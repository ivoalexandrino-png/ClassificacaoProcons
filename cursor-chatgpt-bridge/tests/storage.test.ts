import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SqliteStore } from "../src/storage/store.js";

describe("SqliteStore", () => {
  let store: SqliteStore;

  beforeEach(() => {
    store = new SqliteStore(":memory:");
  });

  afterEach(() => {
    store.close();
  });

  it("should register a project and find it by name", () => {
    const project = store.createProject({
      name: "sunday",
      repository: "https://github.com/acme/sunday",
      workingDirectory: "/repos/sunday",
      defaultBranch: "main",
    });

    expect(project.id).toBeTruthy();
    expect(project.name).toBe("sunday");

    const found = store.findProjectByName("SUNDAY");
    expect(found?.id).toBe(project.id);
    expect(store.listProjects()).toHaveLength(1);
  });

  it("should upsert a project idempotently by name", () => {
    store.createProject({ name: "sunday", repository: "repo-a" });
    const updated = store.createProject({ name: "sunday", repository: "repo-b" });

    expect(store.listProjects()).toHaveLength(1);
    expect(updated.repository).toBe("repo-b");
  });

  it("should register an agent linked to a project", () => {
    const project = store.createProject({ name: "sunday" });
    const agent = store.upsertAgent({
      agentId: "agent-1",
      projectId: project.id,
      mode: "local",
      workingDirectory: "/repos/sunday",
      status: "running",
      metadata: { model: "auto" },
    });

    expect(agent.agent_id).toBe("agent-1");
    expect(agent.project_id).toBe(project.id);
    expect(agent.metadata).toEqual({ model: "auto" });
    expect(store.listAgents()).toHaveLength(1);
  });

  it("should create and update a run", () => {
    store.upsertAgent({ agentId: "agent-1", mode: "local" });
    const run = store.createRun({
      runId: "run-1",
      agentId: "agent-1",
      status: "running",
      prompt: "do the thing",
    });
    expect(run.status).toBe("running");
    expect(store.getActiveRunForAgent("agent-1")?.run_id).toBe("run-1");

    const updated = store.updateRun("run-1", {
      status: "completed",
      response: "done",
      completedAt: new Date().toISOString(),
    });
    expect(updated?.status).toBe("completed");
    expect(updated?.response).toBe("done");
    expect(store.getActiveRunForAgent("agent-1")).toBeNull();
  });

  it("should persist messages and recover the conversation in order", () => {
    store.upsertAgent({ agentId: "agent-1", mode: "local" });
    store.createRun({ runId: "run-1", agentId: "agent-1", status: "completed" });

    store.createMessage({ agentId: "agent-1", runId: "run-1", role: "user", content: "hi" });
    store.createMessage({
      agentId: "agent-1",
      runId: "run-1",
      role: "assistant",
      content: "hello",
      metadata: { tokens: 3 },
    });

    const conversation = store.listMessagesByAgent("agent-1", 10);
    expect(conversation).toHaveLength(2);
    expect(conversation[0]?.role).toBe("user");
    expect(conversation[1]?.role).toBe("assistant");
    expect(conversation[1]?.metadata).toEqual({ tokens: 3 });
  });

  it("should report healthcheck ok", () => {
    expect(store.healthcheck()).toBe(true);
  });
});
