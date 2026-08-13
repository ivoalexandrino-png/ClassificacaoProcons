import { randomUUID } from "node:crypto";
import type { AddressInfo } from "node:net";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import express from "express";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AgentService } from "../src/cursor/agents.js";
import { RunService } from "../src/cursor/runs.js";
import { createLogger } from "../src/logger.js";
import { extractBearerToken, isAuthorized, createAuthMiddleware } from "../src/security/auth.js";
import { buildMcpServer } from "../src/server.js";
import { BridgeStore } from "../src/storage/store.js";
import { MockCursorAgentProvider } from "./helpers/mockProvider.js";

interface Harness {
  store: BridgeStore;
  provider: MockCursorAgentProvider;
  agents: AgentService;
  runs: RunService;
  server: McpServer;
  client: Client;
}

async function buildHarness(providerOptions?: ConstructorParameters<typeof MockCursorAgentProvider>[0]): Promise<Harness> {
  const store = new BridgeStore(":memory:");
  const provider = new MockCursorAgentProvider(providerOptions);
  const logger = createLogger("error");
  const agents = new AgentService(store, provider);
  const runs = new RunService(store, provider, agents, logger, 5000);
  const server = buildMcpServer({ agents, runs, logger });

  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const client = new Client({ name: "test-client", version: "0.0.0" });
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);

  return { store, provider, agents, runs, server, client };
}

describe("MCP tools", () => {
  let harness: Harness;

  beforeEach(async () => {
    harness = await buildHarness();
  });

  afterEach(async () => {
    await harness.client.close();
    harness.store.close();
  });

  it("should expose every cursor_* tool with a JSON-schema input", async () => {
    const { tools } = await harness.client.listTools();
    const names = tools.map((tool) => tool.name).sort();

    expect(names).toEqual(
      [
        "cursor_cancel_run",
        "cursor_get_agent",
        "cursor_get_changes",
        "cursor_get_conversation",
        "cursor_get_run",
        "cursor_list_agents",
        "cursor_list_projects",
        "cursor_project_register",
        "cursor_send_followup",
        "cursor_start_agent",
      ].sort(),
    );
    for (const tool of tools) {
      expect(tool.inputSchema).toBeDefined();
      expect(tool.inputSchema.type).toBe("object");
    }
  });

  it("should register a project and list it back", async () => {
    const register = await harness.client.callTool({
      name: "cursor_project_register",
      arguments: { name: "sunday", repository: "https://github.com/acme/sunday", default_branch: "main" },
    });
    expect(register.isError).toBeFalsy();
    expect(register.structuredContent).toMatchObject({ name: "sunday", default_branch: "main" });

    const list = await harness.client.callTool({ name: "cursor_list_projects", arguments: {} });
    expect(list.structuredContent).toMatchObject({
      projects: [expect.objectContaining({ name: "sunday" })],
    });
  });

  it("should start a cloud agent tied to a registered project and record the conversation", async () => {
    await harness.client.callTool({
      name: "cursor_project_register",
      arguments: { name: "sunday", repository: "https://github.com/acme/sunday" },
    });

    const start = await harness.client.callTool({
      name: "cursor_start_agent",
      arguments: { project: "sunday", message: "Investigate the failing test.", mode: "cloud" },
    });
    expect(start.isError).toBeFalsy();
    const agentId = (start.structuredContent as { agent_id: string }).agent_id;
    expect(agentId).toBeTruthy();

    const listAgents = await harness.client.callTool({ name: "cursor_list_agents", arguments: {} });
    expect(listAgents.structuredContent).toMatchObject({
      agents: [expect.objectContaining({ agent_id: agentId, project: "sunday" })],
    });

    const conversation = await harness.client.callTool({
      name: "cursor_get_conversation",
      arguments: { agent_id: agentId },
    });
    const messages = (conversation.structuredContent as { messages: Array<{ role: string }> }).messages;
    expect(messages.map((message) => message.role)).toContain("user");
  });

  it("should send a follow-up and wait for completion", async () => {
    const start = await harness.client.callTool({
      name: "cursor_start_agent",
      arguments: { repository: "https://github.com/acme/sunday", message: "Start.", mode: "cloud" },
    });
    const agentId = (start.structuredContent as { agent_id: string }).agent_id;

    const followup = await harness.client.callTool({
      name: "cursor_send_followup",
      arguments: { agent_id: agentId, message: "Continue please.", wait_for_completion: true },
    });

    expect(followup.isError).toBeFalsy();
    expect(followup.structuredContent).toMatchObject({
      agent_id: agentId,
      status: "completed",
      response: "Mock result.",
    });

    const runId = (followup.structuredContent as { run_id: string }).run_id;
    const getRun = await harness.client.callTool({ name: "cursor_get_run", arguments: { run_id: runId } });
    expect(getRun.structuredContent).toMatchObject({ run_id: runId, status: "completed" });
  });

  it("should report cancellation as unsupported rather than pretending to cancel", async () => {
    const start = await harness.client.callTool({
      name: "cursor_start_agent",
      arguments: { repository: "https://github.com/acme/sunday", message: "Start.", mode: "cloud" },
    });
    const agentId = (start.structuredContent as { agent_id: string }).agent_id;
    const followup = await harness.client.callTool({
      name: "cursor_send_followup",
      arguments: { agent_id: agentId, message: "Keep going.", wait_for_completion: false },
    });
    const runId = (followup.structuredContent as { run_id: string }).run_id;

    const cancel = await harness.client.callTool({ name: "cursor_cancel_run", arguments: { run_id: runId } });
    expect(cancel.structuredContent).toMatchObject({ supported: false });
  });

  it("should block a follow-up that matches the dangerous-action policy", async () => {
    const start = await harness.client.callTool({
      name: "cursor_start_agent",
      arguments: { repository: "https://github.com/acme/sunday", message: "Start.", mode: "cloud" },
    });
    const agentId = (start.structuredContent as { agent_id: string }).agent_id;

    const followup = await harness.client.callTool({
      name: "cursor_send_followup",
      arguments: { agent_id: agentId, message: "Faça terraform destroy no ambiente." },
    });

    expect(followup.structuredContent).toMatchObject({
      status: "blocked_by_policy",
      requires_explicit_authorization: true,
    });
  });

  it("should return AGENT_NOT_FOUND for an agent the bridge has never seen", async () => {
    const result = await harness.client.callTool({
      name: "cursor_get_agent",
      arguments: { agent_id: "does-not-exist" },
    });
    expect(result.isError).toBe(true);
    expect(result.structuredContent).toMatchObject({ error: { code: "AGENT_NOT_FOUND" } });
  });

  it("should return PROJECT_NOT_FOUND when starting an agent against an unregistered project", async () => {
    const result = await harness.client.callTool({
      name: "cursor_start_agent",
      arguments: { project: "does-not-exist", message: "hi", mode: "cloud" },
    });
    expect(result.isError).toBe(true);
    expect(result.structuredContent).toMatchObject({ error: { code: "PROJECT_NOT_FOUND" } });
  });

  it("should reject a tool call whose input violates its schema", async () => {
    const result = await harness.client.callTool({
      name: "cursor_send_followup",
      arguments: { agent_id: "x" },
    });
    expect(result.isError).toBe(true);
    const text = (result.content as Array<{ type: string; text?: string }>)[0]?.text ?? "";
    expect(text).toMatch(/message/i);
  });
});

