import { describe, expect, it } from "vitest";

import { BridgeStore } from "../src/storage/store.js";

function makeStore(): BridgeStore {
  return new BridgeStore(":memory:");
}

describe("BridgeStore", () => {
  it("should register and retrieve a project", () => {
    const store = makeStore();
    const project = store.registerProject({
      name: "sunday",
      repository: "https://github.com/org/sunday",
      working_directory: "/srv/sunday",
      default_branch: "main",
    });
    expect(project.name).toBe("sunday");
    expect(store.getProjectByName("sunday")?.id).toBe(project.id);
    expect(store.getProjectByName("SUNDAY")?.id).toBe(project.id);
    expect(store.listProjects()).toHaveLength(1);
  });

  it("should update an existing project when registered again", () => {
    const store = makeStore();
    const first = store.registerProject({ name: "sunday", default_branch: "main" });
    const second = store.registerProject({
      name: "sunday",
      repository: "https://github.com/org/sunday",
    });
    expect(second.id).toBe(first.id);
    expect(second.repository).toBe("https://github.com/org/sunday");
    expect(second.default_branch).toBe("main");
    expect(store.listProjects()).toHaveLength(1);
  });

  it("should register an agent linked to a project", () => {
    const store = makeStore();
    const project = store.registerProject({ name: "sunday" });
    const agent = store.upsertAgent({
      agent_id: "bc-123",
      project_id: project.id,
      mode: "cloud",
      status: "running",
      metadata: { repository: "https://github.com/org/sunday" },
    });
    expect(agent.agent_id).toBe("bc-123");
    expect(agent.project_id).toBe(project.id);
    expect(agent.metadata.repository).toBe("https://github.com/org/sunday");
    expect(store.listAgents()).toHaveLength(1);
  });

  it("should merge metadata when upserting an existing agent", () => {
    const store = makeStore();
    store.upsertAgent({ agent_id: "bc-1", metadata: { a: 1 } });
    const updated = store.upsertAgent({ agent_id: "bc-1", status: "finished", metadata: { b: 2 } });
    expect(updated.metadata).toEqual({ a: 1, b: 2 });
    expect(updated.status).toBe("finished");
  });

  it("should register a run and update its lifecycle", () => {
    const store = makeStore();
    store.upsertAgent({ agent_id: "bc-1" });
    const run = store.createRun({ run_id: "run-1", agent_id: "bc-1", prompt: "do it" });
    expect(run.status).toBe("running");
    expect(run.started_at).toBeTruthy();
    expect(run.completed_at).toBeNull();

    expect(store.getActiveRunForAgent("bc-1")?.run_id).toBe("run-1");

    const updated = store.updateRun("run-1", {
      status: "completed",
      response: "all done",
      completed: true,
    });
    expect(updated?.status).toBe("completed");
    expect(updated?.response).toBe("all done");
    expect(updated?.completed_at).toBeTruthy();
    expect(store.getActiveRunForAgent("bc-1")).toBeUndefined();
  });

  it("should return undefined when updating an unknown run", () => {
    const store = makeStore();
    expect(store.updateRun("missing", { status: "error" })).toBeUndefined();
  });

  it("should persist messages and recover the conversation in order", () => {
    const store = makeStore();
    store.upsertAgent({ agent_id: "bc-1" });
    store.addMessage({ agent_id: "bc-1", run_id: "run-1", role: "user", content: "first" });
    store.addMessage({ agent_id: "bc-1", run_id: "run-1", role: "assistant", content: "second" });
    store.addMessage({ agent_id: "bc-1", role: "system", content: "third" });

    const conversation = store.getConversation("bc-1");
    expect(conversation.map((m) => m.content)).toEqual(["first", "second", "third"]);
    expect(conversation.map((m) => m.role)).toEqual(["user", "assistant", "system"]);
  });

  it("should respect the conversation limit and keep the most recent messages", () => {
    const store = makeStore();
    store.upsertAgent({ agent_id: "bc-1" });
    for (let i = 1; i <= 30; i += 1) {
      store.addMessage({ agent_id: "bc-1", role: "user", content: `msg-${i}` });
    }
    const conversation = store.getConversation("bc-1", 5);
    expect(conversation.map((m) => m.content)).toEqual([
      "msg-26",
      "msg-27",
      "msg-28",
      "msg-29",
      "msg-30",
    ]);
  });
});
