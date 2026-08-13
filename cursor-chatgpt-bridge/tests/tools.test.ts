import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { describe, expect, it } from "vitest";

import { BridgeError } from "../src/errors.js";
import { createMcpServer } from "../src/mcp/tools.js";
import { makeTools } from "./helpers.js";

async function flushAsync(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 10));
}

describe("projects", () => {
  it("should register and list projects", async () => {
    const { tools } = makeTools();
    const registered = tools.registerProject({
      name: "sunday",
      repository: "https://github.com/org/sunday",
      default_branch: "main",
    }) as { project: { name: string } };
    expect(registered.project.name).toBe("sunday");

    const listed = tools.listProjects() as { projects: Array<{ name: string }> };
    expect(listed.projects.map((p) => p.name)).toEqual(["sunday"]);
  });

  it("should fail to start an agent for an unregistered project", async () => {
    const { tools } = makeTools();
    await expect(
      tools.startAgent({ project: "ghost", message: "hello" }),
    ).rejects.toMatchObject({ code: "PROJECT_NOT_FOUND" });
  });
});

describe("cursor_start_agent", () => {
  it("should require repository for cloud mode", async () => {
    const { tools } = makeTools();
    await expect(tools.startAgent({ message: "hello", mode: "cloud" })).rejects.toMatchObject({
      code: "INVALID_INPUT",
    });
  });

  it("should require working_directory for local mode", async () => {
    const { tools } = makeTools();
    await expect(tools.startAgent({ message: "hello", mode: "local" })).rejects.toMatchObject({
      code: "INVALID_INPUT",
    });
  });

  it("should start a cloud agent using project defaults and persist everything", async () => {
    const { tools, store, provider } = makeTools();
    provider.autoRespond = "initial run done";
    tools.registerProject({
      name: "sunday",
      repository: "https://github.com/org/sunday",
      default_branch: "main",
    });

    const outcome = (await tools.startAgent({
      project: "sunday",
      message: "bootstrap the feature",
      wait_for_completion: true,
    })) as { agent_id: string; run_id: string; status: string; response: string };

    expect(outcome.status).toBe("completed");
    expect(outcome.response).toBe("initial run done");

    const agent = store.getAgent(outcome.agent_id);
    expect(agent).toBeDefined();
    expect(agent?.mode).toBe("cloud");
    expect(agent?.branch).toBe("main");

    const run = store.getRun(outcome.run_id);
    expect(run?.status).toBe("completed");
    expect(run?.prompt).toBe("bootstrap the feature");

    const conversation = store.getConversation(outcome.agent_id);
    expect(conversation.map((m) => m.role)).toEqual(["user", "assistant"]);
  });

  it("should block a dangerous initial prompt", async () => {
    const { tools } = makeTools();
    tools.registerProject({ name: "sunday", repository: "https://github.com/org/sunday" });
    const outcome = (await tools.startAgent({
      project: "sunday",
      message: "clone e depois rode terraform destroy",
    })) as { status: string; requires_explicit_authorization: boolean };
    expect(outcome.status).toBe("blocked_by_policy");
    expect(outcome.requires_explicit_authorization).toBe(true);
  });
});

