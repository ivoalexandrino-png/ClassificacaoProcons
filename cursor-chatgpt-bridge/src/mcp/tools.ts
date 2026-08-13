import { McpServer } from "@modelcontextprotocol/server";
import { toolErrorResult, toolSuccessResult } from "../errors.js";
import type { AgentService } from "../cursor/agents.js";
import type { RunService } from "../cursor/runs.js";
import type { Logger } from "../logger.js";
import { evaluateDangerousActions } from "../security/policy.js";
import type { BridgeStore } from "../storage/store.js";
import {
  cancelRunSchema,
  getAgentSchema,
  getChangesSchema,
  getConversationSchema,
  getRunSchema,
  listAgentsSchema,
  listProjectsSchema,
  projectRegisterSchema,
  sendFollowupSchema,
  startAgentSchema,
} from "./schemas.js";

export interface ToolDeps {
  store: BridgeStore;
  agents: AgentService;
  runs: RunService;
  logger: Logger;
}

export function createMcpServer(deps: ToolDeps): McpServer {
  const server = new McpServer(
    {
      name: "cursor-chatgpt-bridge",
      version: "1.0.0",
    },
    {
      instructions: [
        "You are supervising Cursor Agents through cursor-chatgpt-bridge.",
        "ChatGPT = supervisor/reviewer; Cursor = executor.",
        "Typical flow: cursor_list_projects → cursor_list_agents → cursor_get_conversation → cursor_get_changes → cursor_send_followup.",
        "Never invent authorization for dangerous actions; require allow_dangerous_actions=true only after explicit human approval.",
      ].join(" "),
    },
  );

  server.registerTool(
    "cursor_list_agents",
    {
      title: "List Cursor agents",
      description:
        "List Cursor agents/sessions known by the bridge. Use this when the user asks which agents exist or to find the agent for a project.",
      inputSchema: listAgentsSchema,
      annotations: { readOnlyHint: true },
    },
    async () => {
      try {
        return toolSuccessResult({ agents: deps.agents.listKnownAgents() });
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_agent",
    {
      title: "Get Cursor agent",
      description:
        "Get details for one Cursor agent/session by agent_id, including project, branch, status, and active run.",
      inputSchema: getAgentSchema,
      annotations: { readOnlyHint: true },
    },
    async ({ agent_id }) => {
      try {
        return toolSuccessResult(deps.agents.getAgentDetails(agent_id));
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_conversation",
    {
      title: "Get Cursor conversation",
      description:
        "Read recent prompts/responses/events for a Cursor agent session so ChatGPT can supervise without manual copy-paste.",
      inputSchema: getConversationSchema,
      annotations: { readOnlyHint: true },
    },
    async ({ agent_id, limit }) => {
      try {
        return toolSuccessResult(deps.agents.getConversation(agent_id, limit));
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_send_followup",
    {
      title: "Send Cursor follow-up",
      description:
        "Resume an existing Cursor agent and send a follow-up prompt, preserving session context. Use allow_dangerous_actions=true only with explicit human authorization.",
      inputSchema: sendFollowupSchema,
      annotations: { readOnlyHint: false },
    },
    async ({
      agent_id,
      message,
      wait_for_completion,
      allow_dangerous_actions,
    }) => {
      try {
        const policy = evaluateDangerousActions(
          message,
          allow_dangerous_actions,
        );
        if (!policy.allowed) {
          deps.logger.warn("cursor_followup_blocked", {
            agent_id,
            matched: policy.matched.map((m) => m.description),
          });
          return toolSuccessResult({
            status: "blocked_by_policy",
            reason: policy.reason,
            requires_explicit_authorization: true,
            matched: policy.matched,
          });
        }

        const result = await deps.agents.sendFollowUp({
          agentId: agent_id,
          message,
          waitForCompletion: wait_for_completion,
        });
        return toolSuccessResult(result);
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_start_agent",
    {
      title: "Start Cursor agent",
      description:
        "Start a new Cursor agent session in local or cloud mode and store the returned agent_id in the bridge.",
      inputSchema: startAgentSchema,
      annotations: { readOnlyHint: false },
    },
    async ({ project, repository, working_directory, message, mode }) => {
      try {
        const policy = evaluateDangerousActions(message, false);
        if (!policy.allowed) {
          return toolSuccessResult({
            status: "blocked_by_policy",
            reason: policy.reason,
            requires_explicit_authorization: true,
            matched: policy.matched,
          });
        }

        const result = await deps.agents.startAgent({
          project,
          repository,
          workingDirectory: working_directory,
          message,
          mode,
        });
        return toolSuccessResult(result);
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_run",
    {
      title: "Get Cursor run",
      description: "Get status and response for a specific Cursor run_id.",
      inputSchema: getRunSchema,
      annotations: { readOnlyHint: true },
    },
    async ({ run_id }) => {
      try {
        return toolSuccessResult(await deps.runs.getRun(run_id));
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_cancel_run",
    {
      title: "Cancel Cursor run",
      description:
        "Cancel a running Cursor agent run when supported by the official SDK. Never simulates cancellation.",
      inputSchema: cancelRunSchema,
      annotations: { readOnlyHint: false },
    },
    async ({ run_id }) => {
      try {
        return toolSuccessResult(await deps.runs.cancelRun(run_id));
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_get_changes",
    {
      title: "Get Cursor changes",
      description:
        "Inspect code changes made by a Cursor agent. For local agents returns git status/diff; for cloud agents returns best-effort metadata.",
      inputSchema: getChangesSchema,
      annotations: { readOnlyHint: true },
    },
    async ({ agent_id, max_diff_chars }) => {
      try {
        return toolSuccessResult(
          await deps.agents.getChanges(agent_id, max_diff_chars),
        );
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_project_register",
    {
      title: "Register project",
      description:
        "Persist a named project (repository + working directory) so ChatGPT can later say things like 'continue the Sunday agent'.",
      inputSchema: projectRegisterSchema,
      annotations: { readOnlyHint: false },
    },
    async ({ name, repository, working_directory, default_branch }) => {
      try {
        const project = deps.store.createProject({
          name,
          repository,
          workingDirectory: working_directory,
          defaultBranch: default_branch,
        });
        return toolSuccessResult({
          id: project.id,
          name: project.name,
          repository: project.repository,
          working_directory: project.workingDirectory,
          default_branch: project.defaultBranch,
          created_at: project.createdAt,
        });
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  server.registerTool(
    "cursor_list_projects",
    {
      title: "List projects",
      description: "List projects registered in the bridge.",
      inputSchema: listProjectsSchema,
      annotations: { readOnlyHint: true },
    },
    async () => {
      try {
        const projects = deps.store.listProjects().map((p) => ({
          id: p.id,
          name: p.name,
          repository: p.repository,
          working_directory: p.workingDirectory,
          default_branch: p.defaultBranch,
          created_at: p.createdAt,
          updated_at: p.updatedAt,
        }));
        return toolSuccessResult({ projects });
      } catch (error) {
        return toolErrorResult(error);
      }
    },
  );

  return server;
}
