import { randomUUID } from "node:crypto";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import type { BridgeConfig } from "../config.js";
import type {
  CursorAgentProvider,
  ProviderRunHandle,
  ProviderRunResult,
} from "../cursor/types.js";
import { BridgeError, toErrorPayload } from "../errors.js";
import { collectLocalChanges } from "../git.js";
import { AgentLocks } from "../locks.js";
import type { Logger } from "../logger.js";
import { evaluateMessage } from "../security/policy.js";
import type { BridgeStore } from "../storage/store.js";
import type { AgentRecord, RunStatus } from "../storage/types.js";
import * as schemas from "./schemas.js";

export interface BridgeToolsDeps {
  store: BridgeStore;
  provider: CursorAgentProvider;
  config: BridgeConfig;
  logger: Logger;
  locks?: AgentLocks;
}

interface RunOutcome {
  [key: string]: unknown;
  agent_id: string;
  run_id: string;
  status: RunStatus | "blocked_by_policy" | "busy";
  response: string | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

function providerStatusToRunStatus(status: ProviderRunResult["status"]): RunStatus {
  return status === "completed" ? "completed" : status;
}

export class BridgeTools {
  private readonly store: BridgeStore;
  private readonly provider: CursorAgentProvider;
  private readonly config: BridgeConfig;
  private readonly logger: Logger;
  readonly locks: AgentLocks;

  constructor(deps: BridgeToolsDeps) {
    this.store = deps.store;
    this.provider = deps.provider;
    this.config = deps.config;
    this.logger = deps.logger;
    this.locks = deps.locks ?? new AgentLocks();
  }

  // ------------------------------------------------------------------ agents

