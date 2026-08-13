import { BridgeError } from "../errors.js";
import type { Logger } from "../logger.js";
import type { BridgeStore } from "../storage/store.js";
import type { CursorAgentProvider } from "./types.js";

export class RunService {
  constructor(
    private readonly store: BridgeStore,
    private readonly provider: CursorAgentProvider,
    private readonly logger: Logger,
  ) {}

  async getRun(runId: string) {
    const local = this.store.getRun(runId);
    if (!local) {
      throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: runId });
    }

    let remote = null;
    try {
      remote = await this.provider.getRun(runId, local.agentId);
    } catch (error) {
      this.logger.warn("cursor_get_run_remote_failed", {
        run_id: runId,
        message: error instanceof Error ? error.message : String(error),
      });
    }

    if (remote && remote.status !== "running" && local.status === "running") {
      this.store.updateRun(runId, {
        status:
          remote.status === "completed"
            ? "completed"
            : remote.status === "error"
              ? "error"
              : remote.status === "cancelled"
                ? "cancelled"
                : remote.status === "timeout"
                  ? "timeout"
                  : "running",
        response: remote.response ?? local.response,
        error: remote.error ?? local.error,
        completedAt: remote.completedAt ?? local.completedAt,
      });
    }

    const fresh = this.store.requireRun(runId);
    return {
      run_id: fresh.runId,
      agent_id: fresh.agentId,
      status: fresh.status,
      response: fresh.response,
      started_at: fresh.startedAt,
      completed_at: fresh.completedAt,
      error: fresh.error,
      remote_status: remote?.status ?? null,
    };
  }

  async cancelRun(runId: string) {
    const local = this.store.requireRun(runId);
    const result = await this.provider.cancelRun(runId, local.agentId);

    if (!result.supported) {
      return {
        supported: false as const,
        reason: result.reason,
        run_id: runId,
        agent_id: local.agentId,
      };
    }

    this.store.updateRun(runId, {
      status: "cancelled",
      completedAt: new Date().toISOString(),
      error: null,
    });
    this.store.addMessage({
      agentId: local.agentId,
      runId,
      role: "event",
      content: "Run cancelled via cursor_cancel_run",
      metadata: { event: "cancelled" },
    });

    this.logger.info("cursor_run_cancelled", {
      run_id: runId,
      agent_id: local.agentId,
    });

    return {
      supported: true as const,
      run_id: runId,
      agent_id: local.agentId,
      status: "cancelled" as const,
    };
  }
}
