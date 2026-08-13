export type AgentMode = "local" | "cloud";

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "error"
  | "cancelled"
  | "timeout"
  | "busy"
  | "blocked_by_policy";

export type MessageRole = "user" | "assistant" | "tool" | "system" | "event";

export interface ProjectRecord {
  id: string;
  name: string;
  repository: string;
  workingDirectory: string;
  defaultBranch: string;
  createdAt: string;
  updatedAt: string;
}

export interface AgentRecord {
  agentId: string;
  projectId: string | null;
  mode: AgentMode;
  branch: string | null;
  status: string;
  workingDirectory: string | null;
  repository: string | null;
  createdAt: string;
  lastActivityAt: string;
  metadata: Record<string, unknown>;
}

export interface RunRecord {
  runId: string;
  agentId: string;
  status: RunStatus;
  prompt: string;
  response: string | null;
  startedAt: string;
  completedAt: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
}

export interface MessageRecord {
  id: string;
  agentId: string;
  runId: string | null;
  role: MessageRole;
  content: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface CreateProjectInput {
  name: string;
  repository: string;
  workingDirectory: string;
  defaultBranch?: string;
}

export interface UpsertAgentInput {
  agentId: string;
  projectId?: string | null;
  mode: AgentMode;
  branch?: string | null;
  status?: string;
  workingDirectory?: string | null;
  repository?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateRunInput {
  runId: string;
  agentId: string;
  status: RunStatus;
  prompt: string;
  metadata?: Record<string, unknown>;
}

export interface CreateMessageInput {
  agentId: string;
  runId?: string | null;
  role: MessageRole;
  content: string;
  metadata?: Record<string, unknown>;
}
