import { beforeEach, describe, expect, it } from "vitest";
import { BridgeStore } from "../src/storage/store.js";

describe("BridgeStore", () => {
  let store: BridgeStore;

  beforeEach(() => {
    store = new BridgeStore(":memory:");
  });

  it("should register a project when given a unique name", () => {
    const project = store.createProject({
      name: "sunday",
      repository: "https://github.com/acme/sunday",
      workingDirectory: "/repos/sunday",
      defaultBranch: "main",
    });

    expect(project.name).toBe("sunday");
    expect(project.repository).toBe("https://github.com/acme/sunday");
    expect(project.working_directory).toBe("/repos/sunday");
    expect(project.default_branch).toBe("main");
    expect(store.getProjectByName("sunday")?.id).toBe(project.id);
  });

  it("should update the existing project when registering the same name twice", () => {
    const first = store.createProject({ name: "sunday", repository: "https://github.com/acme/sunday" });
    const second = store.createProject({ name: "sunday", repository: "https://github.com/acme/sunday-v2" });

    expect(second.id).toBe(first.id);
    expect(second.repository).toBe("https://github.com/acme/sunday-v2");
    expect(store.listProjects()).toHaveLength(1);
  });

  it("should register an agent linked to a project", () => {
    const project = store.createProject({ name: "sunday" });
    const agent = store.createAgent({
      agentId: "bc-123",
      projectId: project.id,
      mode: "cloud",
      branch: "cursor/fix-bug",
      repository: "https://github.com/acme/sunday",
      status: "running",
    });

    expect(agent.agent_id).toBe("bc-123");
    expect(agent.project_id).toBe(project.id);
    expect(agent.mode).toBe("cloud");
    expect(agent.status).toBe("running");
    expect(store.getAgent("bc-123")?.agent_id).toBe("bc-123");
  });

  it("should register a run for an agent and update it to a terminal state", () => {
    store.createAgent({ agentId: "bc-123", mode: "cloud", status: "running" });
    const run = store.createRun({ runId: "run-1", agentId: "bc-123", status: "running", prompt: "Do the thing" });

    expect(run.run_id).toBe("run-1");
    expect(run.status).toBe("running");
    expect(run.completed_at).toBeNull();

    const updated = store.updateRun("run-1", {
      status: "completed",
      response: "Done.",
      completedAt: "2026-01-01T00:00:00.000Z",
    });

    expect(updated.status).toBe("completed");
    expect(updated.response).toBe("Done.");
    expect(updated.completed_at).toBe("2026-01-01T00:00:00.000Z");
  });

  it("should persist messages and retrieve the conversation in chronological order", () => {
    store.createAgent({ agentId: "bc-123", mode: "cloud", status: "running" });
    store.createRun({ runId: "run-1", agentId: "bc-123", status: "running", prompt: "Do the thing" });

    store.createMessage({ agentId: "bc-123", runId: "run-1", role: "user", content: "Do the thing" });
    store.createMessage({ agentId: "bc-123", runId: "run-1", role: "assistant", content: "Done." });
    store.createMessage({ agentId: "bc-123", role: "system", content: "Follow-up blocked by policy." });

    const conversation = store.listMessagesByAgent("bc-123", 20);

    expect(conversation).toHaveLength(3);
    expect(conversation.map((message) => message.role)).toEqual(["user", "assistant", "system"]);
    expect(conversation[0]?.content).toBe("Do the thing");
    expect(conversation[1]?.content).toBe("Done.");
  });

  it("should report no active run when the agent has none in flight", () => {
    store.createAgent({ agentId: "bc-123", mode: "cloud", status: "running" });
    expect(store.getActiveRun("bc-123")).toBeUndefined();

    store.createRun({ runId: "run-1", agentId: "bc-123", status: "running", prompt: "Do the thing" });
    expect(store.getActiveRun("bc-123")?.run_id).toBe("run-1");

    store.updateRun("run-1", { status: "completed", completedAt: new Date().toISOString() });
    expect(store.getActiveRun("bc-123")).toBeUndefined();
  });

  it("should return undefined for an agent that was never registered", () => {
    expect(store.getAgent("does-not-exist")).toBeUndefined();
  });
});
