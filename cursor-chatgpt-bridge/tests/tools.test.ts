import { describe, expect, it } from "vitest";
import { BridgeError, BridgeService } from "../src/cursor/agents.js";
import { followupSchema, projectSchema } from "../src/mcp/schemas.js";
import { BridgeStore } from "../src/storage/store.js";
import { FakeProvider, temporaryDatabase } from "./helpers.js";

const setup = () => {
  const store = new BridgeStore(temporaryDatabase());
  const provider = new FakeProvider();
  const service = new BridgeService(store, provider, 10_000);
  service.registerProject({
    name: "sunday", repository: "https://github.com/example/sunday", workingDirectory: "/tmp/sunday", defaultBranch: "main"
  });
  store.createAgent({
    agentId: "agent-1", projectId: store.getProjectByName("sunday")!.id, mode: "local", branch: "main",
    status: "idle", createdAt: new Date().toISOString(), lastActivityAt: new Date().toISOString(), metadata: {}
  });
  return { store, provider, service };
};

describe("bridge tool service", () => {
  it("should validate public tool input schemas", () => {
    expect(followupSchema.parse({ agent_id: "agent-1", message: "continue" })).toMatchObject({
      wait_for_completion: true, allow_dangerous_actions: false
    });
    expect(() => projectSchema.parse({ name: "" })).toThrow();
  });

  it("should return a structured completed run for a follow-up", async () => {
    const { service } = setup();
    await expect(service.sendFollowup({ agentId: "agent-1", message: "continue", waitForCompletion: true }))
      .resolves.toMatchObject({ agentId: "agent-1", status: "completed", response: "done" });
  });

  it("should reject an unknown agent", async () => {
    const { service } = setup();
    await expect(service.sendFollowup({ agentId: "missing", message: "continue", waitForCompletion: true }))
      .rejects.toMatchObject<Partial<BridgeError>>({ code: "AGENT_NOT_FOUND" });
  });

  it("should reject a start request for an unknown project", async () => {
    const { service } = setup();
    await expect(service.startAgent({ project: "missing", message: "start", mode: "local" }))
      .rejects.toMatchObject<Partial<BridgeError>>({ code: "PROJECT_NOT_FOUND" });
  });

  it("should reject a second follow-up while the agent is busy", async () => {
    const { service, provider } = setup();
    provider.waitForRun = async () => new Promise(() => undefined);
    await service.sendFollowup({ agentId: "agent-1", message: "continue", waitForCompletion: false });
    await expect(service.sendFollowup({ agentId: "agent-1", message: "again", waitForCompletion: false }))
      .rejects.toMatchObject<Partial<BridgeError>>({ code: "AGENT_BUSY" });
  });

  it("should block dangerous actions", async () => {
    const { service } = setup();
    await expect(service.sendFollowup({
      agentId: "agent-1", message: "run terraform destroy", waitForCompletion: true
    })).rejects.toMatchObject<Partial<BridgeError>>({ code: "BLOCKED_BY_POLICY" });
  });
});
