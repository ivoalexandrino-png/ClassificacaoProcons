import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BridgeStore } from "../src/storage/store.js";

describe("BridgeStore", () => {
  let dbPath: string;
  let store: BridgeStore;

  beforeEach(() => {
    const dir = mkdtempSync(join(tmpdir(), "bridge-store-"));
    dbPath = join(dir, "test.db");
    store = new BridgeStore(dbPath);
  });

  afterEach(() => {
    store.close();
    rmSync(join(dbPath, ".."), { recursive: true, force: true });
  });

  it("should register and list projects", () => {
    const project = store.registerProject({
      name: "sunday",
      repository: "https://github.com/org/sunday",
      working_directory: "/tmp/sunday",
      default_branch: "main",
    });

    const projects = store.listProjects();
    expect(projects).toHaveLength(1);
    expect(projects[0].name).toBe("sunday");
    expect(project.id).toBe(projects[0].id);
  });

  it("should register agent and run and persist messages", () => {
    const project = store.registerProject({
      name: "sunday",
      repository: "https://github.com/org/sunday",
      working_directory: "/tmp/sunday",
      default_branch: "main",
    });

    store.upsertAgent({
      agent_id: "agent-123",
      project_id: project.id,
      mode: "local",
      branch: "main",
      status: "running",
      working_directory: "/tmp/sunday",
      repository: project.repository,
    });

    store.createRun({
      run_id: "run-123",
      agent_id: "agent-123",
      status: "running",
      prompt: "hello",
    });

    store.addMessage({
      agent_id: "agent-123",
      run_id: "run-123",
      role: "user",
      content: "hello",
    });
    store.addMessage({
      agent_id: "agent-123",
      run_id: "run-123",
      role: "assistant",
      content: "hi there",
    });

    const agent = store.getAgent("agent-123");
    expect(agent?.agent_id).toBe("agent-123");

    const conversation = store.getConversation("agent-123", 10);
    expect(conversation).toHaveLength(2);
    expect(conversation.map((m) => m.role)).toContain("user");
    expect(conversation.map((m) => m.role)).toContain("assistant");
  });
});
