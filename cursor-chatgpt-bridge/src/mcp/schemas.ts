import { z } from "zod";

export const listAgentsInput = {
  sync_remote: z
    .boolean()
    .default(true)
    .describe("Also refresh the agent list from the Cursor API when configured"),
};

export const getAgentInput = {
  agent_id: z.string().min(1).describe("Cursor agent ID (bc-... for cloud agents)"),
};

export const getConversationInput = {
  agent_id: z.string().min(1).describe("Cursor agent ID"),
  limit: z
    .number()
    .int()
    .min(1)
    .max(200)
    .default(20)
    .describe("Maximum number of recent messages to return"),
};

export const sendFollowupInput = {
  agent_id: z.string().min(1).describe("Cursor agent ID to resume"),
  message: z.string().min(1).describe("Follow-up prompt for the agent"),
  wait_for_completion: z
    .boolean()
    .default(true)
    .describe("Wait for the run to finish (subject to the bridge timeout) before returning"),
  allow_dangerous_actions: z
    .boolean()
    .default(false)
    .describe(
      "Explicit human authorization for messages matching dangerous-action policies (production, destructive commands, etc.)",
    ),
};

export const startAgentInput = {
  project: z
    .string()
    .min(1)
    .optional()
    .describe("Registered project name (fills repository/working_directory defaults)"),
  repository: z
    .string()
    .min(1)
    .optional()
    .describe("GitHub repository URL (required for cloud mode when no project default exists)"),
  working_directory: z
    .string()
    .min(1)
    .optional()
    .describe("Local working directory (required for local mode when no project default exists)"),
  branch: z.string().min(1).optional().describe("Starting branch/ref for cloud agents"),
  message: z.string().min(1).describe("Initial prompt for the new agent"),
  mode: z
    .enum(["local", "cloud"])
    .default("cloud")
    .describe("Where the agent runs: on this bridge host (local) or on a Cursor cloud VM (cloud)"),
  wait_for_completion: z
    .boolean()
    .default(false)
    .describe("Wait for the initial run to finish before returning"),
  allow_dangerous_actions: z.boolean().default(false),
};

export const getRunInput = {
  run_id: z.string().min(1).describe("Run ID returned by cursor_send_followup / cursor_start_agent"),
};

export const cancelRunInput = {
  run_id: z.string().min(1).describe("Run ID to cancel"),
};

export const getChangesInput = {
  agent_id: z.string().min(1).describe("Cursor agent ID"),
  max_diff_chars: z
    .number()
    .int()
    .min(200)
    .max(200_000)
    .optional()
    .describe("Cap for the returned diff, in characters (default 30000)"),
};

export const projectRegisterInput = {
  name: z.string().min(1).describe("Short project name, e.g. 'sunday'"),
  repository: z.string().min(1).optional().describe("GitHub repository URL"),
  working_directory: z
    .string()
    .min(1)
    .optional()
    .describe("Local checkout path on the bridge host (enables local agents and git diff)"),
  default_branch: z.string().min(1).optional().describe("Default branch, e.g. 'main'"),
};

export const listProjectsInput = {};
