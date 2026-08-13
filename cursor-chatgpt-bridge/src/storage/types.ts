/** Persisted domain rows and the storage interface used across the bridge. */

export type AgentMode = "local" | "cloud";

export type RunStatus = "running" | "completed" | "error" | "cancelled" | "timeout";

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
  status: string | null;
  working_directory: string | null;
  repository: string | null;
  created_at: string;
  last_activity_at: string;
  metadata: Record<string, unknown>;
}

export interface RunRow {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  prompt: string | null;
  response: string | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface MessageRow {
  id: string;
  agent_id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface CreateProjectInput {
  name: string;
  repository?: string | null;
  workingDirectory?: string | null;
  defaultBranch?: string | null;
}

export interface UpsertAgentInput {
  agentId: string;
  projectId?: string | null;
  mode: AgentMode;
  branch?: string | null;
  status?: string | null;
  workingDirectory?: string | null;
  repository?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateRunInput {
  runId: string;
  agentId: string;
  status: RunStatus;
  prompt?: string | null;
  startedAt?: string;
}

export interface UpdateRunInput {
  status?: RunStatus;
  response?: string | null;
  completedAt?: string | null;
  error?: string | null;
}

export interface CreateMessageInput {
  agentId: string;
  runId?: string | null;
  role: MessageRole;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface Store {
  // Projects
  createProject(input: CreateProjectInput): ProjectRow;
  listProjects(): ProjectRow[];
  getProject(id: string): ProjectRow | null;
  findProjectByName(name: string): ProjectRow | null;
  findProjectByRepository(repository: string): ProjectRow | null;

  // Agents
  upsertAgent(input: UpsertAgentInput): AgentRow;
  listAgents(): AgentRow[];
  getAgent(agentId: string): AgentRow | null;
  touchAgent(agentId: string, status?: string | null): void;

  // Runs
  createRun(input: CreateRunInput): RunRow;
  updateRun(runId: string, patch: UpdateRunInput): RunRow | null;
  getRun(runId: string): RunRow | null;
  listRunsByAgent(agentId: string, limit?: number): RunRow[];
  getActiveRunForAgent(agentId: string): RunRow | null;

  // Messages
  createMessage(input: CreateMessageInput): MessageRow;
  listMessagesByAgent(agentId: string, limit?: number): MessageRow[];

  // Lifecycle
  healthcheck(): boolean;
  close(): void;
}
