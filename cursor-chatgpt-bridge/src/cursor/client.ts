import {
  Agent,
  AgentBusyError,
  AgentNotFoundError,
  AuthenticationError,
  ConfigurationError,
  CursorSdkError,
  IntegrationNotConnectedError,
  RateLimitError,
  UnsupportedRunOperationError,
  type Run,
  type RunResult,
  type SDKAgent,
} from "@cursor/sdk";
import { BridgeError } from "../mcp/errors.js";
import type { Logger } from "../logger.js";
import type {
  AgentCapabilities,
  AgentContext,
  CancelRunResult,
  ConversationEvent,
  CursorAgentProvider,
  ProviderGitBranch,
  ProviderRun,
  ProviderRunStatus,
  SendMessageResult,
  StartAgentParams,
  StartAgentResult,
} from "./types.js";

const RUN_STATUS_MAP: Record<string, ProviderRunStatus> = {
  running: "running",
  finished: "completed",
  error: "error",
  cancelled: "cancelled",
};

function mapGitBranches(git?: { branches: ProviderGitBranch[] }): ProviderGitBranch[] | undefined {
  return git?.branches;
}

function mapRun(agentId: string, runId: string, run: Run | RunResult): ProviderRun {
  const branches = mapGitBranches(run.git);
  return {
    runId,
    agentId,
    status: RUN_STATUS_MAP[run.status] ?? "running",
    result: run.result,
    error: run.error ? { message: run.error.message, code: run.error.code } : undefined,
    durationMs: run.durationMs,
    git: branches ? { branches } : undefined,
  };
}

/**
 * Tool call `message` shapes are internal to the SDK and explicitly marked
 * unstable in the docs, so this only reads the one field that's been stable
 * across the built-in tool union (`type`) and never dumps `args`/`result`.
 */
function summarizeToolCall(message: unknown): string {
  if (typeof message === "object" && message !== null && "type" in message) {
    return `tool_call: ${String(message.type)}`;
  }
  return "tool_call";
}

/**
 * Translates `@cursor/sdk` errors into `BridgeError`s with the codes defined
 * in the bridge's error contract. Never swallows the underlying message —
 * only reshapes it — and never invents a success.
 */
function mapSdkError(error: unknown): BridgeError {
  if (error instanceof AgentBusyError) {
    return new BridgeError("AGENT_BUSY", "Cursor agent already has an active run.");
  }
  if (error instanceof AgentNotFoundError) {
    return new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found.");
  }
  if (error instanceof AuthenticationError) {
    return new BridgeError("CURSOR_API_ERROR", `Cursor authentication failed: ${error.message}`);
  }
  if (error instanceof IntegrationNotConnectedError) {
    return new BridgeError("CURSOR_API_ERROR", error.message, {
      provider: error.provider,
      helpUrl: error.helpUrl,
    });
  }
  if (error instanceof RateLimitError) {
    return new BridgeError("CURSOR_API_ERROR", `Cursor rate limit exceeded: ${error.message}`);
  }
  if (error instanceof UnsupportedRunOperationError) {
    return new BridgeError("CURSOR_API_ERROR", error.message, { operation: error.operation });
  }
  if (error instanceof ConfigurationError) {
    return new BridgeError("CURSOR_API_ERROR", `Cursor configuration error: ${error.message}`);
  }
  if (error instanceof CursorSdkError) {
    return new BridgeError("CURSOR_API_ERROR", error.message, {
      code: error.code,
      status: error.status,
      requestId: error.requestId,
    });
  }
  const message = error instanceof Error ? error.message : String(error);
  return new BridgeError("CURSOR_API_ERROR", `Unexpected Cursor SDK error: ${message}`);
}

export interface CursorSdkAgentProviderOptions {
  apiKey: string | undefined;
  logger: Logger;
}

/**
 * Concrete `CursorAgentProvider` backed by the official `@cursor/sdk`
 * package. Keeps a small in-process cache of `SDKAgent` handles so
 * follow-ups on the same process reuse the same object; falls back to
 * `Agent.resume()` (which reloads conversation state from the persisted
 * checkpoint store) whenever a handle isn't cached — e.g. after a restart.
 */
export class CursorSdkAgentProvider implements CursorAgentProvider {
  private readonly apiKey: string | undefined;
  private readonly logger: Logger;
  private readonly handles = new Map<string, SDKAgent>();

  constructor(options: CursorSdkAgentProviderOptions) {
    this.apiKey = options.apiKey;
    this.logger = options.logger;
  }

  isConfigured(): boolean {
    return Boolean(this.apiKey);
  }

  private requireApiKey(): string {
    if (!this.apiKey) {
      throw new BridgeError(
        "CURSOR_API_ERROR",
        "CURSOR_API_KEY is not configured on the bridge server.",
      );
    }
    return this.apiKey;
  }

  private async resolveAgent(context: AgentContext): Promise<SDKAgent> {
    const cached = this.handles.get(context.agentId);
    if (cached) return cached;

    const apiKey = this.requireApiKey();
    const agent = await Agent.resume(context.agentId, {
      apiKey,
      ...(context.mode === "local" && context.workingDirectory
        ? { local: { cwd: context.workingDirectory } }
        : {}),
    });
    this.handles.set(context.agentId, agent);
    return agent;
  }

