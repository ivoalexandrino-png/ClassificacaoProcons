import { randomUUID } from "node:crypto";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { ZodRawShape } from "zod";

import type { Config } from "../config.js";
import { AgentLockManager } from "../cursor/agents.js";
import type { CursorAgentProvider, ProviderRun } from "../cursor/types.js";
import { BridgeError, ErrorCodes, errors, toBridgeError } from "../errors.js";
import { collectGitChanges } from "../git/changes.js";
import type { Logger } from "../logger.js";
import { evaluatePolicy } from "../security/policy.js";
import type { AgentRow, RunRow, Store } from "../storage/types.js";
import {
  cancelRunShape,
  getAgentShape,
  getChangesShape,
  getConversationShape,
  getRunShape,
  listAgentsShape,
  listProjectsShape,
  projectRegisterShape,
  schemas,
  sendFollowupShape,
  startAgentShape,
} from "./schemas.js";

export interface ToolContext {
  store: Store;
  provider: CursorAgentProvider;
  locks: AgentLockManager;
  config: Config;
  logger: Logger;
}

interface PublicAgentView {
  agent_id: string;
  project: string | null;
  project_id: string | null;
  repository: string | null;
  branch: string | null;
  working_directory: string | null;
  mode: string;
  status: string | null;
  last_activity_at: string | null;
  created_at: string | null;
}

