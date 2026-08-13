import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { inspectLocalChanges } from "../cursor/agents.js";
import { AgentLock } from "../cursor/runs.js";
import type {
  AgentRuntimeContext,
  CursorAgentProvider,
  ProviderRun,
  ProviderRunResult,
} from "../cursor/types.js";
import { BridgeError } from "../errors.js";
import { Logger } from "../logger.js";
import { evaluatePolicy } from "../security/policy.js";
import { BridgeStore } from "../storage/store.js";
import type { AgentRecord, ProjectRecord, RunRecord } from "../storage/types.js";
import type {
  RegisterProjectInput,
  SendFollowupInput,
  StartAgentInput,
} from "./schemas.js";

type StructuredResponse = Record<string, unknown>;

export class BridgeTools {
  private readonly locks = new AgentLock();

  constructor(
    private readonly store: BridgeStore,
    private readonly provider: CursorAgentProvider,
    private readonly runTimeoutMs: number,
    private readonly defaultMaxDiffCharacters: number,
    private readonly logger = new Logger(),
  ) {}

  listProjects(): StructuredResponse {
    return { projects: this.store.listProjects() };
  }

  registerProject(input: RegisterProjectInput): StructuredResponse {
    const project = this.store.registerProject({
      name: input.name,
      repository: input.repository,
      workingDirectory: path.resolve(input.working_directory),
      defaultBranch: input.default_branch,
    });
    return { project };
  }

  listAgents(): StructuredResponse {
    const agents = this.store.listAgents().map((agent) => ({
      agent_id: agent.agent_id,
      project: agent.project,
      repository: agent.repository,
      branch: agent.branch,
      status: agent.status,
      last_activity_at: agent.last_activity_at,
    }));
    return { agents };
  }

  getAgent(agentId: string): StructuredResponse {
    const agent = this.requireAgent(agentId);
    const project = this.requireProjectById(agent.project_id);
    const activeRun = this.store.getActiveRun(agentId);
    return {
      agent: {
        agent_id: agent.agent_id,
        project: project.name,
        repository: project.repository,
        branch: agent.branch,
        working_directory: agent.mode === "local" ? project.working_directory : null,
        mode: agent.mode,
        status: agent.status,
        created_at: agent.created_at,
        last_activity_at: agent.last_activity_at,
        active_run_id: activeRun?.run_id ?? null,
        metadata: agent.metadata,
        capabilities: {
          followup: true,
          conversation: true,
          cancel_run: true,
          local_changes: agent.mode === "local",
        },
      },
    };
  }

  getConversation(agentId: string, limit: number): StructuredResponse {
    this.requireAgent(agentId);
    return {
      agent_id: agentId,
      messages: this.store.getConversation(agentId, limit),
    };
  }

  async startAgent(input: StartAgentInput): Promise<StructuredResponse> {
    const project = this.requireProjectByName(input.project);
    this.assertProjectMatches(project, input.repository, input.working_directory);
    this.assertPolicy(input.message, input.allow_dangerous_actions);
    if (input.mode === "local") {
      this.assertLocalDirectory(project.working_directory);
    }

    let providerAgent;
    try {
      providerAgent = await this.provider.createAgent({
        mode: input.mode,
        repository: project.repository,
        workingDirectory: project.working_directory,
        branch: project.default_branch,
        project: project.name,
      });
    } catch (error) {
      throw this.asCursorError(error);
    }
    const agent = this.store.createAgent({
      agentId: providerAgent.agentId,
      projectId: project.id,
      mode: input.mode,
      branch: project.default_branch,
      metadata: {
        ...providerAgent.metadata,
        capabilities: providerAgent.capabilities,
      },
    });
    return this.executePrompt(agent, project, input.message, input.wait_for_completion);
  }

  async sendFollowup(input: SendFollowupInput): Promise<StructuredResponse> {
    const decision = evaluatePolicy(input.message, input.allow_dangerous_actions);
    if (!decision.allowed) {
      return {
        agent_id: input.agent_id,
        status: "blocked_by_policy",
        reason: decision.reason,
        matched_rule: decision.matched_rule,
        requires_explicit_authorization: true,
      };
    }
    const agent = this.requireAgent(input.agent_id);
    const project = this.requireProjectById(agent.project_id);
    return this.executePrompt(agent, project, input.message, input.wait_for_completion);
  }

