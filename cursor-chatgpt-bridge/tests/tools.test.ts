import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";
import { AgentService } from "../src/cursor/agents.js";
import { CursorSdkProvider } from "../src/cursor/client.js";
import { RunService } from "../src/cursor/runs.js";
import { BridgeError } from "../src/errors.js";
import { createLogger } from "../src/logger.js";
import {
  getAgentSchema,
  registerProjectSchema,
  sendFollowupSchema,
} from "../src/mcp/schemas.js";
import { BridgeStore } from "../src/storage/store.js";

class MockCursorProvider implements Pick<
  CursorSdkProvider,
  "resumeAgent" | "sendMessage" | "cancelRun" | "waitForRunCompletion" | "createAgent"
> {
  sendMessage = async (input: {
    agentId: string;
    message: string;
    waitForCompletion?: boolean;
  }) => ({
    run_id: "run-sdk-1",
    agent_id: input.agentId,
    status: input.waitForCompletion ? "completed" : "running",
    response: input.waitForCompletion ? "done" : undefined,
    started_at: new Date().toISOString(),
    completed_at: input.waitForCompletion ? new Date().toISOString() : undefined,
    error: null,
  });

  resumeAgent = async () => undefined;
  cancelRun = async () => ({ supported: true, run_id: "run-sdk-1", status: "cancelled" });
  waitForRunCompletion = async (agentId: string, runId: string) => ({
    run_id: runId,
    agent_id: agentId,
    status: "completed" as const,
    response: "done",
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    error: null,
  });
  createAgent = async () => ({ agentId: "agent-new", runId: "run-new" });
}

describe("schemas", () => {
  it("should validate send followup schema", () => {
    const parsed = sendFollowupSchema.parse({
      agent_id: "agent-1",
      message: "continue",
      wait_for_completion: true,
    });
    expect(parsed.agent_id).toBe("agent-1");
    expect(parsed.allow_dangerous_actions).toBe(false);
  });

  it("should validate register project schema", () => {
    const parsed = registerProjectSchema.parse({
      name: "sunday",
      repository: "https://github.com/org/sunday",
      working_directory: "/tmp/sunday",
      default_branch: "main",
    });
    expect(parsed.name).toBe("sunday");
  });
});

describe("run service concurrency", () => {
  let dbPath: string;
  let store: BridgeStore;
  let runService: RunService;
  const mockCursor = new MockCursorProvider();

  beforeEach(() => {
    const dir = mkdtempSync(join(tmpdir(), "bridge-tools-"));
    dbPath = join(dir, "test.db");
    store = new BridgeStore(dbPath);
    const config = loadConfig({
      CURSOR_BRIDGE_TOKEN: "test",
      DATABASE_PATH: dbPath,
    });
    const logger = createLogger(config);
    runService = new RunService(store, mockCursor as CursorSdkProvider, logger, 1000);

    store.upsertAgent({
      agent_id: "agent-1",
      mode: "local",
      status: "idle",
      working_directory: "/tmp",
    });
  });

  afterEach(() => {
    store.close();
    rmSync(join(dbPath, ".."), { recursive: true, force: true });
  });

  it("should reject second execution while agent is busy", async () => {
    runService.isAgentBusy("agent-1");
    (runService as unknown as { locks: Set<string> }).locks.add("agent-1");

    const result = await runService.sendFollowup({
      agent_id: "agent-1",
      message: "second prompt",
      wait_for_completion: true,
    });

    expect(result.status).toBe("busy");
  });

  it("should return agent not found error for missing agent", async () => {
    await expect(
      runService.sendFollowup({
        agent_id: "missing",
        message: "hello",
      }),
    ).rejects.toMatchObject({ code: "AGENT_NOT_FOUND" });
  });
});

describe("agent and project errors", () => {
  let store: BridgeStore;
  let dbPath: string;

  beforeEach(() => {
    const dir = mkdtempSync(join(tmpdir(), "bridge-agent-"));
    dbPath = join(dir, "test.db");
    store = new BridgeStore(dbPath);
  });

  afterEach(() => {
    store.close();
    rmSync(join(dbPath, ".."), { recursive: true, force: true });
  });

  it("should return undefined for missing agent details", () => {
    const agentService = new AgentService(store);
    expect(agentService.getAgentDetails("missing")).toBeUndefined();
  });

  it("should validate get agent schema", () => {
    expect(getAgentSchema.parse({ agent_id: "abc" }).agent_id).toBe("abc");
  });

  it("should throw project not found via BridgeError code", () => {
    const error = new BridgeError("PROJECT_NOT_FOUND", "Project not found", {
      project: "missing",
    });
    expect(error.code).toBe("PROJECT_NOT_FOUND");
  });
});
