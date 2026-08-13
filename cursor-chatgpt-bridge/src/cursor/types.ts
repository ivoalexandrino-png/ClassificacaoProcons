export type AgentMode = "local" | "cloud";
export type RunStatus = "running" | "completed" | "error" | "cancelled" | "timeout";
export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface Project {
  id: number;
  name: string;
  repository: string;
  workingDirectory: string;
  defaultBranch: string;
  createdAt: string;
  updatedAt: string;
}

export interface AgentRecord {
  agentId: string;
  projectId: number;
  mode: AgentMode;
  branch: string | null;
  status: RunStatus | "idle";
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
}

export interface MessageRecord {
  id: number;
  agentId: string;
  runId: string | null;
  role: MessageRole;
  content: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface ProviderAgent {
  agentId: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

export interface ProviderRun {
  runId: string;
  agentId: string;
  status: RunStatus;
  response?: string;
  error?: string;
  startedAt?: string;
  completedAt?: string;
}

export interface CursorAgentProvider {
  createAgent(input: {
    mode: AgentMode;
    repository: string;
    workingDirectory: string;
    defaultBranch: string;
  }): Promise<ProviderAgent>;
  resumeAgent(agentId: string, workingDirectory: string): Promise<void>;
  sendMessage(agentId: string, workingDirectory: string, message: string): Promise<ProviderRun>;
  waitForRun(runId: string, agentId: string, mode: AgentMode, workingDirectory: string): Promise<ProviderRun>;
  getAgent(agentId: string, workingDirectory: string): Promise<ProviderAgent>;
  getRun(runId: string, agentId: string, mode: AgentMode, workingDirectory: string): Promise<ProviderRun>;
  cancelRun(runId: string, agentId: string, mode: AgentMode, workingDirectory: string): Promise<void>;
  getConversation(agentId: string, workingDirectory: string, limit: number): Promise<MessageRecord[]>;
}