/** Structured tool handlers, decoupled from the MCP transport for direct testing. */
export function createToolHandlers(ctx: ToolContext) {
  const { store, provider, locks, config, logger } = ctx;

  function publicAgent(agent: AgentRow): PublicAgentView {
    const project = agent.project_id ? store.getProject(agent.project_id) : null;
    return {
      agent_id: agent.agent_id,
      project: project?.name ?? null,
      project_id: agent.project_id,
      repository: agent.repository,
      branch: agent.branch,
      working_directory: agent.working_directory,
      mode: agent.mode,
      status: agent.status,
      last_activity_at: agent.last_activity_at,
      created_at: agent.created_at,
    };
  }

  function requireAgent(agentId: string): AgentRow {
    const agent = store.getAgent(agentId);
    if (!agent) throw errors.agentNotFound({ agent_id: agentId });
    return agent;
  }

  function persistRun(agentId: string, prompt: string, run: ProviderRun): RunRow {
    const runRow = store.createRun({
      runId: run.runId,
      agentId,
      status: run.status,
      prompt,
      startedAt: run.startedAt,
    });
    store.createMessage({ agentId, runId: run.runId, role: "user", content: prompt });
    if (run.response) {
      store.createMessage({
        agentId,
        runId: run.runId,
        role: "assistant",
        content: run.response,
      });
    }
    const patched = store.updateRun(run.runId, {
      status: run.status,
      response: run.response ?? null,
      completedAt: run.completedAt ?? null,
      error: run.error ?? null,
    });
    store.touchAgent(agentId, run.status === "running" ? "running" : run.status);
    return patched ?? runRow;
  }

  function runResponse(run: ProviderRun) {
    return {
      agent_id: run.agentId,
      run_id: run.runId,
      status: run.status,
      response: run.response ?? null,
      started_at: run.startedAt ?? null,
      completed_at: run.completedAt ?? null,
      error: run.error ?? null,
      git: run.git ?? null,
    };
  }

  return {
    async cursor_list_agents(input: unknown) {
      const { include_remote } = schemas.listAgents.parse(input ?? {});
      const agents = store.listAgents().map(publicAgent);

      if (include_remote && provider.configured) {
        try {
          const remote = await provider.listCloudAgents();
          const known = new Set(agents.map((a) => a.agent_id));
          for (const info of remote) {
            if (known.has(info.agentId)) continue;
            agents.push({
              agent_id: info.agentId,
              project: null,
              project_id: null,
              repository: info.repository ?? null,
              branch: info.branch ?? null,
              working_directory: null,
              mode: info.mode,
              status: info.status ?? null,
              last_activity_at: info.lastActivityAt ?? null,
              created_at: info.lastActivityAt ?? null,
            });
          }
        } catch (err) {
          logger.warn("list_cloud_agents_failed", { message: toBridgeError(err).message });
        }
      }

      return { agents };
    },

    async cursor_get_agent(input: unknown) {
      const { agent_id } = schemas.getAgent.parse(input);
      const agent = requireAgent(agent_id);

      let liveStatus = agent.status;
      if (provider.configured) {
        try {
          const info = await provider.getAgentInfo(agent_id, agent.mode);
          if (info?.status) {
            liveStatus = info.status;
            store.touchAgent(agent_id, info.status);
          }
        } catch (err) {
          logger.debug("get_agent_info_failed", { message: toBridgeError(err).message });
        }
      }

      const activeRun = store.getActiveRunForAgent(agent_id) ?? null;
      return {
        ...publicAgent(agent),
        status: liveStatus,
        active_run: activeRun
          ? { run_id: activeRun.run_id, status: activeRun.status, started_at: activeRun.started_at }
          : locks.isLocked(agent_id)
            ? { run_id: locks.activeRunId(agent_id), status: "running" }
            : null,
        metadata: agent.metadata,
        capabilities: {
          send_followup: true,
          get_conversation: true,
          get_run: true,
          cancel_run: provider.configured,
          get_changes: agent.mode === "local",
        },
      };
    },

    async cursor_get_conversation(input: unknown) {
      const { agent_id, limit } = schemas.getConversation.parse(input);
      const agent = requireAgent(agent_id);
      const messages = store.listMessagesByAgent(agent_id, limit).map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        run_id: m.run_id,
        created_at: m.created_at,
        metadata: m.metadata,
      }));
      const runs = store.listRunsByAgent(agent_id, limit).map((r) => ({
        run_id: r.run_id,
        status: r.status,
        started_at: r.started_at,
        completed_at: r.completed_at,
      }));
      return { agent_id: agent.agent_id, mode: agent.mode, messages, runs };
    },

    async cursor_send_followup(input: unknown) {
      const { agent_id, message, wait_for_completion, allow_dangerous_actions } =
        schemas.sendFollowup.parse(input);
      const agent = requireAgent(agent_id);

      const policy = evaluatePolicy(message, allow_dangerous_actions);
      if (policy.blocked) {
        logger.warn("blocked_by_policy", { agent_id, matches: policy.matches });
        return {
          status: "blocked_by_policy",
          reason: policy.reason,
          matches: policy.matches,
          requires_explicit_authorization: true,
        };
      }

      const pendingId = randomUUID();
      const acquired = locks.tryAcquire(agent_id, pendingId);
      if (!acquired.acquired) {
        return { status: "busy", active_run_id: acquired.activeRunId ?? null };
      }

      const startedAt = Date.now();
      try {
        let run: ProviderRun;
        try {
          run = await provider.sendFollowup({
            agentId: agent_id,
            mode: agent.mode,
            message,
            workingDirectory: agent.working_directory ?? undefined,
            timeoutMs: config.runTimeoutMs,
            waitForCompletion: wait_for_completion,
          });
        } catch (err) {
          const bridgeErr = toBridgeError(err);
          if (bridgeErr.code === ErrorCodes.AGENT_BUSY) {
            return { status: "busy", active_run_id: store.getActiveRunForAgent(agent_id)?.run_id ?? null };
          }
          throw bridgeErr;
        }

        persistRun(agent_id, message, run);
        logger.info("cursor_run_completed", {
          agent_id,
          run_id: run.runId,
          status: run.status,
          duration_ms: Date.now() - startedAt,
        });
        return runResponse(run);
      } finally {
        locks.release(agent_id);
      }
    },

    async cursor_start_agent(input: unknown) {
      const parsed = schemas.startAgent.parse(input);
      const { project, message, mode, allow_dangerous_actions } = parsed;

      const projectRow = project
        ? (store.findProjectByName(project) ??
          store.findProjectByRepository(project) ??
          null)
        : null;
      if (project && !projectRow && !parsed.repository && !parsed.working_directory) {
        throw errors.projectNotFound({ project });
      }

      const repository = parsed.repository ?? projectRow?.repository ?? undefined;
      const workingDirectory =
        parsed.working_directory ?? projectRow?.working_directory ?? undefined;
      const branch = parsed.branch ?? projectRow?.default_branch ?? undefined;

      if (mode === "local" && !workingDirectory) {
        throw errors.validation("working_directory is required for local mode", { mode });
      }
      if (mode === "cloud" && !repository) {
        throw errors.validation("repository is required for cloud mode", { mode });
      }

      const policy = evaluatePolicy(message, allow_dangerous_actions);
      if (policy.blocked) {
        logger.warn("blocked_by_policy", { matches: policy.matches });
        return {
          status: "blocked_by_policy",
          reason: policy.reason,
          matches: policy.matches,
          requires_explicit_authorization: true,
        };
      }

      const result = await provider.startAgent({
        mode,
        message,
        model: parsed.model,
        repository,
        workingDirectory,
        branch,
        timeoutMs: config.runTimeoutMs,
        waitForCompletion: true,
      });

      store.upsertAgent({
        agentId: result.agentId,
        projectId: projectRow?.id ?? null,
        mode: result.mode,
        branch: branch ?? null,
        repository: repository ?? null,
        workingDirectory: workingDirectory ?? null,
        status: result.run.status,
        metadata: result.model ? { model: result.model } : {},
      });
      persistRun(result.agentId, message, result.run);

      logger.info("cursor_agent_started", {
        agent_id: result.agentId,
        run_id: result.run.runId,
        mode: result.mode,
      });

      return {
        ...runResponse(result.run),
        agent_id: result.agentId,
        mode: result.mode,
        model: result.model ?? null,
        project: projectRow?.name ?? null,
      };
    },

    async cursor_get_run(input: unknown) {
      const { run_id } = schemas.getRun.parse(input);
      const runRow = store.getRun(run_id);
      if (!runRow) throw errors.runNotFound({ run_id });

      let current = runRow;
      const needsRefresh = runRow.status === "running" || runRow.status === "timeout";
      if (needsRefresh && provider.configured) {
        const agent = store.getAgent(runRow.agent_id);
        if (agent) {
          try {
            const fresh = await provider.getRun({
              runId: run_id,
              agentId: agent.agent_id,
              mode: agent.mode,
              workingDirectory: agent.working_directory ?? undefined,
            });
            const patched = store.updateRun(run_id, {
              status: fresh.status,
              response: fresh.response ?? null,
              completedAt: fresh.completedAt ?? null,
              error: fresh.error ?? null,
            });
            if (fresh.response) {
              store.createMessage({
                agentId: agent.agent_id,
                runId: run_id,
                role: "assistant",
                content: fresh.response,
              });
            }
            if (patched) current = patched;
          } catch (err) {
            logger.debug("get_run_refresh_failed", { message: toBridgeError(err).message });
          }
        }
      }

      return {
        run_id: current.run_id,
        agent_id: current.agent_id,
        status: current.status,
        response: current.response,
        started_at: current.started_at,
        completed_at: current.completed_at,
        error: current.error,
      };
    },

    async cursor_cancel_run(input: unknown) {
      const { run_id } = schemas.cancelRun.parse(input);
      const runRow = store.getRun(run_id);
      if (!runRow) throw errors.runNotFound({ run_id });

      if (!provider.configured) {
        return {
          run_id,
          supported: false,
          cancelled: false,
          reason: "CURSOR_API_KEY is not configured, so runs cannot be cancelled via the SDK.",
        };
      }

      const agent = store.getAgent(runRow.agent_id);
      if (!agent) throw errors.agentNotFound({ agent_id: runRow.agent_id });

      try {
        const result = await provider.cancelRun({
          runId: run_id,
          agentId: agent.agent_id,
          mode: agent.mode,
          workingDirectory: agent.working_directory ?? undefined,
        });
        if (result.cancelled) {
          store.updateRun(run_id, { status: "cancelled", completedAt: new Date().toISOString() });
          locks.release(agent.agent_id);
        }
        return { run_id, ...result, status: result.cancelled ? "cancelled" : runRow.status };
      } catch (err) {
        const bridgeErr = toBridgeError(err);
        return { run_id, supported: true, cancelled: false, reason: bridgeErr.message };
      }
    },

    async cursor_get_changes(input: unknown) {
      const { agent_id, max_diff_chars } = schemas.getChanges.parse(input);
      const agent = requireAgent(agent_id);

      if (agent.mode === "local") {
        if (!agent.working_directory) {
          return { agent_id, mode: agent.mode, available: false, reason: "No working directory recorded for this agent." };
        }
        const changes = await collectGitChanges(agent.working_directory, max_diff_chars);
        return { agent_id, mode: agent.mode, working_directory: agent.working_directory, ...changes };
      }

      // Cloud agent: surface git branch / PR info from the latest run when possible.
      const latestRun = store.listRunsByAgent(agent_id, 1)[0];
      if (!latestRun || !provider.configured) {
        return {
          agent_id,
          mode: agent.mode,
          available: false,
          reason: "Diffs are not available for cloud agents from the bridge; inspect the PR/branch in Cursor.",
        };
      }
      try {
        const fresh = await provider.getRun({
          runId: latestRun.run_id,
          agentId: agent_id,
          mode: agent.mode,
        });
        return {
          agent_id,
          mode: agent.mode,
          available: Boolean(fresh.git?.length),
          branches: fresh.git ?? [],
          note: "Cloud diffs live in Cursor; the bridge reports the branch and PR references only.",
        };
      } catch (err) {
        return {
          agent_id,
          mode: agent.mode,
          available: false,
          reason: toBridgeError(err).message,
        };
      }
    },

    async cursor_project_register(input: unknown) {
      const parsed = schemas.projectRegister.parse(input);
      const project = store.createProject({
        name: parsed.name,
        repository: parsed.repository ?? null,
        workingDirectory: parsed.working_directory ?? null,
        defaultBranch: parsed.default_branch ?? null,
      });
      logger.info("project_registered", { project: project.name });
      return { project };
    },

    async cursor_list_projects(input: unknown) {
      schemas.listProjects.parse(input ?? {});
      return { projects: store.listProjects() };
    },
  };
}

