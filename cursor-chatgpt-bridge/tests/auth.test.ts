import type { Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { createApp } from "../src/server.js";
import { extractBearerToken, safeTokenCompare } from "../src/security/auth.js";
import { nullLogger } from "../src/logger.js";
import { makeConfig, makeTools } from "./helpers.js";

const TOKEN = "super-secret-token";

let server: Server;
let baseUrl: string;

beforeAll(async () => {
  const { tools, store } = makeTools();
  const app = createApp({
    config: makeConfig({ bridgeToken: TOKEN }),
    tools,
    store,
    logger: nullLogger,
    bridgeToken: TOKEN,
  });
  await new Promise<void>((resolve) => {
    server = app.listen(0, () => resolve());
  });
  const address = server.address() as AddressInfo;
  baseUrl = `http://127.0.0.1:${address.port}`;
});

afterAll(async () => {
  await new Promise<void>((resolve, reject) =>
    server.close((err) => (err ? reject(err) : resolve())),
  );
});

function mcpRequest(headers: Record<string, string> = {}): Promise<Response> {
  return fetch(`${baseUrl}/mcp`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      ...headers,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "test-client", version: "0.0.1" },
      },
    }),
  });
}

describe("auth primitives", () => {
  it("should compare tokens in constant time semantics", () => {
    expect(safeTokenCompare("abc", "abc")).toBe(true);
    expect(safeTokenCompare("abc", "abd")).toBe(false);
    expect(safeTokenCompare("short", "a-much-longer-token")).toBe(false);
  });

  it("should extract bearer tokens case-insensitively", () => {
    expect(extractBearerToken("Bearer tok")).toBe("tok");
    expect(extractBearerToken("bearer tok")).toBe("tok");
    expect(extractBearerToken("Basic tok")).toBeUndefined();
    expect(extractBearerToken(undefined)).toBeUndefined();
  });
});

describe("HTTP auth", () => {
  it("should serve /health without authentication", async () => {
    const res = await fetch(`${baseUrl}/health`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.status).toBe("ok");
    expect(body.service).toBe("cursor-chatgpt-bridge");
    expect(body.database).toBe("ok");
  });

  it("should reject an MCP request without a token", async () => {
    const res = await mcpRequest();
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: { code: string } };
    expect(body.error.code).toBe("UNAUTHORIZED");
  });

  it("should reject an MCP request with a wrong token", async () => {
    const res = await mcpRequest({ authorization: "Bearer wrong-token" });
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: { code: string } };
    expect(body.error.code).toBe("UNAUTHORIZED");
  });

  it("should accept an MCP initialize request with the correct token", async () => {
    const res = await mcpRequest({ authorization: `Bearer ${TOKEN}` });
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      result: { serverInfo: { name: string } };
    };
    expect(body.result.serverInfo.name).toBe("cursor-chatgpt-bridge");
  });

  it("should reject GET /mcp (stateless mode) but only after auth", async () => {
    const unauthorized = await fetch(`${baseUrl}/mcp`);
    expect(unauthorized.status).toBe(401);
    const authorized = await fetch(`${baseUrl}/mcp`, {
      headers: { authorization: `Bearer ${TOKEN}` },
    });
    expect(authorized.status).toBe(405);
  });
});
