import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { CursorAgentProvider, MessageRecord, ProviderAgent, ProviderRun } from "../src/cursor/types.js";

export class FakeProvider implements CursorAgentProvider {
  calls: string[] = [];
  private runCounter = 0;
  private readonly runs = new Map<string, ProviderRun>();

  async createAgent(): Promise<ProviderAgent> { return { agentId: "agent-test", status: "idle" }; }
  async resumeAgent(): Promise<void> { this.calls.push("resume"); }
  async sendMessage(agentId: string, _cwd: string, message: string): Promise<ProviderRun> {
    this.calls.push(`send:${message}`);
    const run = { runId: `run-${++this.runCounter}`, agentId, status: "running" as const };
    this.runs.set(run.runId, run);
    return run;
  }
  async waitForRun(runId: string, agentId: string): Promise<ProviderRun> {
    this.calls.push(`wait:${runId}`);
    return { runId, agentId, status: "completed", response: "done", completedAt: new Date().toISOString() };
  }
  async getAgent(agentId: string): Promise<ProviderAgent> { return { agentId, status: "idle" }; }
  async getRun(runId: string, agentId: string): Promise<ProviderRun> {
    return this.runs.get(runId) ?? { runId, agentId, status: "completed", response: "done" };
  }
  async cancelRun(): Promise<void> { this.calls.push("cancel"); }
  async getConversation(): Promise<MessageRecord[]> { return []; }
}

export const temporaryDatabase = () => join(mkdtempSync(join(tmpdir(), "bridge-test-")), "bridge.db");