  async startAgent(params: StartAgentParams): Promise<StartAgentResult> {
    const apiKey = this.requireApiKey();
    try {
      const agent =
        params.mode === "local"
          ? await Agent.create({
              apiKey,
              local: { cwd: params.workingDirectory ?? process.cwd() },
            })
          : await Agent.create({
              apiKey,
              cloud: {
                repos: params.repository
                  ? [{ url: params.repository, startingRef: params.branch }]
                  : [],
              },
            });

      this.handles.set(agent.agentId, agent);
      const run = await agent.send(params.message);
      this.logger.info({
        event: "cursor_agent_started",
        agent_id: agent.agentId,
        run_id: run.id,
        mode: params.mode,
      });
      return { agentId: agent.agentId, run: mapRun(agent.agentId, run.id, run) };
    } catch (error) {
      throw mapSdkError(error);
    }
  }

  async sendMessage(context: AgentContext, message: string): Promise<SendMessageResult> {
    try {
      const agent = await this.resolveAgent(context);
      const run = await agent.send(message);
      return { runId: run.id, run: mapRun(context.agentId, run.id, run) };
    } catch (error) {
      throw mapSdkError(error);
    }
  }

  private runOptions(context: AgentContext) {
    const apiKey = this.requireApiKey();
    return context.mode === "cloud"
      ? ({ runtime: "cloud", agentId: context.agentId, apiKey } as const)
      : ({ runtime: "local", cwd: context.workingDirectory } as const);
  }

  async getRun(context: AgentContext, runId: string): Promise<ProviderRun> {
    try {
      const run = await Agent.getRun(runId, this.runOptions(context));
      return mapRun(context.agentId, runId, run);
    } catch (error) {
      throw mapSdkError(error);
    }
  }

  async waitForRun(
    context: AgentContext,
    runId: string,
    timeoutMs: number,
  ): Promise<{ run: ProviderRun; timedOut: boolean }> {
    try {
      const run = await Agent.getRun(runId, this.runOptions(context));

      if (!run.supports("wait")) {
        return { run: mapRun(context.agentId, runId, run), timedOut: false };
      }

      const timeout = new Promise<"timeout">((resolve) => {
        setTimeout(() => resolve("timeout"), timeoutMs);
      });
      const outcome = await Promise.race([run.wait(), timeout]);
      if (outcome === "timeout") {
        // The run itself keeps executing upstream; we only stop waiting on
        // it. Report its last-known status rather than inventing a result.
        return { run: mapRun(context.agentId, runId, run), timedOut: true };
      }
      return { run: mapRun(context.agentId, runId, outcome), timedOut: false };
    } catch (error) {
      throw mapSdkError(error);
    }
  }

  async cancelRun(context: AgentContext, runId: string): Promise<CancelRunResult> {
    const options = this.runOptions(context);

    try {
      const run = await Agent.getRun(runId, options);
      if (!run.supports("cancel")) {
        return {
          supported: false,
          reason: run.unsupportedReason("cancel") ?? "Cancel is not supported for this run.",
        };
      }
    } catch (error) {
      throw mapSdkError(error);
    }

    try {
      await Agent.cancelRun(runId, options);
    } catch (error) {
      if (error instanceof UnsupportedRunOperationError) {
        return { supported: false, reason: error.message };
      }
      throw mapSdkError(error);
    }

    try {
      const refreshed = await Agent.getRun(runId, options);
      return { supported: true, run: mapRun(context.agentId, runId, refreshed) };
    } catch {
      return { supported: true };
    }
  }

  getCapabilities(context: AgentContext): Promise<AgentCapabilities> {
    return Promise.resolve({
      mode: context.mode,
      workingDirectory: context.workingDirectory,
      repository: context.repository,
      supportsCancel: true,
      supportsStreaming: true,
    });
  }

  async getConversationEvents(context: AgentContext, runId: string): Promise<ConversationEvent[]> {
    try {
      const run = await Agent.getRun(runId, this.runOptions(context));
      if (!run.supports("conversation")) return [];

      const turns = await run.conversation();
      const events: ConversationEvent[] = [];
      for (const turn of turns) {
        if (turn.type === "agentConversationTurn") {
          for (const step of turn.turn.steps) {
            if (step.type === "assistantMessage") {
              events.push({ role: "assistant", content: step.message.text });
            } else if (step.type === "toolCall") {
              events.push({ role: "tool", content: summarizeToolCall(step.message) });
            }
            // thinkingMessage steps are intentionally skipped: internal
            // reasoning, not the kind of thing a supervisor needs to review.
          }
        } else if (turn.type === "shellConversationTurn" && turn.turn.shellCommand) {
          events.push({ role: "tool", content: `shell: ${turn.turn.shellCommand.command}` });
        }
      }
      return events;
    } catch {
      // Best-effort enrichment; never let this break the caller's flow.
      return [];
    }
  }

  /** Dispose all cached agent handles. Call on process shutdown. */
  dispose(): Promise<void> {
    for (const agent of this.handles.values()) {
      agent.close();
    }
    this.handles.clear();
    return Promise.resolve();
  }
}
