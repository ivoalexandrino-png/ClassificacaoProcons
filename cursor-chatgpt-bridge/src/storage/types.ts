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
  project_id: string | null;
  mode: "local" | "cloud";
  branch: string | null;
  status: string;
  working_directory: string | null;
  repository: string | null;
  created_at: string;
  last_activity_at: string;
  metadata: string | null;
}

export interface RunRecord {
  run_id: string;
  agent_id: string;
  status: string;
  prompt: string;
  response: string | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface MessageRecord {
  id: string;
  agent_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  metadata: string | null;
}

export interface ConversationMessage {
  id: string;
  agent_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}
