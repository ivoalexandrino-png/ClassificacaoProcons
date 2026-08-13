import { z } from "zod";

export const listAgentsSchema = z.object({}).strict();

export const getAgentSchema = z
  .object({
    agent_id: z.string().min(1),
  })
  .strict();

export const getConversationSchema = z
  .object({
    agent_id: z.string().min(1),
    limit: z.number().int().min(1).max(200).optional().default(20),
  })
  .strict();

export const sendFollowupSchema = z
  .object({
    agent_id: z.string().min(1),
    message: z.string().min(1),
    wait_for_completion: z.boolean().optional().default(true),
    allow_dangerous_actions: z.boolean().optional().default(false),
  })
  .strict();

export const startAgentSchema = z
  .object({
    project: z.string().min(1).optional(),
    repository: z.string().min(1).optional(),
    working_directory: z.string().min(1).optional(),
    message: z.string().min(1),
    mode: z.enum(["local", "cloud"]).optional().default("local"),
  })
  .strict();

export const getRunSchema = z
  .object({
    run_id: z.string().min(1),
  })
  .strict();

export const cancelRunSchema = z
  .object({
    run_id: z.string().min(1),
  })
  .strict();

export const getChangesSchema = z
  .object({
    agent_id: z.string().min(1),
    max_diff_chars: z.number().int().min(1000).max(200000).optional().default(30000),
  })
  .strict();

export const projectRegisterSchema = z
  .object({
    name: z.string().min(1),
    repository: z.string().min(1),
    working_directory: z.string().min(1),
    default_branch: z.string().min(1).optional().default("main"),
  })
  .strict();

export const listProjectsSchema = z.object({}).strict();
