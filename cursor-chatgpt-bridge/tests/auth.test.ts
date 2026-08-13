import type { AddressInfo } from "node:net";
import type { Server } from "node:http";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type {
  AgentRuntimeContext,
  CreateAgentRequest,
  CursorAgentProvider,
  ProviderAgent,
  ProviderRun,
} from "../src/cursor/types.js";
import { Logger } from "../src/logger.js";
import { BridgeTools } from "../src/mcp/tools.js";
import { createHttpServer } from "../src/server.js";
import { BridgeStore } from "../src/storage/store.js";

class UnusedProvider implements CursorAgentProvider {
  isConfigured(): boolean {
    return true;
  }

  createAgent(_request: CreateAgentRequest): Promise<ProviderAgent> {
    return Promise.reject(new Error("not used"));
  }

  sendMessage(
    _agentId: string,
    _message: string,
    _context: AgentRuntimeContext,
  ): Promise<ProviderRun> {
    return Promise.reject(new Error("not used"));
  }

  getRun(
    _agentId: string,
    _runId: string,
    _context: AgentRuntimeContext,
  ): Promise<ProviderRun> {
    return Promise.reject(new Error("not used"));
  }

  cancelRun(
    _agentId: string,
    _runId: string,
    _context: AgentRuntimeContext,
  ): Promise<{ supported: boolean }> {
    return Promise.resolve({ supported: false });
  }
}

describe("HTTP authentication", () => {
  const token = "a".repeat(64);
  let server: Server;
  let store: BridgeStore;
  let endpoint: string;

  beforeEach(async () => {
    store = new BridgeStore(":memory:");
    const provider = new UnusedProvider();
    const logger = new Logger("error");
    server = createHttpServer({
      host: "127.0.0.1",
      port: 0,
      bridgeToken: token,
      store,
      provider,
      tools: new BridgeTools(store, provider, 1_000, 30_000, logger),
      logger,
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address() as AddressInfo;
    endpoint = `http://127.0.0.1:${address.port}`;
  });

  afterEach(async () => {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
    store.close();
  });

  it("should expose an unauthenticated health check without secrets", async () => {
    const response = await fetch(`${endpoint}/health`);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      status: "ok",
      service: "cursor-chatgpt-bridge",
      cursor_sdk_configured: true,
      database: "ok",
    });
  });

  it.each([
    ["missing", undefined],
    ["incorrect", "Bearer wrong-token"],
  ])("should reject %s bearer token", async (_case, authorization) => {
    const response = await fetch(`${endpoint}/mcp`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(authorization ? { authorization } : {}),
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
    });

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "UNAUTHORIZED" },
    });
  });

  it("should accept a correct bearer token and serve MCP", async () => {
    const response = await fetch(`${endpoint}/mcp`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2025-11-25",
          capabilities: {},
          clientInfo: { name: "bridge-test", version: "1.0.0" },
        },
      }),
    });

    expect(response.status).toBe(200);
    const body = await response.text();
    const dataLine = body
      .split("\n")
      .find((line) => line.startsWith("data: "));
    expect(dataLine).toBeDefined();
    expect(JSON.parse(dataLine!.slice(6))).toMatchObject({
      result: {
        serverInfo: { name: "cursor-chatgpt-bridge" },
      },
    });
  });
});
