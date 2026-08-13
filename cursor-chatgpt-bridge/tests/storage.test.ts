import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { BridgeStore } from "../src/storage/store.js";

const stores: BridgeStore[] = [];

function createStore(): BridgeStore {
  const dir = mkdtempSync(path.join(tmpdir(), "bridge-store-"));
  const store = new BridgeStore(path.join(dir, "test.db"));
  stores.push(store);
  return store;
}

afterEach(() => {
  while (stores.length) {
    stores.pop()?.close();
  }
});

describe("BridgeStore persistence", () => {
  it("should register project when valid input is provided", () => {
    const store = createStore();
    const project = store.createProject({
      name: "sunday",
      repository: "https://github.com/org/sunday.git",
      workingDirectory: "/repos/sunday",
      defaultBranch: "main",
    });

    expect(project.name).toBe("sunday");
    expect(store.getProjectByName("Sunday")?.id).toBe(project.id);
    expect(store.listProjects()).toHaveLength(1);
  });

  it("should register agent when upserted", () => {
    const store = createStore();
    const project = store.createProject({
      name: "sunday",
      repository: "https://github.com/org/sunday.git",
      workingDirectory: "/repos/sunday",
    });

    const agent = store.upsertAgent({
      agentId: "agent-123",
      projectId: project.id,
      mode: "local",
      branch: "main",
      workingDirectory: "/repos/sunday",
      repository: project.repository,
      status: "idle",
    });

    expect(agent.agentId).toBe("agent-123");
    expect(store.requireAgent("agent-123").projectId).toBe(project.id);
  });

  it("should register run and persist message conversation", () => {
    const store = createStore();
    store.upsertAgent({
      agentId: "agent-abc",
      mode: "cloud",
      status: "idle",
    });

    const run = store.createRun({
      runId: "run-1",
      agentId: "agent-abc",
      status: "running",
      prompt: "Fix the tests",
    });
    expect(run.status).toBe("running");

    store.addMessage({
      agentId: "agent-abc",
      runId: "run-1",
      role: "user",
      content: "Fix the tests",
    });
    store.addMessage({
      agentId: "agent-abc",
      runId: "run-1",
      role: "assistant",
      content: "Done",
    });
    store.updateRun("run-1", {
      status: "completed",
      response: "Done",
      completedAt: new Date().toISOString(),
    });

    const conversation = store.getConversation("agent-abc", 10);
    expect(conversation).toHaveLength(2);
    expect(conversation[0]?.role).toBe("user");
    expect(conversation[1]?.content).toBe("Done");
    expect(store.requireRun("run-1").status).toBe("completed");
  });

  it("should throw PROJECT_NOT_FOUND when project name is unknown", () => {
    const store = createStore();
    expect(() => store.requireProjectByName("missing")).toThrowError(
      /Project not found/,
    );
  });

  it("should throw AGENT_NOT_FOUND when agent is unknown", () => {
    const store = createStore();
    expect(() => store.requireAgent("nope")).toThrowError(/not found/i);
  });
});
