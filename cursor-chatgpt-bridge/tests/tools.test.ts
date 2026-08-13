import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Config } from "../src/config.js";
import { AgentLockManager } from "../src/cursor/agents.js";
import type {
  CancelResult,
  CancelRunParams,
  CursorAgentProvider,
  GetRunParams,
  ProviderAgentInfo,
  ProviderRun,
  ProviderStartResult,
  SendFollowupParams,
  StartAgentParams,
} from "../src/cursor/types.js";
import { BridgeError } from "../src/errors.js";
import { createLogger } from "../src/logger.js";
import { createToolHandlers, type ToolContext } from "../src/mcp/tools.js";
import { SqliteStore } from "../src/storage/store.js";

const ISO = new Date().toISOString();

/** In-memory fake of the Cursor SDK provider for deterministic tool tests. */
class FakeProvider implements CursorAgentProvider {
  configured = true;
  sendCalls = 0;
  private startCounter = 0;
  private gate: Promise<void> | null = null;
  private openGateFn: (() => void) | null = null;

  useGate(): void {
    this.gate = new Promise<void>((resolve) => {
      this.openGateFn = resolve;
    });
  }

  openGate(): void {
    this.openGateFn?.();
  }

  async startAgent(params: StartAgentParams): Promise<ProviderStartResult> {
    this.startCounter += 1;
    const agentId = params.mode === "cloud" ? `bc-fake-${this.startCounter}` : `agent-fake-${this.startCounter}`;
    return {
      agentId,
      mode: params.mode,
      model: params.model ?? "auto",
      run: {
        runId: `run-start-${this.startCounter}`,
        agentId,
        status: "completed",
        response: "started ok",
        startedAt: ISO,
        completedAt: ISO,
      },
    };
  }

  async sendFollowup(params: SendFollowupParams): Promise<ProviderRun> {
    this.sendCalls += 1;
    if (this.gate) await this.gate;
    return {
      runId: `run-follow-${this.sendCalls}`,
      agentId: params.agentId,
      status: "completed",
      response: "follow-up done",
      startedAt: ISO,
      completedAt: ISO,
    };
  }

  async getRun(params: GetRunParams): Promise<ProviderRun> {
    return {
      runId: params.runId,
      agentId: params.agentId,
      status: "completed",
      response: "final",
      startedAt: ISO,
      completedAt: ISO,
    };
  }

  async cancelRun(_params: CancelRunParams): Promise<CancelResult> {
    return { supported: true, cancelled: true };
  }

  async listCloudAgents(): Promise<ProviderAgentInfo[]> {
    return [{ agentId: "bc-remote-1", mode: "cloud", status: "running" }];
  }

  async getAgentInfo(agentId: string, mode: "local" | "cloud"): Promise<ProviderAgentInfo | null> {
    return { agentId, mode, status: "running" };
  }
}

function makeConfig(): Config {
  return {
    port: 0,
    host: "127.0.0.1",
    bridgeToken: "test-token",
    cursorApiKey: "test-key",
    databasePath: ":memory:",
    cursorLocalStorePath: "./data/test-store",
    cursorModel: "auto",
    runTimeoutMs: 60_000,
    logLevel: "error",
    transport: "http",
  };
}

