import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import type { AgentService } from "../cursor/agents.js";
import type { RunService } from "../cursor/runs.js";
import type { Logger } from "../logger.js";
import { BridgeError, errorBody, type ErrorEnvelope } from "./errors.js";
import {
  cancelRunInputShape,
  getAgentInputShape,
  getChangesInputShape,
  getConversationInputShape,
  getRunInputShape,
  listAgentsInputShape,
  listProjectsInputShape,
  projectRegisterInputShape,
  sendFollowupInputShape,
  startAgentInputShape,
} from "./schemas.js";

export interface BridgeDependencies {
  agents: AgentService;
  runs: RunService;
  logger: Logger;
}

function toolSuccess(payload: unknown): CallToolResult {
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    structuredContent: payload as Record<string, unknown>,
  };
}

function toolFailure(envelope: ErrorEnvelope): CallToolResult {
  return {
    content: [{ type: "text", text: JSON.stringify(envelope, null, 2) }],
    structuredContent: envelope as unknown as Record<string, unknown>,
    isError: true,
  };
}

function toErrorEnvelope(error: unknown): ErrorEnvelope {
  if (error instanceof BridgeError) {
    return error.toErrorBody();
  }
  const message = error instanceof Error ? error.message : String(error);
  return errorBody("INTERNAL_ERROR", message);
}

/** Wraps a tool handler so every failure returns a structured error envelope, never a bare stack trace. */
function safeHandler<Args>(
  logger: Logger,
  toolName: string,
  handler: (args: Args) => Promise<unknown>,
): (args: Args) => Promise<CallToolResult> {
  return async (args: Args) => {
    try {
      const result = await handler(args);
      return toolSuccess(result);
    } catch (error) {
      const envelope = toErrorEnvelope(error);
      logger.error({
        event: "mcp_tool_error",
        tool: toolName,
        code: envelope.error.code,
        message: envelope.error.message,
      });
      return toolFailure(envelope);
    }
  };
}

/**
 * Registers every `cursor_*` tool on the given MCP server instance. Kept
 * independent of transport (stdio vs. HTTP) — call this once per server
 * instance, however that instance is connected.
 */
export function registerCursorTools(server: McpServer, deps: BridgeDependencies): void {
  const { agents, runs, logger } = deps;

  server.registerTool(
    "cursor_list_agents",
    {
      title: "List Cursor agents",
      description:
        "List the Cursor agents/sessions known to this bridge (started via cursor_start_agent or otherwise recorded), newest activity first.",
      inputSchema: listAgentsInputShape,
    },
    safeHandler(logger, "cursor_list_agents", () => Promise.resolve({ agents: agents.listAgents() })),
  );

  server.registerTool(
    "cursor_get_agent",
    {
      title: "Get Cursor agent details",
      description:
        "Get full details for one Cursor agent known to the bridge: project, repo, branch, working directory, status, last activity, active run, and capabilities.",
      inputSchema: getAgentInputShape,
    },
    safeHandler(logger, "cursor_get_agent", async (args) => agents.getAgent(args.agent_id)),
  );

  server.registerTool(
    "cursor_get_conversation",
    {
      title: "Get recent conversation for a Cursor agent",
      description:
        "Read the most recent messages/events the bridge recorded for a Cursor agent (user prompts, assistant/agent responses, system/policy events), so ChatGPT can catch up without the user copy-pasting anything.",
      inputSchema: getConversationInputShape,
    },
    safeHandler(logger, "cursor_get_conversation", (args) => {
      const limit = args.limit ?? 20;
      return Promise.resolve({
        agent_id: args.agent_id,
        messages: agents.getConversation(args.agent_id, limit),
        limit,
      });
    }),
  );

  server.registerTool(
    "cursor_send_followup",
    {
      title: "Send a follow-up prompt to an existing Cursor agent",
      description:
        "Resume an existing Cursor agent, preserving its conversation context, and send it a new instruction. Optionally waits for completion. Blocked by policy (BLOCKED_BY_POLICY) for messages that look like they target production or perform destructive actions, unless allow_dangerous_actions=true.",
      inputSchema: sendFollowupInputShape,
    },
    safeHandler(logger, "cursor_send_followup", async (args) =>
      runs.sendFollowup({
        agentId: args.agent_id,
        message: args.message,
        waitForCompletion: args.wait_for_completion,
        allowDangerousActions: args.allow_dangerous_actions,
      }),
    ),
  );

  server.registerTool(
    "cursor_start_agent",
    {
      title: "Start a new Cursor agent",
      description:
        "Start a brand-new Cursor agent (local or cloud) with an initial prompt. The bridge stores the returned agent ID so later tools can resume it.",
      inputSchema: startAgentInputShape,
    },
    safeHandler(logger, "cursor_start_agent", async (args) =>
      agents.startAgent({
        project: args.project,
        repository: args.repository,
        workingDirectory: args.working_directory,
        message: args.message,
        mode: args.mode,
      }),
    ),
  );

  server.registerTool(
    "cursor_get_run",
    {
      title: "Get the status/result of a Cursor run",
      description: "Look up a specific run by ID: status, final response, timestamps, and error (if any).",
      inputSchema: getRunInputShape,
    },
    safeHandler(logger, "cursor_get_run", async (args) => runs.getRun(args.run_id)),
  );

  server.registerTool(
    "cursor_cancel_run",
    {
      title: "Cancel an active Cursor run",
      description:
        "Cancel a run if the underlying Cursor runtime supports it. Never simulated — if cancellation isn't supported, returns { supported: false, reason }.",
      inputSchema: cancelRunInputShape,
    },
    safeHandler(logger, "cursor_cancel_run", async (args) => runs.cancelRun(args.run_id)),
  );

  server.registerTool(
    "cursor_get_changes",
    {
      title: "Inspect what a Cursor agent changed",
      description:
        "Review what a Cursor agent modified: branch, working-tree status, changed files, diff stat, and a (possibly truncated) diff. For cloud agents, returns pushed branches/PR links instead of a full diff.",
      inputSchema: getChangesInputShape,
    },
    safeHandler(logger, "cursor_get_changes", async (args) =>
      runs.getChanges({ agentId: args.agent_id, maxDiffChars: args.max_diff_chars }),
    ),
  );

  server.registerTool(
    "cursor_project_register",
    {
      title: "Register a project",
      description:
        "Register (or update) a named project with its repository/working_directory/default_branch, so future tools can refer to it by name (e.g. 'continue the Sunday agent').",
      inputSchema: projectRegisterInputShape,
    },
    safeHandler(logger, "cursor_project_register", (args) =>
      Promise.resolve(
        agents.registerProject({
          name: args.name,
          repository: args.repository,
          workingDirectory: args.working_directory,
          defaultBranch: args.default_branch,
        }),
      ),
    ),
  );

  server.registerTool(
    "cursor_list_projects",
    {
      title: "List registered projects",
      description: "List every project registered with the bridge via cursor_project_register.",
      inputSchema: listProjectsInputShape,
    },
    safeHandler(logger, "cursor_list_projects", () => Promise.resolve({ projects: agents.listProjects() })),
  );
}
