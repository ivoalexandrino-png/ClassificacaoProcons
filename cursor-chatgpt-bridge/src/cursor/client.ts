import { Agent } from "@cursor/sdk";
import type {
  AgentMode,
  CursorAgentProvider,
  MessageRecord,
  ProviderAgent,
  ProviderRun
} from "./types.js";

type SdkRun = Awaited<ReturnType<Awaited<ReturnType<typeof Agent.resume>>["send"]>>;

const toRunStatus = (status: string): ProviderRun["status"] => {
  if (status === "finished") return "completed";
  if (status === "cancelled") return "cancelled";
  if (status === "error") return "error";
  return "running";
};

export class CursorSdkProvider implements CursorAgentProvider {
  private readonly activeRuns = new Map<string, SdkRun>();

  async createAgent(input: {
    mode: AgentMode;
    repository: string;
    workingDirectory: string;
    defaultBranch: string;
  }): Promise<ProviderAgent> {
    const agent =
      input.mode === "local"
        ? await Agent.create({ local: { cwd: input.workingDirectory } })
        : await Agent.create({
            cloud: {
              repos: [{ url: input.repository, startingRef: input.defaultBranch }]
            }
          });
    return { agentId: agent.agentId, status: "idle" };
  }

  async resumeAgent(agentId: string, workingDirectory: string): Promise<void> {
    await Agent.resume(agentId, { local: { cwd: workingDirectory } });
  }

  async sendMessage(agentId: string, workingDirectory: string, message: string): Promise<ProviderRun> {
    const agent = await Agent.resume(agentId, { local: { cwd: workingDirectory } });
    const run = await agent.send(message);
    this.activeRuns.set(run.id, run);
    return { runId: run.id, agentId, status: toRunStatus(run.status), startedAt: new Date().toISOString() };
  }

  async waitForRun(
    runId: string,
    agentId: string,
    mode: AgentMode,
    workingDirectory: string
  ): Promise<ProviderRun> {
    const run = this.activeRuns.get(runId) ??
      (await Agent.getRun(runId, mode === "cloud"
        ? { runtime: "cloud", agentId }
        : { runtime: "local", cwd: workingDirectory }));
    const result = await run.wait();
    this.activeRuns.delete(runId);
    return {
      runId,
      agentId,
      status: toRunStatus(result.status),
      response: result.result,
      error: result.error?.message,
      completedAt: new Date().toISOString()
    };
  }

  async getAgent(agentId: string, workingDirectory: string): Promise<ProviderAgent> {
    const info = await Agent.get(agentId, { cwd: workingDirectory });
    return { agentId: info.agentId, status: info.status, metadata: { name: info.name, summary: info.summary } };
  }

  async getRun(
    runId: string,
    agentId: string,
    mode: AgentMode,
    workingDirectory: string
  ): Promise<ProviderRun> {
    const run = await Agent.getRun(runId, mode === "cloud"
      ? { runtime: "cloud", agentId }
      : { runtime: "local", cwd: workingDirectory });
    return {
      runId,
      agentId,
      status: toRunStatus(run.status),
      response: run.result,
      error: run.error?.message
    };
  }

  async cancelRun(runId: string, agentId: string, mode: AgentMode, workingDirectory: string): Promise<void> {
    const active = this.activeRuns.get(runId);
    if (active) {
      await active.cancel();
      return;
    }
    await Agent.cancelRun(runId, mode === "cloud"
      ? { runtime: "cloud", agentId }
      : { runtime: "local", cwd: workingDirectory });
  }

  async getConversation(agentId: string, workingDirectory: string, limit: number): Promise<MessageRecord[]> {
    const messages = await Agent.messages.list(agentId, { cwd: workingDirectory, limit });
    return messages.map((message) => ({
      id: 0,
      agentId,
      runId: null,
      role: message.type,
      content: JSON.stringify(message.message),
      createdAt: new Date().toISOString(),
      metadata: { source: "cursor-sdk" }
    }));
  }
}
