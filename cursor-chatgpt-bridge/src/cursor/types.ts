/**
 * Provider-agnostic types for driving a Cursor Agent.
 *
 * `CursorAgentProvider` is the seam between the MCP tools/bridge logic and
 * whatever the current Cursor SDK exposes. If the official SDK's method
 * names or shapes change, only `cursor/client.ts` (the concrete
 * `CursorSdkAgentProvider`) needs to change — nothing above this interface
 * should need to know about `@cursor/sdk` directly.
 */

export type ProviderAgentMode = "local" | "cloud";

export type ProviderRunStatus = "creating" | "running" | "completed" | "error" | "cancelled";

export interface ProviderRunError {
  message: string;
  code?: string;
}

export interface ProviderGitBranch {
  repoUrl: string;
  branch?: string;
  prUrl?: string;
}

export interface ProviderRun {
  runId: string;
  agentId: string;
  status: ProviderRunStatus;
  result?: string;
  error?: ProviderRunError;
  durationMs?: number;
  git?: { branches: ProviderGitBranch[] };
}

/**
 * Everything the provider needs to locate/resume an agent. Cursor's SDK
 * scopes local agents by working directory and cloud agents by agent ID
 * alone, so the bridge always carries both and lets the provider pick what
 * it needs.
 */
export interface AgentContext {
  agentId: string;
  mode: ProviderAgentMode;
  workingDirectory?: string;
  repository?: string;
  branch?: string;
}

export interface StartAgentParams {
  mode: ProviderAgentMode;
  message: string;
  /** Required for local mode: the working directory the agent operates on. */
  workingDirectory?: string;
  /** Required for cloud mode: the repository URL to clone into the VM. */
  repository?: string;
  /** Branch/ref to start from. Cloud only (local uses the checkout's current branch). */
  branch?: string;
}

export interface StartAgentResult {
  agentId: string;
  run: ProviderRun;
}

export interface SendMessageResult {
  runId: string;
  run: ProviderRun;
}

export interface CancelRunResult {
  supported: boolean;
  reason?: string;
  run?: ProviderRun;
}

/**
 * A single step from a finished run's structured transcript (assistant text
 * or a tool invocation), used to populate `cursor_get_conversation` with
 * more than just the final result. Deliberately coarse: tool call
 * argument/result shapes are internal to the SDK and can change, so only a
 * short, defensive summary is kept — never a raw dump of tool args/results
 * (which could include large payloads or secrets passed to MCP/shell tools).
 */
export interface ConversationEvent {
  role: "assistant" | "tool" | "system";
  content: string;
}

export interface AgentCapabilities {
  mode: ProviderAgentMode;
  workingDirectory?: string;
  repository?: string;
  supportsCancel: boolean;
  supportsStreaming: boolean;
}

/**
 * Thin abstraction over the Cursor Agent runtime (SDK today; REST API or a
 * future SDK major version tomorrow). Every method maps 1:1 to an operation
 * an MCP tool needs, not to a specific SDK call, so the mapping can change
 * without touching the tools.
 */
export interface CursorAgentProvider {
  /** True when the provider has enough configuration (API key) to operate. */
  isConfigured(): boolean;

  startAgent(params: StartAgentParams): Promise<StartAgentResult>;

  /** Send a follow-up prompt to an existing agent, without waiting for completion. */
  sendMessage(context: AgentContext, message: string): Promise<SendMessageResult>;

  /** Poll the current state of a run (does not wait). */
  getRun(context: AgentContext, runId: string): Promise<ProviderRun>;

  /** Wait for a run to reach a terminal state, or until `timeoutMs` elapses. */
  waitForRun(
    context: AgentContext,
    runId: string,
    timeoutMs: number,
  ): Promise<{ run: ProviderRun; timedOut: boolean }>;

  /** Cancel an active run. Never simulated: reports `supported: false` when the runtime can't. */
  cancelRun(context: AgentContext, runId: string): Promise<CancelRunResult>;

  getCapabilities(context: AgentContext): Promise<AgentCapabilities>;

  /**
   * Best-effort structured transcript (assistant text + tool calls) for a
   * finished run. Returns `[]` when the runtime doesn't support it rather
   * than throwing — this is a "nice to have" enrichment of the conversation
   * log, not a required step in any tool's control flow.
   */
  getConversationEvents(context: AgentContext, runId: string): Promise<ConversationEvent[]>;
}