  async listAgents(input: { sync_remote?: boolean } = {}): Promise<{
    agents: Array<Record<string, unknown>>;
  }> {
    const syncRemote = input.sync_remote ?? true;
    if (syncRemote && this.provider.configured) {
      try {
        const remote = await this.provider.listAgents();
        for (const info of remote) {
          this.store.upsertAgent({
            agent_id: info.agentId,
            mode: info.runtime,
            status: info.status ?? "unknown",
            metadata: {
              name: info.name,
              repos: info.repos,
              archived: info.archived,
            },
          });
        }
      } catch (err) {
        this.logger.warn("cursor_list_agents_remote_failed", {
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
    const agents = this.store.listAgents().map((agent) => this.describeAgent(agent, false));
    return { agents };
  }

  async getAgent(input: { agent_id: string }): Promise<Record<string, unknown>> {
    const agent = await this.requireAgent(input.agent_id);
    return this.describeAgent(agent, true);
  }

  private async requireAgent(agentId: string): Promise<AgentRecord> {
    const local = this.store.getAgent(agentId);
    if (local) return local;
    if (this.provider.configured) {
      try {
        const info = await this.provider.getAgent(agentId);
        return this.store.upsertAgent({
          agent_id: info.agentId,
          mode: info.runtime,
          status: info.status ?? "unknown",
          metadata: { name: info.name, repos: info.repos },
        });
      } catch (err) {
        if (err instanceof BridgeError && err.code === "AGENT_NOT_FOUND") throw err;
        this.logger.warn("cursor_get_agent_remote_failed", {
          agent_id: agentId,
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
    throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", { agent_id: agentId });
  }

  private describeAgent(agent: AgentRecord, detailed: boolean): Record<string, unknown> {
    const project = agent.project_id ? this.store.getProjectById(agent.project_id) : undefined;
    const metadata = agent.metadata;
    const activeRun = this.store.getActiveRunForAgent(agent.agent_id);
    const base: Record<string, unknown> = {
      agent_id: agent.agent_id,
      project: project?.name ?? null,
      repository:
        (metadata.repository as string | undefined) ??
        (Array.isArray(metadata.repos) ? (metadata.repos[0] as string | undefined) : undefined) ??
        project?.repository ??
        null,
      branch: agent.branch,
      status: agent.status,
      last_activity_at: agent.last_activity_at,
    };
    if (!detailed) return base;
    return {
      ...base,
      mode: agent.mode,
      working_directory: this.resolveWorkingDirectory(agent) ?? null,
      created_at: agent.created_at,
      active_run: activeRun
        ? { run_id: activeRun.run_id, status: activeRun.status, started_at: activeRun.started_at }
        : null,
      metadata,
      capabilities: {
        send_followup: true,
        get_conversation: true,
        get_run: true,
        cancel_run: true,
        get_changes: true,
        local_git_diff: Boolean(this.resolveWorkingDirectory(agent)),
      },
    };
  }

  private resolveWorkingDirectory(agent: AgentRecord): string | undefined {
    const fromMetadata = agent.metadata.working_directory;
    if (typeof fromMetadata === "string" && fromMetadata) return fromMetadata;
    if (agent.project_id) {
      const project = this.store.getProjectById(agent.project_id);
      if (project?.working_directory) return project.working_directory;
    }
    return undefined;
  }

  // ------------------------------------------------------------ conversation

  async getConversation(input: { agent_id: string; limit?: number }): Promise<{
    agent_id: string;
    messages: Array<Record<string, unknown>>;
    note: string;
  }> {
    const agent = await this.requireAgent(input.agent_id);
    const messages = this.store.getConversation(agent.agent_id, input.limit ?? 20);
    return {
      agent_id: agent.agent_id,
      messages: messages.map((m) => ({
        role: m.role,
        content: m.content,
        run_id: m.run_id,
        created_at: m.created_at,
        metadata: m.metadata,
      })),
      note: "Messages are recorded by the bridge for every prompt/response that passes through it.",
    };
  }

  // ---------------------------------------------------------------- followup

  async sendFollowup(input: {
    agent_id: string;
    message: string;
    wait_for_completion?: boolean;
    allow_dangerous_actions?: boolean;
  }): Promise<Record<string, unknown>> {
    const agent = await this.requireAgent(input.agent_id);

    const policy = evaluateMessage(input.message, input.allow_dangerous_actions ?? false);
    if (!policy.allowed) {
      this.logger.warn("cursor_followup_blocked_by_policy", {
        agent_id: agent.agent_id,
        matches: policy.matches,
      });
      return {
        status: "blocked_by_policy",
        reason: policy.reason,
        requires_explicit_authorization: true,
        matches: policy.matches,
      };
    }

    const busy = this.checkBusy(agent.agent_id);
    if (busy) return busy;

    return this.executeRun({
      agent,
      message: input.message,
      waitForCompletion: input.wait_for_completion ?? true,
      startRun: (opts) => this.provider.sendFollowup(agent.agent_id, input.message, opts),
    });
  }

  // ------------------------------------------------------------- start agent

  async startAgent(input: {
    project?: string;
    repository?: string;
    working_directory?: string;
    branch?: string;
    message: string;
    mode?: "local" | "cloud";
    wait_for_completion?: boolean;
    allow_dangerous_actions?: boolean;
  }): Promise<Record<string, unknown>> {
    const policy = evaluateMessage(input.message, input.allow_dangerous_actions ?? false);
    if (!policy.allowed) {
      return {
        status: "blocked_by_policy",
        reason: policy.reason,
        requires_explicit_authorization: true,
        matches: policy.matches,
      };
    }

    let project = undefined;
    if (input.project) {
      project = this.store.getProjectByName(input.project);
      if (!project) {
        throw new BridgeError("PROJECT_NOT_FOUND", "Project is not registered", {
          project: input.project,
          hint: "Register it first with cursor_project_register",
        });
      }
    }

    const mode = input.mode ?? "cloud";
    const repository = input.repository ?? project?.repository ?? undefined;
    const workingDirectory = input.working_directory ?? project?.working_directory ?? undefined;
    const branch = input.branch ?? project?.default_branch ?? undefined;

    if (mode === "local" && !workingDirectory) {
      throw new BridgeError("INVALID_INPUT", "Local mode requires a working_directory", {
        hint: "Pass working_directory or register the project with one",
      });
    }
    if (mode === "cloud" && !repository) {
      throw new BridgeError("INVALID_INPUT", "Cloud mode requires a repository URL", {
        hint: "Pass repository or register the project with one",
      });
    }

    const { agent: created, run } = await this.provider.createAgent({
      message: input.message,
      mode,
      repository,
      branch,
      workingDirectory,
    });

    const agent = this.store.upsertAgent({
      agent_id: created.agentId,
      project_id: project?.id ?? null,
      mode,
      branch: branch ?? null,
      status: "running",
      metadata: {
        repository: repository ?? null,
        working_directory: workingDirectory ?? null,
      },
    });

    this.logger.info("cursor_agent_started", {
      agent_id: agent.agent_id,
      mode,
      project: project?.name,
    });

    return this.executeRun({
      agent,
      message: input.message,
      waitForCompletion: input.wait_for_completion ?? false,
      existingRun: run,
      startRun: () => Promise.resolve(run),
    });
  }

  // ------------------------------------------------------- run orchestration

  private checkBusy(agentId: string): Record<string, unknown> | undefined {
    const lockedRun = this.locks.activeRunId(agentId);
    if (lockedRun) {
      return { status: "busy", agent_id: agentId, active_run_id: lockedRun };
    }
    return undefined;
  }

  private async executeRun(params: {
    agent: AgentRecord;
    message: string;
    waitForCompletion: boolean;
    startRun: (opts: { workingDirectory?: string }) => Promise<ProviderRunHandle>;
    existingRun?: ProviderRunHandle;
  }): Promise<RunOutcome> {
    const { agent, message, waitForCompletion } = params;
    const sentinel = `pending:${randomUUID()}`;
    if (!this.locks.acquire(agent.agent_id, sentinel)) {
      return {
        agent_id: agent.agent_id,
        run_id: this.locks.activeRunId(agent.agent_id) ?? "",
        status: "busy",
        response: null,
        started_at: null,
        completed_at: null,
        error: null,
      };
    }

    let handle: ProviderRunHandle;
    try {
      handle =
        params.existingRun ??
        (await params.startRun({ workingDirectory: this.resolveWorkingDirectory(agent) }));
    } catch (err) {
      this.locks.release(agent.agent_id, sentinel);
      if (err instanceof BridgeError && err.code === "AGENT_BUSY") {
        const activeRun = this.store.getActiveRunForAgent(agent.agent_id);
        return {
          agent_id: agent.agent_id,
          run_id: activeRun?.run_id ?? "",
          status: "busy",
          response: null,
          started_at: activeRun?.started_at ?? null,
          completed_at: null,
          error: null,
        };
      }
      throw err;
    }

    // Swap the sentinel for the real run id (single-threaded, no await between).
    this.locks.release(agent.agent_id, sentinel);
    this.locks.acquire(agent.agent_id, handle.runId);

    const run = this.store.createRun({
      run_id: handle.runId,
      agent_id: agent.agent_id,
      prompt: message,
    });
    this.store.addMessage({
      agent_id: agent.agent_id,
      run_id: handle.runId,
      role: "user",
      content: message,
    });
    this.store.touchAgent(agent.agent_id, "running");
    this.logger.info("cursor_run_started", { agent_id: agent.agent_id, run_id: handle.runId });

    const settle = this.settleRun(agent.agent_id, handle);

    if (!waitForCompletion) {
      // Keep settling in the background; result stays queryable via cursor_get_run.
      settle.catch(() => {});
      return {
        agent_id: agent.agent_id,
        run_id: handle.runId,
        status: "running",
        response: null,
        started_at: run.started_at,
        completed_at: null,
        error: null,
      };
    }

    const timeoutMs = this.config.runTimeoutMs;
    const timedOut = Symbol("timeout");
    const raced = await Promise.race([
      settle,
      new Promise<typeof timedOut>((resolve) => {
        const timer = setTimeout(() => resolve(timedOut), timeoutMs);
        timer.unref?.();
      }),
    ]);

    if (raced === timedOut) {
      this.store.updateRun(handle.runId, { status: "timeout" });
      this.logger.warn("cursor_run_timeout", {
        agent_id: agent.agent_id,
        run_id: handle.runId,
        timeout_ms: timeoutMs,
      });
      // Keep waiting in the background so the final result is still captured.
      settle.catch(() => {});
      return {
        agent_id: agent.agent_id,
        run_id: handle.runId,
        status: "timeout",
        response: null,
        started_at: run.started_at,
        completed_at: null,
        error: `Run did not finish within ${timeoutMs} ms; it may still be executing. Check later with cursor_get_run.`,
      };
    }

    const finalRun = this.store.getRun(handle.runId);
    return {
      agent_id: agent.agent_id,
      run_id: handle.runId,
      status: finalRun?.status ?? "completed",
      response: finalRun?.response ?? null,
      started_at: finalRun?.started_at ?? run.started_at,
      completed_at: finalRun?.completed_at ?? null,
      error: finalRun?.error ?? null,
    };
  }

  /** Wait for the provider run to finish and persist the outcome. Always releases the lock. */
  private async settleRun(agentId: string, handle: ProviderRunHandle): Promise<void> {
    const startedAt = Date.now();
    try {
      const result = await handle.wait();
      const status = providerStatusToRunStatus(result.status);
      this.store.updateRun(handle.runId, {
        status,
        response: result.response ?? null,
        error: result.errorMessage ?? null,
        completed: true,
      });
      if (result.response) {
        this.store.addMessage({
          agent_id: agentId,
          run_id: handle.runId,
          role: "assistant",
          content: result.response,
        });
      }
      const agentUpdate: Record<string, unknown> = {};
      if (result.git) agentUpdate.git = result.git;
      this.store.upsertAgent({
        agent_id: agentId,
        status: status === "completed" ? "finished" : status,
        metadata: agentUpdate,
        branch: result.git?.branches?.[0]?.branch ?? undefined,
      });
      this.logger.info("cursor_run_completed", {
        agent_id: agentId,
        run_id: handle.runId,
        status,
        duration_ms: Date.now() - startedAt,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.store.updateRun(handle.runId, { status: "error", error: message, completed: true });
      this.store.touchAgent(agentId, "error");
      this.logger.error("cursor_run_failed", {
        agent_id: agentId,
        run_id: handle.runId,
        message,
      });
    } finally {
      this.locks.release(agentId, handle.runId);
    }
  }

  // -------------------------------------------------------------------- runs

  async getRun(input: { run_id: string }): Promise<Record<string, unknown>> {
    let run = this.store.getRun(input.run_id);
    if (!run) {
      throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: input.run_id });
    }

    // Refresh non-terminal runs from the Cursor API (covers bridge restarts).
    if (run.status === "running" || run.status === "timeout") {
      if (this.provider.configured) {
        try {
          const snapshot = await this.provider.getRun(run.agent_id, run.run_id);
          if (snapshot.status !== "running") {
            const status = providerStatusToRunStatus(snapshot.status);
            this.store.updateRun(run.run_id, {
              status,
              response: snapshot.response ?? null,
              error: snapshot.errorMessage ?? null,
              completed: true,
            });
            if (snapshot.response && !this.hasAssistantMessage(run.run_id)) {
              this.store.addMessage({
                agent_id: run.agent_id,
                run_id: run.run_id,
                role: "assistant",
                content: snapshot.response,
              });
            }
            this.locks.release(run.agent_id, run.run_id);
            run = this.store.getRun(run.run_id)!;
          }
        } catch (err) {
          this.logger.warn("cursor_get_run_remote_failed", {
            run_id: run.run_id,
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    }

    return {
      run_id: run.run_id,
      agent_id: run.agent_id,
      status: run.status,
      prompt: run.prompt,
      response: run.response,
      started_at: run.started_at,
      completed_at: run.completed_at,
      error: run.error,
    };
  }

  private hasAssistantMessage(runId: string): boolean {
    const run = this.store.getRun(runId);
    if (!run) return false;
    return this.store
      .getConversation(run.agent_id, 200)
      .some((m) => m.run_id === runId && m.role === "assistant");
  }

  async cancelRun(input: { run_id: string }): Promise<Record<string, unknown>> {
    const run = this.store.getRun(input.run_id);
    if (!run) {
      throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: input.run_id });
    }
    if (run.status !== "running" && run.status !== "timeout") {
      return {
        supported: false,
        reason: `Run is already in terminal state '${run.status}'`,
        run_id: run.run_id,
        status: run.status,
      };
    }
    const outcome = await this.provider.cancelRun(run.agent_id, run.run_id);
    if (!outcome.supported) {
      return { supported: false, reason: outcome.reason ?? "Cancellation not supported" };
    }
    this.store.updateRun(run.run_id, { status: "cancelled", completed: true });
    this.store.touchAgent(run.agent_id, "cancelled");
    this.locks.release(run.agent_id, run.run_id);
    this.logger.info("cursor_run_cancelled", { agent_id: run.agent_id, run_id: run.run_id });
    return { supported: true, run_id: run.run_id, status: "cancelled" };
  }

  // ------------------------------------------------------------------ changes

  async getChanges(input: {
    agent_id: string;
    max_diff_chars?: number;
  }): Promise<Record<string, unknown>> {
    const agent = await this.requireAgent(input.agent_id);
    const maxDiffChars = input.max_diff_chars ?? this.config.maxDiffChars;
    const workingDirectory = this.resolveWorkingDirectory(agent);

    if (workingDirectory) {
      try {
        const changes = await collectLocalChanges(workingDirectory, maxDiffChars);
        return { agent_id: agent.agent_id, source: "local_git", ...changes };
      } catch (err) {
        throw new BridgeError(
          "INTERNAL_ERROR",
          "Failed to read git state from the working directory",
          {
            working_directory: workingDirectory,
            message: err instanceof Error ? err.message : String(err),
          },
        );
      }
    }

    // Cloud agent: report pushed branches / PRs from the Cursor API.
    let git = agent.metadata.git as
      | { branches?: Array<{ repoUrl: string; branch?: string; prUrl?: string }> }
      | undefined;
    if (this.provider.configured) {
      const latestRun = this.store.listRunsForAgent(agent.agent_id, 1)[0];
      if (latestRun) {
        try {
          const snapshot = await this.provider.getRun(agent.agent_id, latestRun.run_id);
          if (snapshot.git) git = snapshot.git;
        } catch (err) {
          this.logger.warn("cursor_get_changes_remote_failed", {
            agent_id: agent.agent_id,
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    }

    const branches = git?.branches ?? [];
    return {
      agent_id: agent.agent_id,
      source: "cursor_cloud",
      branch: branches[0]?.branch ?? agent.branch ?? null,
      clean: null,
      files: [],
      diff_stat: "",
      diff: "",
      branches,
      pull_requests: branches.map((b) => b.prUrl).filter(Boolean),
      note:
        "Cloud agents work on a Cursor-managed VM; the full diff is not exposed by the Cloud Agents API. " +
        "Review the pushed branch / pull request listed above, or register a local working_directory for this agent's project.",
    };
  }

  // ---------------------------------------------------------------- projects

  registerProject(input: {
    name: string;
    repository?: string;
    working_directory?: string;
    default_branch?: string;
  }): Record<string, unknown> {
    const project = this.store.registerProject(input);
    this.logger.info("project_registered", { project: project.name });
    return { project };
  }

  listProjects(): Record<string, unknown> {
    return { projects: this.store.listProjects() };
  }
}

// ---------------------------------------------------------------------------
// MCP registration
// ---------------------------------------------------------------------------

type ToolResult = {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
};

function ok(payload: unknown): ToolResult {
  return { content: [{ type: "text", text: JSON.stringify(payload, null, 2) }] };
}

function fail(err: unknown): ToolResult {
  return {
    content: [{ type: "text", text: JSON.stringify(toErrorPayload(err), null, 2) }],
    isError: true,
  };
}

async function guard(fn: () => Promise<unknown> | unknown): Promise<ToolResult> {
  try {
    return ok(await fn());
  } catch (err) {
    return fail(err);
  }
}

export function createMcpServer(tools: BridgeTools): McpServer {
  const server = new McpServer({ name: "cursor-chatgpt-bridge", version: "0.1.0" });

  server.registerTool(
    "cursor_list_agents",
    {
      title: "List Cursor agents",
      description:
        "List Cursor agents/sessions known to the bridge (merged with the Cursor Cloud API when configured).",
      inputSchema: schemas.listAgentsInput,
    },
    async (args) => guard(() => tools.listAgents(args)),
  );

  server.registerTool(
    "cursor_get_agent",
    {
      title: "Get Cursor agent",
      description:
        "Get details for one Cursor agent: project, repository, branch, status, active run and capabilities.",
      inputSchema: schemas.getAgentInput,
    },
    async (args) => guard(() => tools.getAgent(args)),
  );

  server.registerTool(
    "cursor_get_conversation",
    {
      title: "Get agent conversation",
      description:
        "Read the recent messages (user prompts, agent responses, system events) recorded for a Cursor agent.",
      inputSchema: schemas.getConversationInput,
    },
    async (args) => guard(() => tools.getConversation(args)),
  );

  server.registerTool(
    "cursor_send_followup",
    {
      title: "Send follow-up to Cursor agent",
      description:
        "Resume an existing Cursor agent (context preserved) and send it a follow-up prompt. " +
        "Dangerous instructions (production, destructive commands) are blocked unless allow_dangerous_actions=true " +
        "after explicit human authorization.",
      inputSchema: schemas.sendFollowupInput,
    },
    async (args) => guard(() => tools.sendFollowup(args)),
  );

  server.registerTool(
    "cursor_start_agent",
    {
      title: "Start new Cursor agent",
      description:
        "Start a new Cursor agent session (cloud VM against a GitHub repo, or local against a working directory on the bridge host).",
      inputSchema: schemas.startAgentInput,
    },
    async (args) => guard(() => tools.startAgent(args)),
  );

  server.registerTool(
    "cursor_get_run",
    {
      title: "Get run status",
      description:
        "Get the status/result of a run started via cursor_send_followup or cursor_start_agent.",
      inputSchema: schemas.getRunInput,
    },
    async (args) => guard(() => tools.getRun(args)),
  );

  server.registerTool(
    "cursor_cancel_run",
    {
      title: "Cancel run",
      description:
        "Cancel an active Cursor run. Returns supported=false when the runtime cannot cancel (never simulates).",
      inputSchema: schemas.cancelRunInput,
    },
    async (args) => guard(() => tools.cancelRun(args)),
  );

  server.registerTool(
    "cursor_get_changes",
    {
      title: "Get agent code changes",
      description:
        "Review what the agent changed: git status/diff for local agents, pushed branches and PRs for cloud agents.",
      inputSchema: schemas.getChangesInput,
    },
    async (args) => guard(() => tools.getChanges(args)),
  );

  server.registerTool(
    "cursor_project_register",
    {
      title: "Register project",
      description:
        "Register a project (name, repository, working directory, default branch) so agents can be resolved by project name.",
      inputSchema: schemas.projectRegisterInput,
    },
    async (args) => guard(() => tools.registerProject(args)),
  );

  server.registerTool(
    "cursor_list_projects",
    {
      title: "List projects",
      description: "List the projects registered in the bridge.",
      inputSchema: schemas.listProjectsInput,
    },
    async () => guard(() => tools.listProjects()),
  );

  return server;
}

// Re-export for consumers/tests that need the raw zod shapes.
export { z };