describe("Concurrency: cursor_send_followup locking", () => {
  it("should reject a second follow-up for the same agent while the first is still active", async () => {
    const harness = await buildHarness({ sendDelayMs: 30 });
    const start = await harness.client.callTool({
      name: "cursor_start_agent",
      arguments: { repository: "https://github.com/acme/sunday", message: "Start.", mode: "cloud" },
    });
    const agentId = (start.structuredContent as { agent_id: string }).agent_id;

    const [first, second] = await Promise.all([
      harness.client.callTool({
        name: "cursor_send_followup",
        arguments: { agent_id: agentId, message: "First.", wait_for_completion: true },
      }),
      harness.client.callTool({
        name: "cursor_send_followup",
        arguments: { agent_id: agentId, message: "Second.", wait_for_completion: true },
      }),
    ]);

    const statuses = [first.structuredContent, second.structuredContent].map(
      (content) => (content as { status: string }).status,
    );
    expect(statuses).toContain("busy");
    expect(statuses).toContain("completed");

    await harness.client.close();
    harness.store.close();
  });
});

describe("Security: bearer token auth", () => {
  const token = "s3cr3t-bridge-token";
  let server: import("node:http").Server;
  let baseUrl: string;

  beforeEach(async () => {
    const app = express();
    app.get("/protected", createAuthMiddleware(token), (_req, res) => {
      res.json({ ok: true });
    });
    server = app.listen(0);
    await new Promise<void>((resolve) => server.once("listening", resolve));
    const { port } = server.address() as AddressInfo;
    baseUrl = `http://127.0.0.1:${port}`;
  });

  afterEach(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it("should reject a request with no Authorization header", async () => {
    const response = await fetch(`${baseUrl}/protected`);
    expect(response.status).toBe(401);
    const body = (await response.json()) as { error: { code: string } };
    expect(body.error.code).toBe("UNAUTHORIZED");
  });

  it("should reject a request with an incorrect bearer token", async () => {
    const response = await fetch(`${baseUrl}/protected`, {
      headers: { Authorization: `Bearer ${randomUUID()}` },
    });
    expect(response.status).toBe(401);
  });

  it("should accept a request with the correct bearer token", async () => {
    const response = await fetch(`${baseUrl}/protected`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
  });

  it("should extract and compare bearer tokens with the helper functions directly", () => {
    expect(extractBearerToken(undefined)).toBeUndefined();
    expect(extractBearerToken(`Bearer ${token}`)).toBe(token);
    expect(isAuthorized(`Bearer ${token}`, token)).toBe(true);
    expect(isAuthorized(`Bearer wrong`, token)).toBe(false);
    expect(isAuthorized(undefined, token)).toBe(false);
  });
});
