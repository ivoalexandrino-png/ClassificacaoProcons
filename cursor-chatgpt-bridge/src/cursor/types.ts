export type AgentMode = "local" | "cloud";

export type BridgeRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "finished"
  | "error"
  | "cancelled"
  | "timeout"
  | "blocked_by_policy"
  | "busy";

export interface CreateAgentInput {
  mode: AgentMode;
  message: string;
  workingDirectory?: string;
  repository?: string;
  branch?: string;
  model?: string;
}

export interface SendMessageInput {
  agentId: string;
  message: string;
  mode?: AgentMode;
  workingDirectory?: string;
  model?: string;
  timeoutMs: number;
  waitForCompletion?: boolean;
}

export interface AgentSummary {
  agent_id: string;
  project?: string;
  repository?: string;
  branch?: string;
  status: string;
  last_activity_at: string;
  mode: AgentMode;
  working_directory?: string;
}

export interface AgentDetails extends AgentSummary {
  active_run_id?: string;
  metadata?: Record<string, unknown>;
  capabilities: {
    cancel_run: boolean;
    get_changes: boolean;
    conversation_history: boolean;
  };
}

export interface RunDetails {
  run_id: string;
  agent_id: string;
  status: BridgeRunStatus;
  response?: string;
  started_at: string;
  completed_at?: string;
  error?: string | null;
}

export interface CancelRunResult {
  supported: boolean;
  reason?: string;
  run_id?: string;
  status?: string;
}

export interface CursorAgentProvider {
  listAgentsFromCursor(options?: {
    mode?: AgentMode;
    workingDirectory?: string;
  }): Promise<AgentSummary[]>;

  createAgent(input: CreateAgentInput): Promise<{ agentId: string; runId: string }>;

  resumeAgent(agentId: string, options?: { workingDirectory?: string }): Promise<void>;

  sendMessage(input: SendMessageInput): Promise<RunDetails>;

  getRun(agentId: string, runId: string, options?: { workingDirectory?: string }): Promise<RunDetails>;

  cancelRun(
    agentId: string,
    runId: string,
    options?: { workingDirectory?: string },
  ): Promise<CancelRunResult>;

  waitForRunCompletion(
    agentId: string,
    runId: string,
    options?: { workingDirectory?: string; timeoutMs?: number },
  ): Promise<RunDetails>;

  getAgentFromCursor(
    agentId: string,
    options?: { workingDirectory?: string },
  ): Promise<AgentSummary | undefined>;
}
