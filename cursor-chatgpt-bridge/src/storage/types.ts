export type AgentMode = "local" | "cloud";
export type RunStatus =
  | "running"
  | "completed"
  | "error"
  | "cancelled"
  | "timeout";
export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface ProjectRecord {
  id: string;
  name: string;
  repository: string;
  working_directory: string;
  default_branch: string;
  created_at: string;
  updated_at: string;
}

export interface AgentRecord {
  agent_id: string;
  project_id: string;
  mode: AgentMode;
  branch: string | null;
  status: string;
  created_at: string;
  last_activity_at: string;
  metadata: Record<string, unknown>;
}

export interface RunRecord {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  prompt: string;
  response: string | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
}

export interface MessageRecord {
  id: string;
  agent_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}
