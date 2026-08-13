import { z } from "zod";

export const agentIdSchema = z.object({ agent_id: z.string().min(1) });
export const runIdSchema = z.object({ run_id: z.string().min(1) });
export const conversationSchema = agentIdSchema.extend({ limit: z.number().int().min(1).max(100).default(20) });
export const followupSchema = agentIdSchema.extend({
  message: z.string().min(1).max(100_000),
  wait_for_completion: z.boolean().default(true),
  allow_dangerous_actions: z.boolean().default(false)
});
export const startAgentSchema = z.object({
  project: z.string().min(1),
  repository: z.string().min(1).optional(),
  working_directory: z.string().min(1).optional(),
  message: z.string().min(1).max(100_000),
  mode: z.enum(["local", "cloud"]).default("local")
});
export const changesSchema = agentIdSchema.extend({
  max_diff_chars: z.number().int().min(1_000).max(100_000).default(30_000)
});
export const projectSchema = z.object({
  name: z.string().min(1),
  repository: z.string().min(1),
  working_directory: z.string().min(1),
  default_branch: z.string().min(1).default("main")
});
