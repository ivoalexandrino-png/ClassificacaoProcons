import { vi } from "vitest";
import type {
  AgentCapabilities,
  AgentContext,
  CancelRunResult,
  ConversationEvent,
  CursorAgentProvider,
  ProviderRun,
  SendMessageResult,
  StartAgentParams,
  StartAgentResult,
} from "../../src/cursor/types.js";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface MockProviderOptions {
  /** Artificial delay (ms) before sendMessage/startAgent resolve, to make races meaningful in tests. */
  sendDelayMs?: number;
  cancelSupported?: boolean;
  /** Conversation events returned by getConversationEvents(); defaults to one tool call + one assistant message. */
  conversationEvents?: ConversationEvent[];
}

/**
 * Deterministic in-memory stand-in for `CursorAgentProvider`, used by tests
 * that exercise the bridge's own orchestration logic (locking, policy,
 * persistence, error mapping) without ever touching `@cursor/sdk` or the
 * network.
 */
export class MockCursorAgentProvider implements CursorAgentProvider {
  private counter = 0;
  private readonly runs = new Map<string, ProviderRun>();
  readonly sendMessageMock = vi.fn();

  constructor(private readonly options: MockProviderOptions = {}) {}

  isConfigured(): boolean {
    return true;
  }

  async startAgent(params: StartAgentParams): Promise<StartAgentResult> {
    await delay(this.options.sendDelayMs ?? 0);
    const agentId = `test-agent-${(this.counter += 1)}`;
    const runId = `test-run-${this.counter}`;
    const run: ProviderRun = {
      runId,
      agentId,
      status: "completed",
      result: `Started with: ${params.message}`,
    };
    this.runs.set(runId, run);
    return { agentId, run };
  }

  async sendMessage(context: AgentContext, message: string): Promise<SendMessageResult> {
    this.sendMessageMock(context, message);
    await delay(this.options.sendDelayMs ?? 0);
    const runId = `test-run-${(this.counter += 1)}`;
    const run: ProviderRun = { runId, agentId: context.agentId, status: "running" };
    this.runs.set(runId, run);
    return { runId, run };
  }

  getRun(_context: AgentContext, runId: string): Promise<ProviderRun> {
    const run = this.runs.get(runId);
    if (!run) throw new Error(`mock run not found: ${runId}`);
    return Promise.resolve(run);
  }

  async waitForRun(
    context: AgentContext,
    runId: string,
    _timeoutMs: number,
  ): Promise<{ run: ProviderRun; timedOut: boolean }> {
    await delay(this.options.sendDelayMs ?? 0);
    const completed: ProviderRun = {
      runId,
      agentId: context.agentId,
      status: "completed",
      result: "Mock result.",
    };
    this.runs.set(runId, completed);
    return { run: completed, timedOut: false };
  }

  cancelRun(context: AgentContext, runId: string): Promise<CancelRunResult> {
    if (!(this.options.cancelSupported ?? false)) {
      return Promise.resolve({
        supported: false,
        reason: "Mock provider does not support cancellation.",
      });
    }
    const run: ProviderRun = { runId, agentId: context.agentId, status: "cancelled" };
    this.runs.set(runId, run);
    return Promise.resolve({ supported: true, run });
  }

  getCapabilities(context: AgentContext): Promise<AgentCapabilities> {
    return Promise.resolve({
      mode: context.mode,
      workingDirectory: context.workingDirectory,
      repository: context.repository,
      supportsCancel: this.options.cancelSupported ?? false,
      supportsStreaming: true,
    });
  }

  getConversationEvents(_context: AgentContext, _runId: string): Promise<ConversationEvent[]> {
    return Promise.resolve(
      this.options.conversationEvents ?? [
        { role: "tool", content: "tool_call: read_file" },
        { role: "assistant", content: "Mock result." },
      ],
    );
  }

  setRun(runId: string, run: ProviderRun): void {
    this.runs.set(runId, run);
  }
}