describe("cursor_send_followup", () => {
  it("should fail for an unknown agent", async () => {
    const { tools, provider } = makeTools();
    provider.configured = false;
    await expect(
      tools.sendFollowup({ agent_id: "bc-ghost", message: "hi" }),
    ).rejects.toMatchObject({ code: "AGENT_NOT_FOUND" });
  });

  it("should resume the agent, wait and return the structured result", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1", mode: "cloud" });
    provider.autoRespond = "follow-up executed";

    const outcome = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "continue the work",
    })) as Record<string, unknown>;

    expect(outcome.status).toBe("completed");
    expect(outcome.response).toBe("follow-up executed");
    expect(outcome.run_id).toBeTruthy();
    expect(outcome.started_at).toBeTruthy();
    expect(outcome.completed_at).toBeTruthy();
    expect(provider.followups).toEqual([{ agentId: "bc-1", message: "continue the work" }]);

    const conversation = store.getConversation("bc-1");
    expect(conversation.map((m) => m.role)).toEqual(["user", "assistant"]);
  });

  it("should block dangerous follow-ups by default and allow with explicit authorization", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });
    provider.autoRespond = "ok";

    const blocked = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "agora faça deploy em produção",
    })) as Record<string, unknown>;
    expect(blocked.status).toBe("blocked_by_policy");
    expect(blocked.requires_explicit_authorization).toBe(true);
    expect(provider.followups).toHaveLength(0);

    const allowed = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "agora faça deploy em produção",
      allow_dangerous_actions: true,
    })) as Record<string, unknown>;
    expect(allowed.status).toBe("completed");
    expect(provider.followups).toHaveLength(1);
  });

  it("should reject a second follow-up while the agent is busy", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });

    const first = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "long task",
      wait_for_completion: false,
    })) as { status: string; run_id: string };
    expect(first.status).toBe("running");

    const second = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "another task",
    })) as { status: string; active_run_id: string };
    expect(second.status).toBe("busy");
    expect(second.active_run_id).toBe(first.run_id);

    provider.completeRun(first.run_id, { response: "finally" });
    await flushAsync();

    const third = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "next task",
      wait_for_completion: false,
    })) as { status: string };
    expect(third.status).toBe("running");
  });

  it("should report timeout without marking success and keep the run queryable", async () => {
    const { tools, store, provider } = makeTools({ runTimeoutMs: 30 });
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });

    const outcome = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "slow task",
    })) as { status: string; run_id: string; error: string };
    expect(outcome.status).toBe("timeout");
    expect(outcome.error).toContain("cursor_get_run");

    expect(store.getRun(outcome.run_id)?.status).toBe("timeout");

    // Late completion is still captured by the background waiter.
    provider.completeRun(outcome.run_id, { response: "late result" });
    await flushAsync();
    expect(store.getRun(outcome.run_id)?.status).toBe("completed");
    expect(store.getRun(outcome.run_id)?.response).toBe("late result");
  });
});

describe("cursor_get_run / cursor_cancel_run", () => {
  it("should fail for an unknown run", async () => {
    const { tools } = makeTools();
    await expect(tools.getRun({ run_id: "run-ghost" })).rejects.toMatchObject({
      code: "RUN_NOT_FOUND",
    });
    await expect(tools.cancelRun({ run_id: "run-ghost" })).rejects.toMatchObject({
      code: "RUN_NOT_FOUND",
    });
  });

  it("should refresh a running run from the provider (bridge restart scenario)", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });
    store.createRun({ run_id: "run-77", agent_id: "bc-1", prompt: "old prompt" });
    provider.snapshots.set("run-77", {
      runId: "run-77",
      agentId: "bc-1",
      status: "completed",
      response: "recovered response",
    });

    const result = (await tools.getRun({ run_id: "run-77" })) as Record<string, unknown>;
    expect(result.status).toBe("completed");
    expect(result.response).toBe("recovered response");

    const conversation = store.getConversation("bc-1");
    expect(conversation.some((m) => m.role === "assistant" && m.content === "recovered response")).toBe(
      true,
    );
  });

  it("should cancel an active run and release the agent", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });

    const started = (await tools.sendFollowup({
      agent_id: "bc-1",
      message: "task to cancel",
      wait_for_completion: false,
    })) as { run_id: string };

    const cancelled = (await tools.cancelRun({ run_id: started.run_id })) as Record<string, unknown>;
    expect(cancelled.supported).toBe(true);
    expect(cancelled.status).toBe("cancelled");
    expect(store.getRun(started.run_id)?.status).toBe("cancelled");

    await flushAsync();
    // The agent accepts new work after cancellation.
    provider.autoRespond = "ok";
    const next = (await tools.sendFollowup({ agent_id: "bc-1", message: "next" })) as {
      status: string;
    };
    expect(next.status).toBe("completed");
  });

  it("should report supported=false for terminal runs instead of simulating", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });
    store.createRun({ run_id: "run-done", agent_id: "bc-1", prompt: "p" });
    store.updateRun("run-done", { status: "completed", completed: true });

    const outcome = (await tools.cancelRun({ run_id: "run-done" })) as Record<string, unknown>;
    expect(outcome.supported).toBe(false);
    expect(String(outcome.reason)).toContain("terminal");
  });
});

