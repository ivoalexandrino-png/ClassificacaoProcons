import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { BridgeError, BridgeService } from "../cursor/agents.js";
import {
  agentIdSchema, changesSchema, conversationSchema, followupSchema, projectSchema, runIdSchema, startAgentSchema
} from "./schemas.js";

const textResult = (data: Record<string, unknown>) => ({
  content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
  structuredContent: data
});
const errorResult = (error: unknown) => {
  const bridgeError = error instanceof BridgeError
    ? error
    : new BridgeError("CURSOR_API_ERROR", error instanceof Error ? error.message : "Unexpected provider error");
  const data = { error: { code: bridgeError.code, message: bridgeError.message, details: bridgeError.details } };
  return { ...textResult(data), isError: true };
};

export function createMcpServer(service: BridgeService): McpServer {
  const server = new McpServer({ name: "cursor-chatgpt-bridge", version: "0.1.0" });

  server.registerTool("cursor_list_agents", {
    description: "List Cursor agent sessions registered with this bridge.",
    inputSchema: z.object({})
  }, async () => {
    try {
      return textResult({
        agents: service.listAgents().map(({ project, ...agent }) => ({
          agent_id: agent.agentId, project: project.name, repository: project.repository, branch: agent.branch,
          status: agent.status, last_activity_at: agent.lastActivityAt
        }))
      });
    } catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_get_agent", {
    description: "Get a registered Cursor agent and its runtime capabilities.",
    inputSchema: agentIdSchema
  }, async ({ agent_id }) => {
    try {
      const agent = service.getAgent(agent_id);
      return textResult({
        agent_id: agent.agentId, project: agent.project.name, repository: agent.project.repository,
        branch: agent.branch, working_directory: agent.project.workingDirectory, status: agent.status,
        last_activity_at: agent.lastActivityAt, active_run_id: agent.activeRunId ?? null, metadata: agent.metadata,
        capabilities: { followup: true, cancel_run: true, local_changes: agent.mode === "local" }
      });
    } catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_get_conversation", {
    description: "Read recent bridge-persisted prompts, responses, and events for an agent.",
    inputSchema: conversationSchema
  }, async ({ agent_id, limit }) => {
    try { return textResult({ agent_id, messages: await service.getConversation(agent_id, limit) }); }
    catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_send_followup", {
    description: "Continue an existing Cursor agent conversation with a follow-up prompt.",
    inputSchema: followupSchema
  }, async ({ agent_id, message, wait_for_completion, allow_dangerous_actions }) => {
    try {
      const run = await service.sendFollowup({
        agentId: agent_id, message, waitForCompletion: wait_for_completion, allowDangerousActions: allow_dangerous_actions
      });
      return textResult({
        agent_id, run_id: run.runId, status: run.status, response: run.response,
        started_at: run.startedAt, completed_at: run.completedAt, error: run.error
      });
    } catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_start_agent", {
    description: "Start a new Cursor agent session for a previously registered project.",
    inputSchema: startAgentSchema
  }, async ({ project, repository, working_directory, message, mode }) => {
    try {
      const registered = service.listProjects().find((item) => item.name === project);
      if (!registered) throw new BridgeError("PROJECT_NOT_FOUND", "Register the project before starting an agent", { project });
      if (repository && repository !== registered.repository) {
        throw new BridgeError("PROJECT_NOT_FOUND", "Repository does not match registered project", { project });
      }
      if (working_directory && working_directory !== registered.workingDirectory) {
        throw new BridgeError("PROJECT_NOT_FOUND", "Working directory does not match registered project", { project });
      }
      const run = await service.startAgent({ project, message, mode });
      return textResult({ agent_id: run.agentId, run_id: run.runId, status: run.status, response: run.response });
    } catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_get_run", {
    description: "Get the persisted and live status of a Cursor run.",
    inputSchema: runIdSchema
  }, async ({ run_id }) => {
    try {
      const run = await service.getRun(run_id);
      return textResult({
        run_id: run.runId, agent_id: run.agentId, status: run.status, response: run.response,
        started_at: run.startedAt, completed_at: run.completedAt, error: run.error
      });
    } catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_cancel_run", {
    description: "Cancel a running Cursor run when supported by the Cursor SDK.",
    inputSchema: runIdSchema
  }, async ({ run_id }) => {
    try { return textResult({ run_id, ...(await service.cancelRun(run_id)) }); }
    catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_get_changes", {
    description: "Inspect local Git changes made in the working directory of an agent.",
    inputSchema: changesSchema
  }, async ({ agent_id, max_diff_chars }) => {
    try { return textResult(await service.getChanges(agent_id, max_diff_chars)); }
    catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_project_register", {
    description: "Register or update the project configuration used by Cursor agents.",
    inputSchema: projectSchema
  }, async ({ name, repository, working_directory, default_branch }) => {
    try {
      const project = service.registerProject({
        name, repository, workingDirectory: working_directory, defaultBranch: default_branch
      });
      return textResult({ project });
    } catch (error) { return errorResult(error); }
  });

  server.registerTool("cursor_list_projects", {
    description: "List projects registered with the bridge.",
    inputSchema: z.object({})
  }, async () => textResult({ projects: service.listProjects() }));

  return server;
}