export type ToolHandlers = ReturnType<typeof createToolHandlers>;

interface ToolDefinition {
  name: keyof ToolHandlers;
  title: string;
  description: string;
  inputSchema: ZodRawShape;
}

const TOOL_DEFINITIONS: ToolDefinition[] = [
  {
    name: "cursor_list_agents",
    title: "List Cursor agents",
    description: "List the agents/sessions known to the bridge (optionally including Cursor cloud agents).",
    inputSchema: listAgentsShape,
  },
  {
    name: "cursor_get_agent",
    title: "Get Cursor agent",
    description: "Get details, status, active run and capabilities for a single agent.",
    inputSchema: getAgentShape,
  },
  {
    name: "cursor_get_conversation",
    title: "Get agent conversation",
    description: "Return recent messages and runs for an agent so ChatGPT can catch up on the session.",
    inputSchema: getConversationShape,
  },
  {
    name: "cursor_send_followup",
    title: "Send follow-up to agent",
    description: "Resume an existing agent, send a follow-up prompt, and return the structured result.",
    inputSchema: sendFollowupShape,
  },
  {
    name: "cursor_start_agent",
    title: "Start a new Cursor agent",
    description: "Start a new agent (local or cloud) for a project/repository and return the first run result.",
    inputSchema: startAgentShape,
  },
  {
    name: "cursor_get_run",
    title: "Get run",
    description: "Fetch the status and response of a run by id.",
    inputSchema: getRunShape,
  },
  {
    name: "cursor_cancel_run",
    title: "Cancel run",
    description: "Cancel an active run when supported by the Cursor API.",
    inputSchema: cancelRunShape,
  },
  {
    name: "cursor_get_changes",
    title: "Get agent changes",
    description: "Review what the agent changed (git status/diff for local agents; branch/PR for cloud).",
    inputSchema: getChangesShape,
  },
  {
    name: "cursor_project_register",
    title: "Register project",
    description: "Register a project so it can be resolved by name later.",
    inputSchema: projectRegisterShape,
  },
  {
    name: "cursor_list_projects",
    title: "List projects",
    description: "List the projects registered with the bridge.",
    inputSchema: listProjectsShape,
  },
];

/** Register all bridge tools on an MCP server instance. */
export function registerTools(server: McpServer, ctx: ToolContext): void {
  const handlers = createToolHandlers(ctx);

  for (const def of TOOL_DEFINITIONS) {
    const handler = handlers[def.name] as (input: unknown) => Promise<unknown>;
    server.registerTool(
      def.name,
      {
        title: def.title,
        description: def.description,
        inputSchema: def.inputSchema,
      },
      async (args: unknown) => {
        try {
          const data = await handler(args);
          return {
            content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
            structuredContent: data as Record<string, unknown>,
          };
        } catch (err) {
          const bridgeErr = err instanceof BridgeError ? err : toBridgeError(err);
          ctx.logger.warn("tool_error", { tool: def.name, code: bridgeErr.code });
          const envelope = bridgeErr.toEnvelope();
          return {
            content: [{ type: "text" as const, text: JSON.stringify(envelope, null, 2) }],
            structuredContent: envelope as unknown as Record<string, unknown>,
            isError: true,
          };
        }
      },
    );
  }
}
