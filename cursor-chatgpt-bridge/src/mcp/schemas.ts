import { z } from "zod";

export const agentIdSchema = z.object({
  agent_id: z.string().min(1),
});

export const listAgentsSchema = z.object({}).optional();

export const getAgentSchema = agentIdSchema;

export const getConversationSchema = z.object({
  agent_id: z.string().min(1),
  limit: z.number().int().positive().max(200).optional().default(20),
});

export const sendFollowupSchema = z.object({
  agent_id: z.string().min(1),
  message: z.string().min(1),
  wait_for_completion: z.boolean().optional().default(true),
  allow_dangerous_actions: z.boolean().optional().default(false),
});

export const startAgentSchema = z.object({
  project: z.string().optional(),
  repository: z.string().optional(),
  working_directory: z.string().optional(),
  message: z.string().min(1),
  mode: z.enum(["local", "cloud"]).optional().default("local"),
  branch: z.string().optional(),
});

export const getRunSchema = z.object({
  run_id: z.string().min(1),
});

export const cancelRunSchema = z.object({
  run_id: z.string().min(1),
});

export const getChangesSchema = z.object({
  agent_id: z.string().min(1),
  max_diff_chars: z.number().int().positive().max(100000).optional().default(30000),
});

export const registerProjectSchema = z.object({
  name: z.string().min(1),
  repository: z.string().min(1),
  working_directory: z.string().min(1),
  default_branch: z.string().min(1).default("main"),
});

export const listProjectsSchema = z.object({}).optional();
