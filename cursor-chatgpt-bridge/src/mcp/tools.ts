import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { BridgeError, isBridgeError } from "../errors.js";
import type { AgentService } from "../cursor/agents.js";
import { CursorSdkProvider, getGitChanges } from "../cursor/client.js";
import type { RunService } from "../cursor/runs.js";
import type { BridgeStore } from "../storage/store.js";
import {
  cancelRunSchema,
  getAgentSchema,
  getChangesSchema,
  getConversationSchema,
  getRunSchema,
  listAgentsSchema,
  listProjectsSchema,
  registerProjectSchema,
  sendFollowupSchema,
  startAgentSchema,
} from "./schemas.js";

function toolError(error: unknown): { content: Array<{ type: "text"; text: string }>; isError: true } {
  if (isBridgeError(error)) {
    return {
      content: [{ type: "text", text: JSON.stringify(error.toJSON(), null, 2) }],
      isError: true,
    };
  }
  const body = {
    error: {
      code: "INTERNAL_ERROR",
      message: error instanceof Error ? error.message : "Unknown error",
    },
  };
  return {
    content: [{ type: "text", text: JSON.stringify(body, null, 2) }],
    isError: true,
  };
}

function toolSuccess(data: unknown): { content: Array<{ type: "text"; text: string }> } {
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
  };
}

export interface ToolContext {
  store: BridgeStore;
  agentService: AgentService;
  runService: RunService;
  cursor: CursorSdkProvider;
}

export function registerMcpTools(server: McpServer, ctx: ToolContext): void {
  server.registerTool(
    "cursor_list_agents",
    {
      description: "List Cursor agents known to the bridge and synced from Cursor SDK.",
      inputSchema: listAgentsSchema,
    },
    async () => {
      try {
        const agents = ctx.agentService.listKnownAgents();
        return toolSuccess({ agents });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_agent",
    {
      description: "Get details for a Cursor agent by agent_id.",
      inputSchema: getAgentSchema,
    },
    async (args) => {
      try {
        const input = getAgentSchema.parse(args);
        const agent = ctx.agentService.getAgentDetails(input.agent_id);
        if (!agent) {
          throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
            agent_id: input.agent_id,
          });
        }
        return toolSuccess(agent);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_conversation",
    {
      description: "Get recent conversation messages for an agent from bridge persistence.",
      inputSchema: getConversationSchema,
    },
    async (args) => {
      try {
        const input = getConversationSchema.parse(args);
        const agent = ctx.store.getAgent(input.agent_id);
        if (!agent) {
          throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
            agent_id: input.agent_id,
          });
        }
        const messages = ctx.store.getConversation(input.agent_id, input.limit).map((m) => ({
          id: m.id,
          agent_id: m.agent_id,
          run_id: m.run_id,
          role: m.role,
          content: m.content,
          created_at: m.created_at,
          metadata: m.metadata ? JSON.parse(m.metadata) : undefined,
        }));
        return toolSuccess({ agent_id: input.agent_id, messages });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_send_followup",
    {
      description:
        "Send a follow-up message to an existing Cursor agent, preserving session context.",
      inputSchema: sendFollowupSchema,
    },
    async (args) => {
      try {
        const input = sendFollowupSchema.parse(args);
        const result = await ctx.runService.sendFollowup(input);
        return toolSuccess(result);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_start_agent",
    {
      description: "Start a new Cursor agent session (local or cloud).",
      inputSchema: startAgentSchema,
    },
    async (args) => {
      try {
        const input = startAgentSchema.parse(args);
        let projectId: string | null = null;
        let repository = input.repository;
        let workingDirectory = input.working_directory;
        let branch = input.branch;

        if (input.project) {
          const project = ctx.store.getProjectByName(input.project);
          if (!project) {
            throw new BridgeError("PROJECT_NOT_FOUND", "Project not found", {
              project: input.project,
            });
          }
          projectId = project.id;
          repository = repository ?? project.repository;
          workingDirectory = workingDirectory ?? project.working_directory;
          branch = branch ?? project.default_branch;
        }

        const created = await ctx.cursor.createAgent({
          mode: input.mode,
          message: input.message,
          repository,
          workingDirectory,
          branch,
        });

        ctx.store.upsertAgent({
          agent_id: created.agentId,
          project_id: projectId,
          mode: input.mode,
          branch: branch ?? null,
          status: "running",
          working_directory: workingDirectory ?? null,
          repository: repository ?? null,
        });

        ctx.store.createRun({
          run_id: created.runId,
          agent_id: created.agentId,
          status: "running",
          prompt: input.message,
        });
        ctx.store.addMessage({
          agent_id: created.agentId,
          run_id: created.runId,
          role: "user",
          content: input.message,
        });

        return toolSuccess({
          agent_id: created.agentId,
          run_id: created.runId,
          status: "running",
          mode: input.mode,
        });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_run",
    {
      description: "Get run status and result by run_id.",
      inputSchema: getRunSchema,
    },
    async (args) => {
      try {
        const input = getRunSchema.parse(args);
        const run = ctx.runService.getRun(input.run_id);
        if (!run) {
          throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: input.run_id });
        }
        return toolSuccess(run);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_cancel_run",
    {
      description: "Cancel an active Cursor agent run when supported by the API.",
      inputSchema: cancelRunSchema,
    },
    async (args) => {
      try {
        const input = cancelRunSchema.parse(args);
        const result = await ctx.runService.cancelRun(input.run_id);
        return toolSuccess(result);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_changes",
    {
      description: "Get git working tree changes for a local agent working directory.",
      inputSchema: getChangesSchema,
    },
    async (args) => {
      try {
        const input = getChangesSchema.parse(args);
        const agent = ctx.store.getAgent(input.agent_id);
        if (!agent) {
          throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
            agent_id: input.agent_id,
          });
        }
        if (agent.mode !== "local" || !agent.working_directory) {
          return toolSuccess({
            supported: false,
            reason: "Git changes are only available for local agents with a working directory.",
          });
        }
        const changes = await getGitChanges(agent.working_directory, input.max_diff_chars);
        return toolSuccess(changes);
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_project_register",
    {
      description: "Register a project configuration for agent lookup.",
      inputSchema: registerProjectSchema,
    },
    async (args) => {
      try {
        const input = registerProjectSchema.parse(args);
        const project = ctx.store.registerProject(input);
        return toolSuccess({ project });
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    "cursor_list_projects",
    {
      description: "List registered projects.",
      inputSchema: listProjectsSchema,
    },
    async () => {
      try {
        const projects = ctx.store.listProjects();
        return toolSuccess({ projects });
      } catch (error) {
        return toolError(error);
      }
    },
  );
}
