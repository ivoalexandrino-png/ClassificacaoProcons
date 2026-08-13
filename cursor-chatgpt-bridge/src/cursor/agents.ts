import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { BridgeStore } from "../storage/store.js";
import { evaluateInstruction } from "../security/policy.js";
import type { AgentRecord, CursorAgentProvider, Project, ProviderRun, RunRecord } from "./types.js";

const execFileAsync = promisify(execFile);

export class BridgeError extends Error {
  constructor(readonly code: string, message: string, readonly details: Record<string, unknown> = {}) {
    super(message);
  }
}

export class BridgeService {
  private readonly activeRuns = new Map<string, { runId: string; completion: Promise<RunRecord> }>();

  constructor(
    private readonly store: BridgeStore,
    private readonly provider: CursorAgentProvider,
    private readonly runTimeoutMs: number
  ) {}

  registerProject(input: Omit<Project, "id" | "createdAt" | "updatedAt">): Project {
    return this.store.registerProject(input);
  }

  listProjects(): Project[] { return this.store.listProjects(); }

  listAgents(): Array<AgentRecord & { project: Project }> {
    return this.store.listAgents().map((agent) => ({ ...agent, project: this.requireProject(agent.projectId) }));
  }

  getAgent(agentId: string): AgentRecord & { project: Project; activeRunId?: string } {
    const agent = this.requireAgent(agentId);
    return { ...agent, project: this.requireProject(agent.projectId), activeRunId: this.activeRuns.get(agentId)?.runId };
  }

  async startAgent(input: { project: string; message: string; mode: AgentRecord["mode"] }): Promise<RunRecord> {
    const project = this.requireProjectByName(input.project);
    const providerAgent = await this.provider.createAgent({
      mode: input.mode,
      repository: project.repository,
      workingDirectory: project.workingDirectory,
      defaultBranch: project.defaultBranch
    });
    const timestamp = new Date().toISOString();
    const agent: AgentRecord = {
      agentId: providerAgent.agentId, projectId: project.id, mode: input.mode, branch: project.defaultBranch,
      status: "idle", createdAt: timestamp, lastActivityAt: timestamp, metadata: providerAgent.metadata ?? {}
    };
    this.store.createAgent(agent);
    return this.sendFollowup({ agentId: agent.agentId, message: input.message, waitForCompletion: true });
  }

  async sendFollowup(input: {
    agentId: string; message: string; waitForCompletion: boolean; allowDangerousActions?: boolean;
  }): Promise<RunRecord> {
    const policy = evaluateInstruction(input.message, input.allowDangerousActions);
    if (!policy.allowed) {
      throw new BridgeError("BLOCKED_BY_POLICY", policy.reason!, {
        requires_explicit_authorization: policy.requiresExplicitAuthorization
      });
    }
    const agent = this.requireAgent(input.agentId);
    const project = this.requireProject(agent.projectId);
    const active = this.activeRuns.get(agent.agentId);
    if (active) throw new BridgeError("AGENT_BUSY", "Agent already has an active run", { active_run_id: active.runId });

    await this.provider.resumeAgent(agent.agentId, project.workingDirectory);
    const providerRun = await this.provider.sendMessage(agent.agentId, project.workingDirectory, input.message);
    const startedAt = providerRun.startedAt ?? new Date().toISOString();
    const record: RunRecord = {
      runId: providerRun.runId, agentId: agent.agentId, status: "running", prompt: input.message,
      response: null, startedAt, completedAt: null, error: null
    };
    this.store.createRun(record);
    this.store.addMessage({ agentId: agent.agentId, runId: record.runId, role: "user", content: input.message, metadata: {} });
    this.store.updateAgentStatus(agent.agentId, "running");

    const completion = this.completeRun(providerRun, agent, project);
    this.activeRuns.set(agent.agentId, { runId: record.runId, completion });
    if (!input.waitForCompletion) return record;

    return Promise.race([
      completion,
      new Promise<RunRecord>((resolve) => setTimeout(() => {
        const timeout = { ...record, status: "timeout" as const, error: "Run exceeded configured wait timeout" };
        this.store.updateRun(record.runId, {
          status: "timeout", response: null, completedAt: null, error: timeout.error
        });
        resolve(timeout);
      }, this.runTimeoutMs))
    ]);
  }

