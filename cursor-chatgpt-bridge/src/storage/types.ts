export interface ProjectRecord {
  id: string;
  name: string;
  repository: string | null;
  working_directory: string | null;
  default_branch: string | null;
  created_at: string;
  updated_at: string;
}

export type AgentMode = "local" | "cloud";

export type AgentStatus = "running" | "idle" | "finished" | "error" | "unknown";

export interface AgentRecord {
  agent_id: string;
  project_id: string | null;
  mode: AgentMode;
  branch: string | null;
  status: string;
  created_at: string;
  last_activity_at: string;
  metadata: Record<string, unknown>;
}

export type RunStatus =
  | "running"
  | "completed"
  | "error"
  | "cancelled"
  | "timeout";

export interface RunRecord {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  prompt: string;
  response: string | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface MessageRecord {
  id: number;
  agent_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}
