/**
 * Provider abstraction over the official Cursor SDK (`@cursor/sdk`).
 * The MCP tools depend only on this interface, so future SDK changes stay
 * isolated in `client.ts` and tests can use an in-memory fake.
 */

export type ProviderRuntime = "local" | "cloud";

export type ProviderRunStatus = "running" | "completed" | "error" | "cancelled";

export interface ProviderAgentInfo {
  agentId: string;
  name?: string;
  status?: string;
  runtime: ProviderRuntime;
  repos?: string[];
  createdAt?: number;
  lastModified?: number;
  archived?: boolean;
}

export interface ProviderGitInfo {
  branches: Array<{ repoUrl: string; branch?: string; prUrl?: string }>;
}

export interface ProviderRunResult {
  runId: string;
  status: Exclude<ProviderRunStatus, "running">;
  response?: string;
  errorMessage?: string;
  git?: ProviderGitInfo;
  durationMs?: number;
}

/** Handle for an in-flight run returned by create/send operations. */
export interface ProviderRunHandle {
  runId: string;
  agentId: string;
  wait(): Promise<ProviderRunResult>;
}

/** Point-in-time snapshot of a run fetched by ID. */
export interface ProviderRunSnapshot {
  runId: string;
  agentId: string;
  status: ProviderRunStatus;
  response?: string;
  errorMessage?: string;
  git?: ProviderGitInfo;
}

export interface CreateAgentOptions {
  message: string;
  mode: ProviderRuntime;
  /** GitHub repository URL — required for cloud agents. */
  repository?: string;
  /** Starting branch/ref for cloud agents. */
  branch?: string;
  /** Local working directory — required for local agents. */
  workingDirectory?: string;
}

export interface SendFollowupOptions {
  /** Working directory hint used when resuming local agents. */
  workingDirectory?: string;
}

export interface CursorAgentProvider {
  /** Whether a Cursor API key is available. */
  readonly configured: boolean;

  createAgent(
    options: CreateAgentOptions,
  ): Promise<{ agent: ProviderAgentInfo; run: ProviderRunHandle }>;

  /** Resume an existing agent (context preserved by Cursor) and send a follow-up. */
  sendFollowup(
    agentId: string,
    message: string,
    options?: SendFollowupOptions,
  ): Promise<ProviderRunHandle>;

  listAgents(limit?: number): Promise<ProviderAgentInfo[]>;

  getAgent(agentId: string): Promise<ProviderAgentInfo>;

  getRun(agentId: string, runId: string): Promise<ProviderRunSnapshot>;

  /** Cancel a run. Resolves with supported=false when the runtime cannot cancel. */
  cancelRun(agentId: string, runId: string): Promise<{ supported: boolean; reason?: string }>;
}