describe("tool handlers", () => {
  let store: SqliteStore;
  let provider: FakeProvider;
  let handlers: ReturnType<typeof createToolHandlers>;

  beforeEach(() => {
    store = new SqliteStore(":memory:");
    provider = new FakeProvider();
    const ctx: ToolContext = {
      store,
      provider,
      locks: new AgentLockManager(),
      config: makeConfig(),
      logger: createLogger("error"),
    };
    handlers = createToolHandlers(ctx);
  });

  afterEach(() => {
    store.close();
  });

  it("should register and list projects", async () => {
    await handlers.cursor_project_register({
      name: "sunday",
      repository: "https://github.com/acme/sunday",
      working_directory: "/repos/sunday",
      default_branch: "main",
    });
    const listed = (await handlers.cursor_list_projects({})) as { projects: unknown[] };
    expect(listed.projects).toHaveLength(1);
  });

  it("should start a local agent and expose it via get_agent", async () => {
    await handlers.cursor_project_register({ name: "sunday", working_directory: "/repos/sunday" });
    const started = (await handlers.cursor_start_agent({
      project: "sunday",
      message: "set up the project",
      mode: "local",
    })) as { agent_id: string; status: string; run_id: string };

    expect(started.agent_id).toBe("agent-fake-1");
    expect(started.status).toBe("completed");

    const agent = (await handlers.cursor_get_agent({ agent_id: started.agent_id })) as {
      agent_id: string;
      capabilities: Record<string, boolean>;
      mode: string;
    };
    expect(agent.mode).toBe("local");
    expect(agent.capabilities.get_changes).toBe(true);
    expect(agent.capabilities.send_followup).toBe(true);
  });

  it("should return PROJECT_NOT_FOUND for an unknown project", async () => {
    await expect(
      handlers.cursor_start_agent({ project: "ghost", message: "hi", mode: "local" }),
    ).rejects.toMatchObject({ code: "PROJECT_NOT_FOUND" });
  });

  it("should return AGENT_NOT_FOUND for an unknown agent", async () => {
    await expect(handlers.cursor_get_agent({ agent_id: "nope" })).rejects.toMatchObject({
      code: "AGENT_NOT_FOUND",
    });
  });

  it("should return RUN_NOT_FOUND for an unknown run", async () => {
    await expect(handlers.cursor_get_run({ run_id: "nope" })).rejects.toBeInstanceOf(BridgeError);
  });

  it("should reject invalid tool input (schema validation)", async () => {
    await expect(handlers.cursor_get_agent({})).rejects.toBeTruthy();
    await expect(handlers.cursor_send_followup({ agent_id: "a" })).rejects.toBeTruthy();
  });

  it("should send a follow-up and record the conversation", async () => {
    store.upsertAgent({ agentId: "agent-fake-1", mode: "local", workingDirectory: "/repos/sunday" });

    const result = (await handlers.cursor_send_followup({
      agent_id: "agent-fake-1",
      message: "add a test",
    })) as { status: string; response: string; run_id: string };

    expect(result.status).toBe("completed");
    expect(result.response).toBe("follow-up done");

    const conversation = (await handlers.cursor_get_conversation({ agent_id: "agent-fake-1" })) as {
      messages: { role: string; content: string }[];
    };
    expect(conversation.messages).toHaveLength(2);
    expect(conversation.messages[0]?.role).toBe("user");
    expect(conversation.messages[1]?.role).toBe("assistant");
  });

  it("should block a dangerous follow-up without explicit authorization", async () => {
    store.upsertAgent({ agentId: "agent-fake-1", mode: "local", workingDirectory: "/repos/sunday" });
    const result = (await handlers.cursor_send_followup({
      agent_id: "agent-fake-1",
      message: "please deploy to production and drop database old_data",
    })) as { status: string; requires_explicit_authorization: boolean };

    expect(result.status).toBe("blocked_by_policy");
    expect(result.requires_explicit_authorization).toBe(true);
    expect(provider.sendCalls).toBe(0);
  });

  it("should allow a dangerous follow-up with explicit authorization", async () => {
    store.upsertAgent({ agentId: "agent-fake-1", mode: "local", workingDirectory: "/repos/sunday" });
    const result = (await handlers.cursor_send_followup({
      agent_id: "agent-fake-1",
      message: "deploy to production",
      allow_dangerous_actions: true,
    })) as { status: string };
    expect(result.status).toBe("completed");
    expect(provider.sendCalls).toBe(1);
  });

  it("should return busy for a concurrent follow-up on the same agent", async () => {
    store.upsertAgent({ agentId: "agent-fake-1", mode: "local", workingDirectory: "/repos/sunday" });
    provider.useGate();

    const first = handlers.cursor_send_followup({ agent_id: "agent-fake-1", message: "one" });
    const second = handlers.cursor_send_followup({ agent_id: "agent-fake-1", message: "two" });

    // Release the first (gated) run so it can complete.
    provider.openGate();
    const [r1, r2] = (await Promise.all([first, second])) as [
      { status: string },
      { status: string; active_run_id: string | null },
    ];

    expect(r1.status).toBe("completed");
    expect(r2.status).toBe("busy");
    expect(r2.active_run_id).toBeTruthy();
    expect(provider.sendCalls).toBe(1);
  });

  it("should report cancel as unsupported when the SDK is not configured", async () => {
    store.upsertAgent({ agentId: "agent-fake-1", mode: "local" });
    store.createRun({ runId: "run-1", agentId: "agent-fake-1", status: "running" });
    provider.configured = false;

    const result = (await handlers.cursor_cancel_run({ run_id: "run-1" })) as {
      supported: boolean;
      cancelled: boolean;
      reason: string;
    };
    expect(result.supported).toBe(false);
    expect(result.cancelled).toBe(false);
    expect(result.reason).toBeTruthy();
  });

  it("should cancel a run when supported", async () => {
    store.upsertAgent({ agentId: "agent-fake-1", mode: "local" });
    store.createRun({ runId: "run-1", agentId: "agent-fake-1", status: "running" });

    const result = (await handlers.cursor_cancel_run({ run_id: "run-1" })) as {
      supported: boolean;
      cancelled: boolean;
      status: string;
    };
    expect(result.supported).toBe(true);
    expect(result.cancelled).toBe(true);
    expect(store.getRun("run-1")?.status).toBe("cancelled");
  });
});
