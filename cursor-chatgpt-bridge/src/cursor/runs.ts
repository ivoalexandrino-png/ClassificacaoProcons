import { randomUUID } from "node:crypto";
import { BridgeError } from "../errors.js";
import type { Logger } from "../logger.js";
import type { BridgeStore } from "../storage/store.js";
import { evaluateDangerousAction } from "../security/policy.js";
import type { CursorSdkProvider } from "./client.js";
import type { RunDetails } from "./types.js";

export class RunService {
  private readonly locks = new Set<string>();

  constructor(
    private readonly store: BridgeStore,
    private readonly cursor: CursorSdkProvider,
    private readonly logger: Logger,
    private readonly runTimeoutMs: number,
  ) {}

  private acquireLock(agentId: string): void {
    if (this.locks.has(agentId)) {
      const active = this.store.getActiveRunForAgent(agentId);
      throw new BridgeError("AGENT_BUSY", "Agent already has an active run", {
        active_run_id: active?.run_id,
      });
    }
    this.locks.add(agentId);
  }

  private releaseLock(agentId: string): void {
    this.locks.delete(agentId);
  }

  isAgentBusy(agentId: string): boolean {
    return this.locks.has(agentId) || Boolean(this.store.getActiveRunForAgent(agentId));
  }

  async sendFollowup(input: {
    agent_id: string;
    message: string;
    wait_for_completion?: boolean;
    allow_dangerous_actions?: boolean;
    working_directory?: string;
  }): Promise<Record<string, unknown>> {
    const agent = this.store.getAgent(input.agent_id);
    if (!agent) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
        agent_id: input.agent_id,
      });
    }

    const policy = evaluateDangerousAction(
      input.message,
      input.allow_dangerous_actions ?? false,
    );
    if (!policy.allowed) {
      return {
        agent_id: input.agent_id,
        status: "blocked_by_policy",
        reason: policy.reason,
        requires_explicit_authorization: policy.requiresExplicitAuthorization ?? true,
      };
    }

    if (this.isAgentBusy(input.agent_id)) {
      const active = this.store.getActiveRunForAgent(input.agent_id);
      return {
        agent_id: input.agent_id,
        status: "busy",
        active_run_id: active?.run_id,
      };
    }

    this.acquireLock(input.agent_id);
    const startedAt = new Date().toISOString();
    const localRunId = randomUUID();
    const waitForCompletion = input.wait_for_completion ?? true;
    const workingDirectory =
      input.working_directory ?? agent.working_directory ?? undefined;

    this.store.createRun({
      run_id: localRunId,
      agent_id: input.agent_id,
      status: "running",
      prompt: input.message,
    });
    this.store.addMessage({
      agent_id: input.agent_id,
      run_id: localRunId,
      role: "user",
      content: input.message,
    });

    try {
      const sdkResult = await this.cursor.sendMessage({
        agentId: input.agent_id,
        message: input.message,
        workingDirectory,
        timeoutMs: this.runTimeoutMs,
        waitForCompletion,
      });

      if (!waitForCompletion) {
        void this.finalizeRunLater(
          input.agent_id,
          localRunId,
          sdkResult.run_id,
          workingDirectory,
        );

        return {
          agent_id: input.agent_id,
          run_id: sdkResult.run_id,
          status: "running",
          started_at: startedAt,
        };
      }

      this.store.updateRun(localRunId, {
        status: sdkResult.status,
        response: sdkResult.response,
        completed_at: sdkResult.completed_at ?? new Date().toISOString(),
        error: sdkResult.error,
      });

      if (sdkResult.response) {
        this.store.addMessage({
          agent_id: input.agent_id,
          run_id: localRunId,
          role: "assistant",
          content: sdkResult.response,
        });
      }

      this.store.upsertAgent({
        agent_id: input.agent_id,
        mode: agent.mode,
        status: sdkResult.status,
        project_id: agent.project_id,
        branch: agent.branch,
        working_directory: agent.working_directory,
        repository: agent.repository,
      });

      const durationMs = Date.now() - Date.parse(startedAt);
      this.logger.info("cursor_run_completed", {
        agent_id: input.agent_id,
        run_id: sdkResult.run_id,
        duration_ms: durationMs,
        status: sdkResult.status,
      });

      return {
        agent_id: input.agent_id,
        run_id: sdkResult.run_id,
        status: sdkResult.status,
        response: sdkResult.response,
        started_at: startedAt,
        completed_at: sdkResult.completed_at,
        error: sdkResult.error,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.store.updateRun(localRunId, {
        status: "error",
        error: message,
        completed_at: new Date().toISOString(),
      });
      throw error;
    } finally {
      if (waitForCompletion) {
        this.releaseLock(input.agent_id);
      }
    }
  }

  private async finalizeRunLater(
    agentId: string,
    localRunId: string,
    sdkRunId: string,
    workingDirectory?: string,
  ): Promise<void> {
    try {
      const sdkResult = await this.cursor.waitForRunCompletion(
        agentId,
        sdkRunId,
        { workingDirectory, timeoutMs: this.runTimeoutMs },
      );

      this.store.updateRun(localRunId, {
        status: sdkResult.status,
        response: sdkResult.response,
        completed_at: sdkResult.completed_at ?? new Date().toISOString(),
        error: sdkResult.error,
      });

      if (sdkResult.response) {
        this.store.addMessage({
          agent_id: agentId,
          run_id: localRunId,
          role: "assistant",
          content: sdkResult.response,
        });
      }

      const agent = this.store.getAgent(agentId);
      if (agent) {
        this.store.upsertAgent({
          agent_id: agentId,
          mode: agent.mode,
          status: sdkResult.status,
          project_id: agent.project_id,
          branch: agent.branch,
          working_directory: agent.working_directory,
          repository: agent.repository,
        });
      }

      this.logger.info("cursor_run_completed", {
        agent_id: agentId,
        run_id: sdkRunId,
        status: sdkResult.status,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.store.updateRun(localRunId, {
        status: "error",
        error: message,
        completed_at: new Date().toISOString(),
      });
      this.logger.error("cursor_run_failed", { agent_id: agentId, run_id: sdkRunId, error: message });
    } finally {
      this.releaseLock(agentId);
    }
  }

  getRun(runId: string): RunDetails | undefined {
    const run = this.store.getRun(runId);
    if (!run) {
      return undefined;
    }
    return {
      run_id: run.run_id,
      agent_id: run.agent_id,
      status: run.status as RunDetails["status"],
      response: run.response ?? undefined,
      started_at: run.started_at,
      completed_at: run.completed_at ?? undefined,
      error: run.error,
    };
  }

  async cancelRun(runId: string): Promise<Record<string, unknown>> {
    const run = this.store.getRun(runId);
    if (!run) {
      throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: runId });
    }

    const agent = this.store.getAgent(run.agent_id);
    if (!agent) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
        agent_id: run.agent_id,
      });
    }

    const result = await this.cursor.cancelRun(run.agent_id, runId, {
      workingDirectory: agent.working_directory ?? undefined,
    });

    if (result.supported) {
      this.store.updateRun(runId, {
        status: "cancelled",
        completed_at: new Date().toISOString(),
      });
    }

    return { ...result } as Record<string, unknown>;
  }
}