  async getRun(runId: string): Promise<RunRecord> {
    const record = this.requireRun(runId);
    if (record.status === "running") {
      const agent = this.requireAgent(record.agentId);
      const project = this.requireProject(agent.projectId);
      const current = await this.provider.getRun(runId, agent.agentId, agent.mode, project.workingDirectory);
      if (current.status !== "running") return this.persistCompletedRun(record, current);
    }
    return this.requireRun(runId);
  }

  async cancelRun(runId: string): Promise<{ supported: true }> {
    const run = this.requireRun(runId);
    const agent = this.requireAgent(run.agentId);
    const project = this.requireProject(agent.projectId);
    await this.provider.cancelRun(runId, agent.agentId, agent.mode, project.workingDirectory);
    return { supported: true };
  }

  async getConversation(agentId: string, limit: number) {
    this.requireAgent(agentId);
    return this.store.getConversation(agentId, limit);
  }

  async getChanges(agentId: string, maxDiffChars: number) {
    const agent = this.requireAgent(agentId);
    const project = this.requireProject(agent.projectId);
    if (agent.mode !== "local") {
      return { branch: agent.branch, clean: null, files: [], diff_stat: "", diff: "", reason: "Cloud working tree is not locally available" };
    }
    const runGit = async (...args: string[]) => (await execFileAsync("git", args, {
      cwd: project.workingDirectory, maxBuffer: maxDiffChars + 10_000
    })).stdout;
    const [branch, status, diffStat, diff, commits] = await Promise.all([
      runGit("branch", "--show-current"), runGit("status", "--short"), runGit("diff", "--stat"),
      runGit("diff"), runGit("log", "--oneline", "-5")
    ]);
    return {
      branch: branch.trim() || agent.branch, clean: status.trim().length === 0,
      files: status.split("\n").filter(Boolean), diff_stat: diffStat.trim(),
      diff: diff.slice(0, maxDiffChars), diff_truncated: diff.length > maxDiffChars,
      recent_commits: commits.trim().split("\n").filter(Boolean)
    };
  }

  private async completeRun(providerRun: ProviderRun, agent: AgentRecord, project: Project): Promise<RunRecord> {
    try {
      const result = await this.provider.waitForRun(providerRun.runId, agent.agentId, agent.mode, project.workingDirectory);
      return this.persistCompletedRun(this.requireRun(providerRun.runId), result);
    } catch (error) {
      const failed = this.persistCompletedRun(this.requireRun(providerRun.runId), {
        ...providerRun, status: "error", error: error instanceof Error ? error.message : "Cursor API error"
      });
      return failed;
    } finally {
      this.activeRuns.delete(agent.agentId);
    }
  }

  private persistCompletedRun(record: RunRecord, result: ProviderRun): RunRecord {
    const completed: RunRecord = {
      ...record, status: result.status, response: result.response ?? null,
      completedAt: result.completedAt ?? new Date().toISOString(), error: result.error ?? null
    };
    this.store.updateRun(record.runId, {
      status: completed.status, response: completed.response, completedAt: completed.completedAt, error: completed.error
    });
    this.store.updateAgentStatus(record.agentId, completed.status === "completed" ? "idle" : completed.status);
    if (completed.response) {
      this.store.addMessage({
        agentId: record.agentId, runId: record.runId, role: "assistant", content: completed.response, metadata: {}
      });
    }
    return completed;
  }

  private requireProject(id: number): Project {
    const project = this.store.getProject(id);
    if (!project) throw new BridgeError("PROJECT_NOT_FOUND", "Registered project not found", { project_id: id });
    return project;
  }
  private requireProjectByName(name: string): Project {
    const project = this.store.getProjectByName(name);
    if (!project) throw new BridgeError("PROJECT_NOT_FOUND", "Registered project not found", { project: name });
    return project;
  }
  private requireAgent(agentId: string): AgentRecord {
    const agent = this.store.getAgent(agentId);
    if (!agent) throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", { agent_id: agentId });
    return agent;
  }
  private requireRun(runId: string): RunRecord {
    const run = this.store.getRun(runId);
    if (!run) throw new BridgeError("RUN_NOT_FOUND", "Cursor run not found", { run_id: runId });
    return run;
  }
}
