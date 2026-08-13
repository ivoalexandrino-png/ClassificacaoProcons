import { z } from "zod";

/**
 * Zod input schemas for every MCP tool.
 *
 * Each tool exposes a raw shape (consumed by `McpServer.registerTool`) and a
 * derived `z.object` used for direct parsing in handlers and tests.
 */

export const listAgentsShape = {
  include_remote: z
    .boolean()
    .default(false)
    .describe("Also include Cursor cloud agents known to the SDK (requires CURSOR_API_KEY)."),
} as const;

export const getAgentShape = {
  agent_id: z.string().min(1).describe("The bridge/Cursor agent id."),
} as const;

export const getConversationShape = {
  agent_id: z.string().min(1),
  limit: z
    .number()
    .int()
    .positive()
    .max(200)
    .default(20)
    .describe("Maximum number of recent messages to return."),
} as const;

export const sendFollowupShape = {
  agent_id: z.string().min(1),
  message: z.string().min(1).describe("The follow-up prompt for the existing agent."),
  wait_for_completion: z
    .boolean()
    .default(true)
    .describe("Wait for the run to finish and return the consolidated response."),
  allow_dangerous_actions: z
    .boolean()
    .default(false)
    .describe("Explicit human authorization to bypass the dangerous-action policy."),
} as const;

export const startAgentShape = {
  project: z.string().min(1).optional().describe("Registered project name to resolve defaults."),
  repository: z.string().min(1).optional().describe("Repository URL (required for cloud mode)."),
  working_directory: z
    .string()
    .min(1)
    .optional()
    .describe("Local working directory (required for local mode)."),
  message: z.string().min(1).describe("Initial prompt for the new agent."),
  mode: z.enum(["local", "cloud"]).default("local"),
  branch: z.string().min(1).optional(),
  model: z.string().min(1).optional(),
  allow_dangerous_actions: z.boolean().default(false),
} as const;

export const getRunShape = {
  run_id: z.string().min(1),
} as const;

export const cancelRunShape = {
  run_id: z.string().min(1),
} as const;

export const getChangesShape = {
  agent_id: z.string().min(1),
  max_diff_chars: z
    .number()
    .int()
    .positive()
    .max(500_000)
    .default(30_000)
    .describe("Upper bound on the returned diff size."),
} as const;

export const projectRegisterShape = {
  name: z.string().min(1),
  repository: z.string().min(1).optional(),
  working_directory: z.string().min(1).optional(),
  default_branch: z.string().min(1).optional(),
} as const;

export const listProjectsShape = {} as const;

export const schemas = {
  listAgents: z.object(listAgentsShape),
  getAgent: z.object(getAgentShape),
  getConversation: z.object(getConversationShape),
  sendFollowup: z.object(sendFollowupShape),
  startAgent: z.object(startAgentShape),
  getRun: z.object(getRunShape),
  cancelRun: z.object(cancelRunShape),
  getChanges: z.object(getChangesShape),
  projectRegister: z.object(projectRegisterShape),
  listProjects: z.object(listProjectsShape),
};

export type ListAgentsInput = z.infer<typeof schemas.listAgents>;
export type GetAgentInput = z.infer<typeof schemas.getAgent>;
export type GetConversationInput = z.infer<typeof schemas.getConversation>;
export type SendFollowupInput = z.infer<typeof schemas.sendFollowup>;
export type StartAgentInput = z.infer<typeof schemas.startAgent>;
export type GetRunInput = z.infer<typeof schemas.getRun>;
export type CancelRunInput = z.infer<typeof schemas.cancelRun>;
export type GetChangesInput = z.infer<typeof schemas.getChanges>;
export type ProjectRegisterInput = z.infer<typeof schemas.projectRegister>;
export type ListProjectsInput = z.infer<typeof schemas.listProjects>;
