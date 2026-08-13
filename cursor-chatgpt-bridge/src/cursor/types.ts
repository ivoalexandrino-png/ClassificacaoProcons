export type CursorRuntimeMode = "local" | "cloud";

export interface CreateAgentParams {
  mode: CursorRuntimeMode;
  message: string;
  workingDirectory?: string;
  repository?: string;
  startingRef?: string;
  modelId?: string;
  projectName?: string;
  timeoutMs?: number;
}

export interface SendFollowUpParams {
  agentId: string;
  message: string;
  waitForCompletion: boolean;
  timeoutMs: number;
}

export interface ProviderAgentInfo {
  agentId: string;
  name?: string;
  summary?: string;
  status?: string;
  mode?: CursorRuntimeMode;
  workingDirectory?: string;
  repositories?: string[];
  branch?: string;
  lastActivityAt?: string;
  createdAt?: string;
  metadata?: Record<string, unknown>;
  capabilities?: string[];
}

export interface ProviderRunResult {
  runId: string;
  agentId: string;
  status: "running" | "completed" | "error" | "cancelled" | "timeout";
  response?: string;
  error?: string;
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  git?: {
    branches?: Array<{ repoUrl: string; branch?: string; prUrl?: string }>;
  };
}

export interface ProviderConversationMessage {
  role: "user" | "assistant" | "tool" | "system" | "event";
  content: string;
  createdAt?: string;
  metadata?: Record<string, unknown>;
}

export interface CursorAgentProvider {
  isConfigured(): boolean;
  createAgent(params: CreateAgentParams): Promise<{
    agentId: string;
    run: ProviderRunResult;
  }>;
  resumeAndSend(params: SendFollowUpParams): Promise<ProviderRunResult>;
  getAgent(agentId: string): Promise<ProviderAgentInfo | null>;
  listAgents(): Promise<ProviderAgentInfo[]>;
  getRun(runId: string, agentId?: string): Promise<ProviderRunResult | null>;
  cancelRun(
    runId: string,
    agentId?: string,
  ): Promise<{ supported: true } | { supported: false; reason: string }>;
  listConversation(
    agentId: string,
    limit?: number,
  ): Promise<ProviderConversationMessage[]>;
}
