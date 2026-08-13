import { z } from "zod";

/**
 * Zod input shapes for each MCP tool. Each export is a plain object of Zod
 * types (not a `z.object(...)`), matching the `ZodRawShapeCompat` the MCP
 * SDK's `registerTool()` expects.
 */

export const listAgentsInputShape = {};

export const getAgentInputShape = {
  agent_id: z.string().min(1).describe("Bridge-known Cursor agent ID (e.g. bc-... for cloud, agent-... for local)."),
};

export const getConversationInputShape = {
  agent_id: z.string().min(1).describe("Bridge-known Cursor agent ID."),
  limit: z
    .number()
    .int()
    .positive()
    .max(200)
    .optional()
    .describe("Max number of recent messages to return (default 20)."),
};

export const sendFollowupInputShape = {
  agent_id: z.string().min(1).describe("Bridge-known Cursor agent ID to resume."),
  message: z.string().min(1).describe("Follow-up instruction to send to the agent."),
  wait_for_completion: z
    .boolean()
    .optional()
    .default(true)
    .describe("If true, block until the run finishes or CURSOR_RUN_TIMEOUT_MS elapses."),
  allow_dangerous_actions: z
    .boolean()
    .optional()
    .default(false)
    .describe(
      "Must be explicitly true to send a message that matches the dangerous-action policy (prod/deploy/destroy/force-push/etc.).",
    ),
};

export const startAgentInputShape = {
  project: z
    .string()
    .optional()
    .describe("Name of a project registered via cursor_project_register, used to fill repository/working_directory/branch defaults."),
  repository: z.string().optional().describe("Repository URL. Required for mode=cloud unless supplied by `project`."),
  working_directory: z
    .string()
    .optional()
    .describe("Absolute working directory. Required for mode=local unless supplied by `project`."),
  message: z.string().min(1).describe("Initial instruction/prompt for the new agent."),
  mode: z.enum(["local", "cloud"]).optional().default("local").describe("Runtime: local (this machine) or cloud (Cursor-hosted VM)."),
};

export const getRunInputShape = {
  run_id: z.string().min(1).describe("Bridge-known run ID."),
};

export const cancelRunInputShape = {
  run_id: z.string().min(1).describe("Bridge-known run ID to cancel."),
};

export const getChangesInputShape = {
  agent_id: z.string().min(1).describe("Bridge-known Cursor agent ID."),
  max_diff_chars: z
    .number()
    .int()
    .positive()
    .max(200_000)
    .optional()
    .default(30_000)
    .describe("Truncate the diff text to this many characters (default 30000)."),
};

export const projectRegisterInputShape = {
  name: z.string().min(1).describe("Unique, human-friendly project name (e.g. 'sunday')."),
  repository: z.string().optional().describe("Default repository URL for cloud agents on this project."),
  working_directory: z.string().optional().describe("Default working directory for local agents on this project."),
  default_branch: z.string().optional().describe("Default branch/ref new agents should start from."),
};

export const listProjectsInputShape = {};
