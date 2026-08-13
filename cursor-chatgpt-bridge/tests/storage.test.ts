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

  it("should keep project mappings immutable after registration", () => {
    store = new BridgeStore(":memory:");
    const original = store.registerProject({
      name: "sunday",
      repository: "repo-a",
      workingDirectory: "/tmp/a",
      defaultBranch: "main",
    });
    expect(
      store.registerProject({
        name: "Sunday",
        repository: "repo-a",
        workingDirectory: "/tmp/a",
        defaultBranch: "main",
      }),
    ).toEqual(original);
    expect(() =>
      store!.registerProject({
        name: "Sunday",
        repository: "repo-b",
        workingDirectory: "/tmp/b",
        defaultBranch: "develop",
      }),
    ).toThrowError(expect.objectContaining({ code: "INVALID_INPUT" }));
    expect(store.listProjects()).toHaveLength(1);
  });

  it("should finalize a run and its messages exactly once", () => {
    store = new BridgeStore(":memory:");
    const project = store.registerProject({
      name: "sunday",
      repository: "repo",
      workingDirectory: "/tmp",
      defaultBranch: "main",
    });
    store.createAgent({
      agentId: "agent-1",
      projectId: project.id,
      mode: "local",
    });
    store.beginRun({
      runId: "run-1",
      agentId: "agent-1",
      prompt: "Continue",
    });
    const result = {
      runId: "run-1",
      status: "completed" as const,
      response: "Done",
      error: null,
      metadata: {},
      messages: [{ role: "assistant" as const, content: "Done" }],
    };

    expect(store.finalizeRun(result)).toBe(true);
    expect(store.finalizeRun(result)).toBe(false);
    expect(store.getConversation("agent-1", 20).map((item) => item.content)).toEqual([
      "Continue",
      "Done",
    ]);
  });
});