  async getRun(runId: string): Promise<StructuredResponse> {
    let record = this.requireRun(runId);
    if (record.status === "running" || record.status === "timeout") {
      const agent = this.requireAgent(record.agent_id);
      const project = this.requireProjectById(agent.project_id);
      if (!this.locks.acquire(agent.agent_id, runId)) {
        return this.runResponse(record);
      }
      try {
        const providerRun = await this.provider.getRun(
          agent.agent_id,
          runId,
          this.runtimeContext(agent, project),
        );
        if (providerRun.status !== "running") {
          record = this.persistResult(
            agent,
            providerRun,
            await providerRun.wait(),
          );
        }
      } catch (error) {
        this.logger.warn("cursor_run_refresh_failed", {
          agent_id: agent.agent_id,
          run_id: runId,
          reason: error instanceof Error ? error.message : "unknown",
        });
      } finally {
        this.locks.release(agent.agent_id, runId);
      }
    }
    return this.runResponse(record);
  }

  async cancelRun(runId: string): Promise<StructuredResponse> {
    const run = this.requireRun(runId);
    const agent = this.requireAgent(run.agent_id);
    const project = this.requireProjectById(agent.project_id);
    const result = await this.provider.cancelRun(
      agent.agent_id,
      run.run_id,
      this.runtimeContext(agent, project),
    );
    if (!result.supported) {
      return {
        run_id: runId,
        supported: false,
        reason: result.reason ?? "Cancellation is not supported by the Cursor provider",
      };
    }
    this.store.completeRun(runId, "cancelled", run.response, null);
    this.store.updateAgent(agent.agent_id, "cancelled");
    this.locks.release(agent.agent_id, runId);
    return { run_id: runId, supported: true, status: "cancelled" };
  }

  async getChanges(agentId: string, maxDiffCharacters?: number): Promise<StructuredResponse> {
    const agent = this.requireAgent(agentId);
    const project = this.requireProjectById(agent.project_id);
    if (agent.mode !== "local") {
      return {
        agent_id: agentId,
        supported: false,
        reason: "Filesystem git inspection is only available for local Cursor agents",
        cursor_git: this.store.getLatestRun(agentId)?.metadata.git ?? null,
      };
    }
    return {
      agent_id: agentId,
      supported: true,
      ...(await inspectLocalChanges(
        project.working_directory,
        maxDiffCharacters ?? this.defaultMaxDiffCharacters,
      )),
    };
  }

  private async executePrompt(
    agent: AgentRecord,
    project: ProjectRecord,
    prompt: string,
    waitForCompletion: boolean,
  ): Promise<StructuredResponse> {
    const persistedActiveRun = this.store.getActiveRun(agent.agent_id);
    const inMemoryActiveRun = this.locks.getActiveRun(agent.agent_id);
    if (persistedActiveRun || inMemoryActiveRun) {
      throw new BridgeError(
        "AGENT_BUSY",
        "Cursor agent already has an active run",
        { active_run_id: persistedActiveRun?.run_id ?? inMemoryActiveRun },
        409,
      );
    }

    const pendingId = `pending-${randomUUID()}`;
    if (!this.locks.acquire(agent.agent_id, pendingId)) {
      throw new BridgeError("AGENT_BUSY", "Cursor agent already has an active run", {}, 409);
    }

    let providerRun: ProviderRun;
    try {
      providerRun = await this.provider.sendMessage(
        agent.agent_id,
        prompt,
        this.runtimeContext(agent, project),
      );
    } catch (error) {
      this.locks.release(agent.agent_id, pendingId);
      this.store.updateAgent(agent.agent_id, "error");
      throw this.asCursorError(error);
    }

    this.locks.replace(agent.agent_id, pendingId, providerRun.runId);
    const run = this.store.createRun({
      runId: providerRun.runId,
      agentId: agent.agent_id,
      prompt,
      metadata: {},
    });
    this.store.addMessage({
      agentId: agent.agent_id,
      runId: providerRun.runId,
      role: "user",
      content: prompt,
    });
    this.store.updateAgent(agent.agent_id, "running");
    this.logger.info("cursor_run_started", {
      agent_id: agent.agent_id,
      run_id: providerRun.runId,
    });

    const completion = this.monitorRun(agent, providerRun);
    if (!waitForCompletion) return this.runResponse(run);

    let timer: NodeJS.Timeout | undefined;
    const timeout = new Promise<RunRecord>((resolve) => {
      timer = setTimeout(() => {
        this.store.completeRun(
          providerRun.runId,
          "timeout",
          null,
          `Run exceeded ${this.runTimeoutMs} ms; the Cursor run may still be active`,
        );
        this.store.updateAgent(agent.agent_id, "timeout");
        resolve(this.requireRun(providerRun.runId));
      }, this.runTimeoutMs);
    });
    const completed = await Promise.race([completion, timeout]);
    if (timer) clearTimeout(timer);
    return this.runResponse(completed);
  }