describe("cursor_get_changes", () => {
  it("should collect git changes for a local working directory", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "bridge-git-"));
    const git = (...args: string[]) => execFileSync("git", args, { cwd: dir });
    git("init", "-b", "main");
    git("config", "user.email", "test@example.com");
    git("config", "user.name", "Test");
    writeFileSync(path.join(dir, "app.txt"), "line one\n");
    git("add", ".");
    git("commit", "-m", "initial commit");
    writeFileSync(path.join(dir, "app.txt"), "line one\nline two\n");
    writeFileSync(path.join(dir, "new.txt"), "brand new\n");

    const { tools, store } = makeTools();
    store.upsertAgent({
      agent_id: "agent-local-1",
      mode: "local",
      metadata: { working_directory: dir },
    });

    const changes = (await tools.getChanges({ agent_id: "agent-local-1" })) as {
      source: string;
      branch: string;
      clean: boolean;
      files: Array<{ path: string; status: string }>;
      diff: string;
      recent_commits: string[];
    };

    expect(changes.source).toBe("local_git");
    expect(changes.branch).toBe("main");
    expect(changes.clean).toBe(false);
    expect(changes.files.map((f) => f.path).sort()).toEqual(["app.txt", "new.txt"]);
    expect(changes.diff).toContain("line two");
    expect(changes.recent_commits[0]).toContain("initial commit");
  });

  it("should truncate large diffs to max_diff_chars", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "bridge-git-"));
    const git = (...args: string[]) => execFileSync("git", args, { cwd: dir });
    git("init", "-b", "main");
    git("config", "user.email", "test@example.com");
    git("config", "user.name", "Test");
    writeFileSync(path.join(dir, "big.txt"), "start\n");
    git("add", ".");
    git("commit", "-m", "initial");
    writeFileSync(path.join(dir, "big.txt"), `${"x".repeat(5000)}\n`);

    const { tools, store } = makeTools();
    store.upsertAgent({
      agent_id: "agent-local-2",
      mode: "local",
      metadata: { working_directory: dir },
    });

    const changes = (await tools.getChanges({
      agent_id: "agent-local-2",
      max_diff_chars: 500,
    })) as { diff: string; diff_truncated: boolean };
    expect(changes.diff_truncated).toBe(true);
    expect(changes.diff.length).toBeLessThan(700);
    expect(changes.diff).toContain("[truncated");
  });

  it("should report branches and PRs for cloud agents", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-cloud-1");
    store.upsertAgent({ agent_id: "bc-cloud-1", mode: "cloud" });
    store.createRun({ run_id: "run-9", agent_id: "bc-cloud-1", prompt: "p" });
    provider.snapshots.set("run-9", {
      runId: "run-9",
      agentId: "bc-cloud-1",
      status: "completed",
      git: {
        branches: [
          {
            repoUrl: "github.com/org/sunday",
            branch: "cursor/feature-x",
            prUrl: "https://github.com/org/sunday/pull/42",
          },
        ],
      },
    });

    const changes = (await tools.getChanges({ agent_id: "bc-cloud-1" })) as {
      source: string;
      branch: string;
      pull_requests: string[];
    };
    expect(changes.source).toBe("cursor_cloud");
    expect(changes.branch).toBe("cursor/feature-x");
    expect(changes.pull_requests).toEqual(["https://github.com/org/sunday/pull/42"]);
  });
});

