import type { BridgeConfig } from "../src/config.js";
import type {
  CreateAgentOptions,
  CursorAgentProvider,
  ProviderAgentInfo,
  ProviderRunHandle,
  ProviderRunResult,
  ProviderRunSnapshot,
} from "../src/cursor/types.js";
import { BridgeError } from "../src/errors.js";
import { nullLogger } from "../src/logger.js";
import { BridgeTools } from "../src/mcp/tools.js";
import { BridgeStore } from "../src/storage/store.js";

export class Deferred<T> {
  promise: Promise<T>;
  resolve!: (value: T) => void;
  reject!: (err: unknown) => void;

  constructor() {
    this.promise = new Promise<T>((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
  }
}

/**
 * In-memory fake of the Cursor SDK provider. Runs stay pending until
 * `completeRun` is called, unless `autoRespond` is set.
 */
export class FakeProvider implements CursorAgentProvider {
  configured = true;
  autoRespond: string | null = null;
  readonly agents = new Map<string, ProviderAgentInfo>();
  readonly pending = new Map<string, Deferred<ProviderRunResult>>();
  readonly snapshots = new Map<string, ProviderRunSnapshot>();
  readonly followups: Array<{ agentId: string; message: string }> = [];
  private counter = 0;

  seedAgent(agentId: string, info: Partial<ProviderAgentInfo> = {}): void {
    this.agents.set(agentId, {
      agentId,
      runtime: agentId.startsWith("bc-") ? "cloud" : "local",
      status: "finished",
      ...info,
    });
  }

  private newRun(agentId: string): ProviderRunHandle {
    const runId = `run-fake-${++this.counter}`;
    const deferred = new Deferred<ProviderRunResult>();
    this.pending.set(runId, deferred);
    if (this.autoRespond !== null) {
      deferred.resolve({ runId, status: "completed", response: this.autoRespond });
    }
    return { runId, agentId, wait: () => deferred.promise };
  }

  completeRun(runId: string, result: Partial<ProviderRunResult> = {}): void {
    const deferred = this.pending.get(runId);
    if (!deferred) throw new Error(`no pending run ${runId}`);
    deferred.resolve({ runId, status: "completed", response: "done", ...result });
  }

  async createAgent(
    options: CreateAgentOptions,
  ): Promise<{ agent: ProviderAgentInfo; run: ProviderRunHandle }> {
    const agentId =
      options.mode === "cloud" ? `bc-fake-${++this.counter}` : `agent-fake-${++this.counter}`;
    this.seedAgent(agentId, {
      runtime: options.mode,
      status: "running",
      repos: options.repository ? [options.repository] : undefined,
    });
    return { agent: this.agents.get(agentId)!, run: this.newRun(agentId) };
  }

  async sendFollowup(agentId: string, message: string): Promise<ProviderRunHandle> {
    if (!this.agents.has(agentId)) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", { agent_id: agentId });
    }
    this.followups.push({ agentId, message });
    return this.newRun(agentId);
  }

  async listAgents(): Promise<ProviderAgentInfo[]> {
    return [...this.agents.values()];
  }

  async getAgent(agentId: string): Promise<ProviderAgentInfo> {
    const info = this.agents.get(agentId);
    if (!info) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", { agent_id: agentId });
    }
    return info;
  }

  async getRun(agentId: string, runId: string): Promise<ProviderRunSnapshot> {
    const snapshot = this.snapshots.get(runId);
    if (snapshot) return snapshot;
    return { runId, agentId, status: "running" };
  }

  async cancelRun(_agentId: string, runId: string): Promise<{ supported: boolean; reason?: string }> {
    const deferred = this.pending.get(runId);
    if (deferred) deferred.resolve({ runId, status: "cancelled" });
    return { supported: true };
  }
}

export function makeConfig(overrides: Partial<BridgeConfig> = {}): BridgeConfig {
  return {
    port: 0,
    bridgeToken: "test-token",
    cursorApiKey: "test-api-key",
    databasePath: ":memory:",
    runTimeoutMs: 5_000,
    logLevel: "error",
    maxDiffChars: 30_000,
    ...overrides,
  };
}

export function makeTools(overrides: Partial<BridgeConfig> = {}): {
  tools: BridgeTools;
  store: BridgeStore;
  provider: FakeProvider;
} {
  const store = new BridgeStore(":memory:");
  const provider = new FakeProvider();
  const tools = new BridgeTools({
    store,
    provider,
    config: makeConfig(overrides),
    logger: nullLogger,
  });
  return { tools, store, provider };
}
