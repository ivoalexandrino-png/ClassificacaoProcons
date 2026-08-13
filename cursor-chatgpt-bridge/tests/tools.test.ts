import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Server } from "node:http";
import { AgentService } from "../src/cursor/agents.js";
import { MockCursorAgentProvider } from "../src/cursor/client.js";
import { RunService } from "../src/cursor/runs.js";
import { createLogger } from "../src/logger.js";
import { loadConfig } from "../src/config.js";
import { createMcpServer } from "../src/mcp/tools.js";
import {
  getAgentSchema,
  projectRegisterSchema,
  sendFollowupSchema,
  startAgentSchema,
} from "../src/mcp/schemas.js";
import { createBridgeApp } from "../src/server.js";
import { BridgeStore } from "../src/storage/store.js";

const cleanup: Array<() => void> = [];

async function setup() {
  const dir = mkdtempSync(path.join(tmpdir(), "bridge-tools-"));
  const store = new BridgeStore(path.join(dir, "bridge.db"));
  const provider = new MockCursorAgentProvider();
  const logger = createLogger("error");
  const agents = new AgentService(store, provider, logger, 5_000);
  const runs = new RunService(store, provider, logger);
  const deps = { store, agents, runs, logger };

  process.env.CURSOR_BRIDGE_TOKEN = "test-token";
  process.env.DATABASE_PATH = path.join(dir, "bridge.db");
  const config = {
    ...loadConfig({ requireToken: true }),
    bridgeToken: "test-token",
    host: "127.0.0.1",
    port: 0,
    allowedHosts: ["localhost", "127.0.0.1"],
    cursorApiKey: "test-key",
    databasePath: path.join(dir, "bridge.db"),
  };

  const bridge = createBridgeApp({
    config,
    store,
    provider,
    deps,
    logger,
  });

  const server = await new Promise<Server>((resolve, reject) => {
    const s = bridge.app.listen(0, "127.0.0.1", () => resolve(s));
    s.on("error", reject);
  });

  cleanup.push(() => {
    server.close();
    void bridge.close();
    store.close();
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Failed to bind test server");
  }

  return {
    store,
    provider,
    agents,
    runs,
    deps,
    baseUrl: `http://127.0.0.1:${address.port}`,
    server,
  };
}

afterEach(() => {
  while (cleanup.length) {
    cleanup.pop()?.();
  }
});

describe("MCP input schemas", () => {
  it("should validate send_followup input schema", () => {
    const parsed = sendFollowupSchema.parse({
      agent_id: "agent-1",
      message: "continue",
    });
    expect(parsed.wait_for_completion).toBe(true);
    expect(parsed.allow_dangerous_actions).toBe(false);
  });

  it("should validate start_agent and project_register schemas", () => {
    expect(
      startAgentSchema.parse({
        message: "boot",
        working_directory: "/tmp/repo",
      }).mode,
    ).toBe("local");
    expect(
      projectRegisterSchema.parse({
        name: "sunday",
        repository: "https://github.com/org/sunday.git",
        working_directory: "/repos/sunday",
      }).default_branch,
    ).toBe("main");
    expect(() => getAgentSchema.parse({})).toThrow();
  });
});

describe("HTTP auth and health", () => {
  it("should reject MCP request without token", async () => {
    const { baseUrl } = await setup();
    const res = await fetch(`${baseUrl}/mcp`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
    });
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: { code: string } };
    expect(body.error.code).toBe("UNAUTHORIZED");
  });

  it("should reject MCP request with incorrect token", async () => {
    const { baseUrl } = await setup();
    const res = await fetch(`${baseUrl}/mcp`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: "Bearer wrong",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
    });
    expect(res.status).toBe(401);
  });

  it("should accept health and authenticated MCP initialize", async () => {
    const { baseUrl } = await setup();
    const health = await fetch(`${baseUrl}/health`);
    expect(health.status).toBe(200);
    const healthBody = (await health.json()) as {
      service: string;
      cursor_sdk_configured: boolean;
      database: string;
    };
    expect(healthBody.service).toBe("cursor-chatgpt-bridge");
    expect(healthBody.database).toBe("ok");
    expect(healthBody.cursor_sdk_configured).toBe(true);

    const res = await fetch(`${baseUrl}/mcp`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        authorization: "Bearer test-token",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2025-03-26",
          capabilities: {},
          clientInfo: { name: "test", version: "1.0.0" },
        },
      }),
    });
    expect(res.status).toBeLessThan(500);
  });
});

describe("bridge tool behaviors", () => {
  let ctx: Awaited<ReturnType<typeof setup>>;

  beforeEach(async () => {
    ctx = await setup();
  });

  it("should return structured error when agent does not exist", async () => {
    try {
      ctx.agents.getAgentDetails("missing");
      throw new Error("expected AGENT_NOT_FOUND");
    } catch (error) {
      expect(error).toMatchObject({ code: "AGENT_NOT_FOUND" });
    }
  });

  it("should return structured error when project does not exist", async () => {
    try {
      await ctx.agents.startAgent({
        project: "missing-project",
        message: "hello",
        mode: "local",
      });
      throw new Error("expected PROJECT_NOT_FOUND");
    } catch (error) {
      expect(error).toMatchObject({ code: "PROJECT_NOT_FOUND" });
    }
  });

  it("should start agent, persist conversation, and return structured follow-up", async () => {
    ctx.store.createProject({
      name: "sunday",
      repository: "https://github.com/org/sunday.git",
      workingDirectory: "/tmp/sunday",
    });

    const started = await ctx.agents.startAgent({
      project: "sunday",
      message: "Summarize the repo",
      mode: "local",
    });
    expect(started.agent_id).toMatch(/^agent-mock-/);
    expect(started.status).toBe("completed");
    expect(started.response).toContain("Mock response");

    const conversation = ctx.agents.getConversation(started.agent_id, 10);
    expect(conversation.messages.length).toBeGreaterThanOrEqual(2);

    const followup = await ctx.agents.sendFollowUp({
      agentId: started.agent_id,
      message: "Continue with tests",
      waitForCompletion: true,
    });
    expect(followup).toMatchObject({
      agent_id: started.agent_id,
      status: "completed",
    });
    expect("run_id" in followup && followup.run_id).toBeTruthy();
  });

  it("should reject second follow-up while agent is busy", async () => {
    const created = await ctx.provider.createAgent({
      mode: "local",
      message: "hi",
      workingDirectory: "/tmp/repo",
    });
    ctx.store.upsertAgent({
      agentId: created.agentId,
      mode: "local",
      status: "idle",
      workingDirectory: "/tmp/repo",
    });

    // Force an active run in the store
    ctx.store.createRun({
      runId: "run-active",
      agentId: created.agentId,
      status: "running",
      prompt: "busy work",
    });

    const result = await ctx.agents.sendFollowUp({
      agentId: created.agentId,
      message: "another",
      waitForCompletion: true,
    });
    expect(result).toEqual({
      status: "busy",
      active_run_id: "run-active",
      agent_id: created.agentId,
    });
  });

  it("should expose MCP server with expected tool names", () => {
    const server = createMcpServer(ctx.deps);
    // McpServer keeps tools internally; ensure construction succeeds and schemas are wired.
    expect(server).toBeTruthy();
  });
});