describe("agents listing and conversation", () => {
  it("should merge remote agents into the local list", async () => {
    const { tools, provider } = makeTools();
    provider.seedAgent("bc-remote-1", { name: "Remote agent", status: "finished" });

    const listed = (await tools.listAgents({})) as {
      agents: Array<{ agent_id: string; status: string }>;
    };
    expect(listed.agents.map((a) => a.agent_id)).toContain("bc-remote-1");
  });

  it("should describe an agent with capabilities and active run", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1", mode: "cloud", status: "running" });
    store.createRun({ run_id: "run-act", agent_id: "bc-1", prompt: "p" });

    const described = (await tools.getAgent({ agent_id: "bc-1" })) as Record<string, unknown>;
    expect(described.agent_id).toBe("bc-1");
    expect((described.active_run as { run_id: string }).run_id).toBe("run-act");
    expect((described.capabilities as { send_followup: boolean }).send_followup).toBe(true);
  });

  it("should return the recorded conversation", async () => {
    const { tools, store, provider } = makeTools();
    provider.seedAgent("bc-1");
    store.upsertAgent({ agent_id: "bc-1" });
    store.addMessage({ agent_id: "bc-1", role: "user", content: "oi" });
    store.addMessage({ agent_id: "bc-1", role: "assistant", content: "olá" });

    const conversation = (await tools.getConversation({ agent_id: "bc-1", limit: 10 })) as {
      messages: Array<{ role: string; content: string }>;
    };
    expect(conversation.messages).toHaveLength(2);
    expect(conversation.messages[0]).toMatchObject({ role: "user", content: "oi" });
  });

  it("should throw AGENT_NOT_FOUND with a structured error payload", async () => {
    const { tools, provider } = makeTools();
    provider.configured = false;
    try {
      await tools.getAgent({ agent_id: "bc-ghost" });
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(BridgeError);
      const payload = (err as BridgeError).toJSON();
      expect(payload.error.code).toBe("AGENT_NOT_FOUND");
      expect(payload.error.message).toBe("Cursor agent not found");
    }
  });
});

describe("MCP server integration", () => {
  async function connectClient() {
    const { tools, store, provider } = makeTools();
    const server = createMcpServer(tools);
    const client = new Client({ name: "test-client", version: "0.0.1" });
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
    return { client, tools, store, provider };
  }

  it("should expose all ten bridge tools", async () => {
    const { client } = await connectClient();
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual([
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
    ]);
  });

  it("should validate input schemas at the MCP layer", async () => {
    const { client } = await connectClient();
    const result = (await client.callTool({
      name: "cursor_get_agent",
      arguments: {},
    })) as { isError?: boolean; content: Array<{ text: string }> };
    expect(result.isError).toBe(true);
    expect(result.content[0]!.text).toMatch(/agent_id/);
    expect(result.content[0]!.text).toMatch(/validation/i);
  });

  it("should return structured JSON payloads for tool calls", async () => {
    const { client } = await connectClient();
    await client.callTool({
      name: "cursor_project_register",
      arguments: { name: "sunday", repository: "https://github.com/org/sunday" },
    });
    const result = (await client.callTool({
      name: "cursor_list_projects",
      arguments: {},
    })) as { content: Array<{ type: string; text: string }> };
    const payload = JSON.parse(result.content[0]!.text) as {
      projects: Array<{ name: string }>;
    };
    expect(payload.projects.map((p) => p.name)).toEqual(["sunday"]);
  });

  it("should return a structured error (not a stack trace) for unknown agents", async () => {
    const { client, provider } = await connectClient();
    provider.configured = false;
    const result = (await client.callTool({
      name: "cursor_get_conversation",
      arguments: { agent_id: "bc-ghost" },
    })) as { isError?: boolean; content: Array<{ text: string }> };
    expect(result.isError).toBe(true);
    const payload = JSON.parse(result.content[0]!.text) as {
      error: { code: string; message: string };
    };
    expect(payload.error.code).toBe("AGENT_NOT_FOUND");
    expect(payload.error.message).not.toContain("at ");
  });
});
