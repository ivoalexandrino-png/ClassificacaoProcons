import path from "node:path";
import { z } from "zod";

const identifier = z.string().trim().min(1).max(200);
const message = z.string().trim().min(1).max(100_000);
const absoluteDirectory = z
  .string()
  .trim()
  .min(1)
  .max(4_096)
  .refine(path.isAbsolute, "working_directory must be an absolute path");
const repository = z.string().trim().min(1).max(2_048);

export const emptyInputSchema = z.object({}).strict();

export const getAgentSchema = z.object({
  agent_id: identifier,
});

export const getConversationSchema = z.object({
  agent_id: identifier,
  limit: z.number().int().min(1).max(200).default(20),
});

export const sendFollowupSchema = z.object({
  agent_id: identifier,
  message,
  wait_for_completion: z.boolean().default(true),
  allow_dangerous_actions: z.boolean().default(false),
});

export const startAgentSchema = z.object({
  project: identifier,
  repository,
  working_directory: absoluteDirectory,
  message,
  mode: z.enum(["local", "cloud"]).default("local"),
  allow_dangerous_actions: z.boolean().default(false),
  wait_for_completion: z.boolean().default(true),
});

export const getRunSchema = z.object({
  run_id: identifier,
});

export const cancelRunSchema = z.object({
  run_id: identifier,
});

export const getChangesSchema = z.object({
  agent_id: identifier,
  max_diff_chars: z.number().int().min(1_000).max(200_000).default(30_000),
});

export const registerProjectSchema = z.object({
  name: identifier,
  repository,
  working_directory: absoluteDirectory,
  default_branch: identifier.default("main"),
});

export type SendFollowupInput = z.infer<typeof sendFollowupSchema>;
export type StartAgentInput = z.infer<typeof startAgentSchema>;
export type RegisterProjectInput = z.infer<typeof registerProjectSchema>;
