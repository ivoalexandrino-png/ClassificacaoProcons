import { describe, expect, it } from "vitest";
import { BridgeStore } from "../src/storage/store.js";
import { temporaryDatabase } from "./helpers.js";

describe("BridgeStore", () => {
  it("should persist projects, agents, runs and conversation messages", () => {
    const store = new BridgeStore(temporaryDatabase());
    const project = store.registerProject({
      name: "sunday", repository: "https://github.com/example/sunday", workingDirectory: "/tmp/sunday", defaultBranch: "main"
    });
    store.createAgent({
      agentId: "agent-1", projectId: project.id, mode: "local", branch: "main", status: "idle",
      createdAt: "2026-01-01T00:00:00.000Z", lastActivityAt: "2026-01-01T00:00:00.000Z", metadata: { source: "test" }
    });
    store.createRun({
      runId: "run-1", agentId: "agent-1", status: "completed", prompt: "inspect", response: "done",
      startedAt: "2026-01-01T00:00:00.000Z", completedAt: "2026-01-01T00:01:00.000Z", error: null
    });
    store.addMessage({ agentId: "agent-1", runId: "run-1", role: "user", content: "inspect", metadata: {} });
    store.addMessage({ agentId: "agent-1", runId: "run-1", role: "assistant", content: "done", metadata: {} });

    expect(store.getProjectByName("sunday")?.repository).toBe("https://github.com/example/sunday");
    expect(store.getAgent("agent-1")?.metadata).toEqual({ source: "test" });
    expect(store.getRun("run-1")?.response).toBe("done");
    expect(store.getConversation("agent-1", 20).map((message) => message.content)).toEqual(["inspect", "done"]);
    store.close();
  });
});