  private async monitorRun(agent: AgentRecord, providerRun: ProviderRun): Promise<RunRecord> {
    try {
      const result = await providerRun.wait();
      return this.persistResult(agent, providerRun, result);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "Unknown Cursor run error";
      this.store.completeRun(providerRun.runId, "error", null, reason);
      this.store.updateAgent(agent.agent_id, "error");
      return this.requireRun(providerRun.runId);
    } finally {
      this.locks.release(agent.agent_id, providerRun.runId);
    }
  }

  private persistResult(
    agent: AgentRecord,
    providerRun: ProviderRun,
    result: ProviderRunResult,
  ): RunRecord {
    for (const message of result.messages) {
      this.store.addMessage({
        agentId: agent.agent_id,
        runId: providerRun.runId,
        role: message.role,
        content: message.content,
        metadata: message.metadata,
      });
    }
    if (result.response) {
      this.store.addMessage({
        agentId: agent.agent_id,
        runId: providerRun.runId,
        role: "assistant",
        content: result.response,
      });
    }
    this.store.completeRun(
      providerRun.runId,
      result.status,
      result.response,
      result.error,
      result.metadata,
    );
    this.store.updateAgent(agent.agent_id, result.status);
    this.logger.info("cursor_run_completed", {
      agent_id: agent.agent_id,
      run_id: providerRun.runId,
      status: result.status,
      duration_ms: result.metadata.duration_ms,
    });
    return this.requireRun(providerRun.runId);
  }

  private runResponse(run: RunRecord): StructuredResponse {
    return {
      run_id: run.run_id,
      agent_id: run.agent_id,
      status: run.status,
      response: run.response,
      started_at: run.started_at,
      completed_at: run.completed_at,
      error: run.error,
      metadata: run.metadata,
    };
  }

  private runtimeContext(agent: AgentRecord, project: ProjectRecord): AgentRuntimeContext {
    return {
      mode: agent.mode,
      workingDirectory: project.working_directory,
    };
  }

  private assertPolicy(message: string, allowed: boolean): void {
    const decision = evaluatePolicy(message, allowed);
    if (!decision.allowed) {
      throw new BridgeError("BLOCKED_BY_POLICY", decision.reason ?? "Action blocked", {
        matched_rule: decision.matched_rule,
        requires_explicit_authorization: true,
      });
    }
  }

  private assertProjectMatches(
    project: ProjectRecord,
    repository: string,
    workingDirectory: string,
  ): void {
    if (
      project.repository !== repository ||
      path.resolve(project.working_directory) !== path.resolve(workingDirectory)
    ) {
      throw new BridgeError("INVALID_INPUT", "Project details do not match registered project", {
        project: project.name,
      });
    }
  }

  private assertLocalDirectory(workingDirectory: string): void {
    if (!fs.existsSync(workingDirectory) || !fs.statSync(workingDirectory).isDirectory()) {
      throw new BridgeError("INVALID_INPUT", "Local working directory does not exist", {
        working_directory: workingDirectory,
      });
    }
  }

  private requireProjectByName(name: string): ProjectRecord {
    const project = this.store.getProjectByName(name);
    if (!project) {
      throw new BridgeError("PROJECT_NOT_FOUND", "Registered project not found", { project: name }, 404);
    }
    return project;
  }

  private requireProjectById(id: string): ProjectRecord {
    const project = this.store.getProjectById(id);
    if (!project) {
      throw new BridgeError("PROJECT_NOT_FOUND", "Registered project not found", {}, 404);
    }
    return project;
  }

  private requireAgent(agentId: string): AgentRecord {
    const agent = this.store.getAgent(agentId);
    if (!agent) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", { agent_id: agentId }, 404);
    }
    return agent;
  }

  private requireRun(runId: string): RunRecord {
    const run = this.store.getRun(runId);
    if (!run) {
      throw new BridgeError("RUN_NOT_FOUND", "Cursor run not found", { run_id: runId }, 404);
    }
    return run;
  }

  private asCursorError(error: unknown): BridgeError {
    if (error instanceof BridgeError) return error;
    const reason = error instanceof Error ? error.message : "Unknown provider error";
    return new BridgeError("CURSOR_API_ERROR", "Cursor provider request failed", { reason }, 502);
  }
}
