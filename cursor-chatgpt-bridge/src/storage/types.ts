export type AgentMode = "local" | "cloud";

/**
 * Mirrors the Cursor Cloud Agents API run states plus two bridge-local
 * states: "queued" (created but not yet acknowledged by the provider) and
 * "timeout" (the bridge stopped waiting; the run may still be active upstream).
 */
export type RunStatus =
  | "queued"
  | "creating"
  | "running"
  | "completed"
  | "error"
  | "cancelled"
  | "timeout";

export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface ProjectRow {
  id: string;
  name: string;
  repository: string | null;
  working_directory: string | null;
  default_branch: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRow {
  agent_id: string;
  project_id: string | null;
  mode: AgentMode;
  branch: string | null;
  repository: string | null;
  working_directory: string | null;
  status: RunStatus;
  active_run_id: string | null;
  created_at: string;
  last_activity_at: string;
  metadata: string | null;
}

export interface RunRow {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  prompt: string;
  response: string | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface MessageRow {
  id: number;
  agent_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  metadata: string | null;
}

export interface CreateProjectInput {
  name: string;
  repository?: string | undefined;
  workingDirectory?: string | undefined;
  defaultBranch?: string | undefined;
}

export interface CreateAgentInput {
  agentId: string;
  projectId?: string | undefined;
  mode: AgentMode;
  branch?: string | undefined;
  repository?: string | undefined;
  workingDirectory?: string | undefined;
  status: RunStatus;
  metadata?: Record<string, unknown> | undefined;
}

export interface CreateRunInput {
  runId: string;
  agentId: string;
  status: RunStatus;
  prompt: string;
}

export interface UpdateRunInput {
  status?: RunStatus;
  response?: string | null;
  completedAt?: string | null;
  error?: string | null;
}

export interface CreateMessageInput {
  agentId: string;
  runId?: string | undefined;
  role: MessageRole;
  content: string;
  metadata?: Record<string, unknown> | undefined;
}
