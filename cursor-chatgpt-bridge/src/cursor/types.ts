import type { AgentMode, RunStatus } from "../storage/types.js";

/**
 * Runtime-agnostic view of the Cursor SDK, so the MCP tools never depend on the
 * concrete `@cursor/sdk` package directly. Swap the implementation to isolate
 * future SDK changes or to inject a fake in tests.
 */

export interface StartAgentParams {
  mode: AgentMode;
  message: string;
  model?: string;
  /** Local runtime working directory. */
  workingDirectory?: string;
  /** Cloud runtime repository URL. */
  repository?: string;
  /** Cloud runtime starting ref/branch. */
  branch?: string;
  timeoutMs: number;
  /** When false, return as soon as the run is enqueued. */
  waitForCompletion: boolean;
}

export interface SendFollowupParams {
  agentId: string;
  mode: AgentMode;
  message: string;
  model?: string;
  workingDirectory?: string;
  timeoutMs: number;
  waitForCompletion: boolean;
}

export interface GetRunParams {
  runId: string;
  agentId: string;
  mode: AgentMode;
  workingDirectory?: string;
}

export interface CancelRunParams {
  runId: string;
  agentId: string;
  mode: AgentMode;
  workingDirectory?: string;
}

export interface ConversationStep {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
}

export interface ProviderRun {
  runId: string;
  agentId: string;
  status: RunStatus;
  response?: string;
  error?: string;
  startedAt?: string;
  completedAt?: string;
  /** Git branches / PRs produced by a cloud run, when available. */
  git?: { repoUrl: string; branch?: string; prUrl?: string }[];
}

export interface ProviderStartResult {
  agentId: string;
  mode: AgentMode;
  model?: string;
  run: ProviderRun;
}

export interface ProviderAgentInfo {
  agentId: string;
  name?: string;
  summary?: string;
  status?: string;
  mode: AgentMode;
  repository?: string;
  branch?: string;
  lastActivityAt?: string;
}

export interface CancelResult {
  supported: boolean;
  cancelled: boolean;
  reason?: string;
}

export interface CursorAgentProvider {
  readonly configured: boolean;

  startAgent(params: StartAgentParams): Promise<ProviderStartResult>;
  sendFollowup(params: SendFollowupParams): Promise<ProviderRun>;
  getRun(params: GetRunParams): Promise<ProviderRun>;
  cancelRun(params: CancelRunParams): Promise<CancelResult>;

  /** Cloud agent listing from the SDK; local agents are tracked by the bridge store. */
  listCloudAgents(): Promise<ProviderAgentInfo[]>;
  getAgentInfo(agentId: string, mode: AgentMode): Promise<ProviderAgentInfo | null>;
}
