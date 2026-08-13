import { afterEach, describe, expect, it } from "vitest";
import type {
  AgentRuntimeContext,
  CreateAgentRequest,
  CursorAgentProvider,
  ProviderAgent,
  ProviderRun,
  ProviderRunResult,
} from "../src/cursor/types.js";
import { BridgeError } from "../src/errors.js";
import {
  getConversationSchema,
  sendFollowupSchema,
  startAgentSchema,
} from "../src/mcp/schemas.js";
import { BridgeTools } from "../src/mcp/tools.js";
import { BridgeStore } from "../src/storage/store.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

class MockProvider implements CursorAgentProvider {
  sendCount = 0;
  private runNumber = 0;
  nextResult = deferred<ProviderRunResult>();
  runs = new Map<string, ProviderRun>();

  isConfigured(): boolean {
    return true;
  }

  createAgent(_request: CreateAgentRequest): Promise<ProviderAgent> {
    return Promise.resolve({
      agentId: "agent-created",
      mode: "local",
      capabilities: {
        followup: true,
        conversation: true,
        cancel: true,
        localChanges: true,
      },
      metadata: {},
    });
  }

  sendMessage(
    agentId: string,
    _message: string,
    _context: AgentRuntimeContext,
  ): Promise<ProviderRun> {
    this.sendCount += 1;
    this.runNumber += 1;
    const runId = `run-${this.runNumber}`;
    const run: ProviderRun = {
      runId,
      agentId,
      status: "running",
      supportsCancel: true,
      wait: () => this.nextResult.promise,
      cancel: () => Promise.resolve(),
    };
    this.runs.set(runId, run);
    return Promise.resolve(run);
  }

  getRun(
    _agentId: string,
    runId: string,
    _context: AgentRuntimeContext,
  ): Promise<ProviderRun> {
    const run = this.runs.get(runId);
    if (!run) return Promise.reject(new Error("missing mock run"));
    return Promise.resolve(run);
  }

  cancelRun(
    _agentId: string,
    _runId: string,
    _context: AgentRuntimeContext,
  ): Promise<{ supported: boolean }> {
    return Promise.resolve({ supported: true });
  }
}

describe("BridgeTools", () => {
  let store: BridgeStore | undefined;

  afterEach(() => store?.close());

  function setup() {
    store = new BridgeStore(":memory:");
    const provider = new MockProvider();
    const tools = new BridgeTools(store, provider, 5_000, 30_000);
    const project = store.registerProject({
      name: "sunday",
      repository: "https://github.com/example/sunday",
      workingDirectory: "/tmp",
      defaultBranch: "main",
    });
    const agent = store.createAgent({
      agentId: "agent-1",
      projectId: project.id,
      mode: "local",
    });
    return { tools, provider, project, agent };
  }

  it("should return structured agent and project responses", () => {
    const { tools } = setup();

    expect(tools.listProjects()).toMatchObject({
      projects: [{ name: "sunday" }],
    });
    expect(tools.getAgent("agent-1")).toMatchObject({
      agent: {
        agent_id: "agent-1",
        project: "sunday",
        capabilities: { followup: true, cancel_run: true },
      },
    });
  });

  it("should persist a completed follow-up and conversation", async () => {
    const { tools, provider } = setup();
    const pending = tools.sendFollowup({
      agent_id: "agent-1",
      message: "Add tests",
      wait_for_completion: true,
      allow_dangerous_actions: false,
    });
    provider.nextResult.resolve({
      runId: "run-1",
      status: "completed",
      response: "Tests added",
      error: null,
      messages: [{ role: "tool", content: "pytest passed" }],
      metadata: { duration_ms: 50 },
    });

    await expect(pending).resolves.toMatchObject({
      run_id: "run-1",
      agent_id: "agent-1",
      status: "completed",
      response: "Tests added",
    });
    expect(tools.getConversation("agent-1", 20)).toMatchObject({
      messages: [
        { role: "user", content: "Add tests" },
        { role: "tool", content: "pytest passed" },
        { role: "assistant", content: "Tests added" },
      ],
    });
  });

  it("should reject a second execution while the same agent is busy", async () => {
    const { tools, provider } = setup();
    await tools.sendFollowup({
      agent_id: "agent-1",
      message: "First task",
      wait_for_completion: false,
      allow_dangerous_actions: false,
    });

    await expect(
      tools.sendFollowup({
        agent_id: "agent-1",
        message: "Second task",
        wait_for_completion: false,
        allow_dangerous_actions: false,
      }),
    ).rejects.toMatchObject({
      code: "AGENT_BUSY",
      details: { active_run_id: "run-1" },
    });
    expect(provider.sendCount).toBe(1);
    provider.nextResult.resolve({
      runId: "run-1",
      status: "completed",
      response: "Done",
      error: null,
      messages: [],
      metadata: {},
    });
    await new Promise((resolve) => setImmediate(resolve));
  });

  it("should return a policy block without sending the prompt", async () => {
    const { tools, provider } = setup();

    await expect(
      tools.sendFollowup({
        agent_id: "agent-1",
        message: "git reset --hard",
        wait_for_completion: true,
        allow_dangerous_actions: false,
      }),
    ).resolves.toMatchObject({
      status: "blocked_by_policy",
      requires_explicit_authorization: true,
    });
    expect(provider.sendCount).toBe(0);
  });

  it("should report missing agents and projects with stable codes", async () => {
    const { tools } = setup();

    expect(() => tools.getAgent("missing")).toThrowError(
      expect.objectContaining<Partial<BridgeError>>({ code: "AGENT_NOT_FOUND" }),
    );
    await expect(
      tools.startAgent({
        project: "missing",
        repository: "repo",
        working_directory: "/tmp",
        message: "Inspect",
        mode: "local",
        wait_for_completion: false,
        allow_dangerous_actions: false,
      }),
    ).rejects.toMatchObject({ code: "PROJECT_NOT_FOUND" });
  });
});

describe("MCP input schemas", () => {
  it("should apply safe defaults to valid inputs", () => {
    expect(
      sendFollowupSchema.parse({ agent_id: "agent-1", message: "Continue" }),
    ).toMatchObject({
      wait_for_completion: true,
      allow_dangerous_actions: false,
    });
    expect(getConversationSchema.parse({ agent_id: "agent-1" }).limit).toBe(20);
  });

  it("should reject invalid and relative-path inputs", () => {
    expect(() => sendFollowupSchema.parse({ agent_id: "", message: "" })).toThrow();
    expect(() =>
      startAgentSchema.parse({
        project: "sunday",
        repository: "repo",
        working_directory: "./relative",
        message: "Inspect",
      }),
    ).toThrow();
  });
});
