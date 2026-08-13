import { afterEach, describe, expect, it } from "vitest";
import { BridgeStore } from "../src/storage/store.js";

describe("BridgeStore", () => {
  let store: BridgeStore | undefined;

  afterEach(() => store?.close());

  it("should persist project, agent, run, message, and conversation", () => {
    store = new BridgeStore(":memory:");
    const project = store.registerProject({
      name: "sunday",
      repository: "https://github.com/example/sunday",
      workingDirectory: "/tmp/sunday",
      defaultBranch: "main",
    });
    const agent = store.createAgent({
      agentId: "agent-1",
      projectId: project.id,
      mode: "local",
      metadata: { source: "test" },
    });
    const run = store.createRun({
      runId: "run-1",
      agentId: agent.agent_id,
      prompt: "Inspect the project",
    });
    store.addMessage({
      agentId: agent.agent_id,
      runId: run.run_id,
      role: "user",
      content: "Inspect the project",
    });
    store.addMessage({
      agentId: agent.agent_id,
      runId: run.run_id,
      role: "assistant",
      content: "Inspection complete",
    });

    expect(store.getProjectByName("SUNDAY")).toEqual(project);
    expect(store.getAgent("agent-1")).toEqual(agent);
    expect(store.getRun("run-1")).toEqual(run);
    expect(store.getConversation("agent-1", 20).map((item) => item.content)).toEqual([
      "Inspect the project",
      "Inspection complete",
    ]);
  });

  it("should update an existing project without changing its id", () => {
    store = new BridgeStore(":memory:");
    const original = store.registerProject({
      name: "sunday",
      repository: "repo-a",
      workingDirectory: "/tmp/a",
      defaultBranch: "main",
    });
    const updated = store.registerProject({
      name: "Sunday",
      repository: "repo-b",
      workingDirectory: "/tmp/b",
      defaultBranch: "develop",
    });

    expect(updated.id).toBe(original.id);
    expect(updated.repository).toBe("repo-b");
    expect(updated.default_branch).toBe("develop");
    expect(store.listProjects()).toHaveLength(1);
  });
});
