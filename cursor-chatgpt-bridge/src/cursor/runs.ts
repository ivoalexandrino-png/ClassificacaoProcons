import { BridgeError } from "../mcp/errors.js";
import type { Logger } from "../logger.js";
import { evaluateMessagePolicy } from "../security/policy.js";
import type { BridgeStore } from "../storage/store.js";
import type { AgentRow, RunStatus } from "../storage/types.js";
import type { AgentService } from "./agents.js";
import { getLocalGitChanges } from "./git.js";
import type { AgentContext, CursorAgentProvider, ProviderRunStatus } from "./types.js";

const PROVIDER_STATUS_MAP: Record<ProviderRunStatus, RunStatus> = {
  creating: "creating",
  running: "running",
  completed: "completed",
  error: "error",
  cancelled: "cancelled",
};

export interface SendFollowupInput {
  agentId: string;
  message: string;
  waitForCompletion: boolean;
  allowDangerousActions: boolean;
}

export type SendFollowupResult =
  | {
      status: "busy";
      active_run_id: string | null;
    }
  | {
      status: "blocked_by_policy";
      reason: string;
      requires_explicit_authorization: true;
    }
  | {
      agent_id: string;
      run_id: string;
      status: RunStatus;
      response: string | null;
      started_at: string;
      completed_at: string | null;
    };

export interface PublicRun {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  response: string | null;
  started_at: string;
  completed_at: string | null;
  error: unknown;
}

export interface CancelRunResultPublic {
  supported: boolean;
  reason?: string;
  run_id?: string;
  status?: RunStatus;
}

export interface GetChangesInput {
  agentId: string;
  maxDiffChars: number;
}

/**
 * Orchestrates follow-ups, run status, cancellation, and change inspection.
 * Owns the per-agent "one active run at a time" lock described in the spec.
 */
export class RunService {
  /** In-process lock so two concurrent calls for the same agent can't both pass the busy check. */
  private readonly locked = new Set<string>();

  constructor(
    private readonly store: BridgeStore,
    private readonly provider: CursorAgentProvider,
    private readonly agents: AgentService,
    private readonly logger: Logger,
    private readonly runTimeoutMs: number,
  ) {}

  private toPublicRun(runId: string): PublicRun {
    const row = this.store.getRun(runId);
    if (!row) {
      throw new BridgeError("RUN_NOT_FOUND", `No run known to the bridge with id "${runId}".`);
    }
    return {
      run_id: row.run_id,
      agent_id: row.agent_id,
      status: row.status,
      response: row.response,
      started_at: row.started_at,
      completed_at: row.completed_at,
      error: row.error ? JSON.parse(row.error) : null,
    };
  }

  async sendFollowup(input: SendFollowupInput): Promise<SendFollowupResult> {
    const { row } = this.agents.contextFor(input.agentId);

    const activeRun = this.store.getActiveRun(input.agentId);
    if (activeRun || this.locked.has(input.agentId)) {
      return { status: "busy", active_run_id: activeRun?.run_id ?? null };
    }

    const policy = evaluateMessagePolicy(input.message, input.allowDangerousActions);
    if (policy.blocked) {
      this.store.createMessage({
        agentId: input.agentId,
        role: "system",
        content: `Follow-up blocked by policy: ${policy.reason}`,
        metadata: { matches: policy.matches },
      });
      this.logger.warn({
        event: "cursor_followup_blocked",
        agent_id: input.agentId,
        matched_patterns: policy.matches.map((match) => match.label),
      });
      return {
        status: "blocked_by_policy",
        reason: policy.reason ?? "Message matched a dangerous-action policy pattern.",
        requires_explicit_authorization: true,
      };
    }

    this.locked.add(input.agentId);
    try {
      return await this.runFollowup(row, input);
    } finally {
      this.locked.delete(input.agentId);
    }
  }

  private async runFollowup(
    row: AgentRow,
    input: SendFollowupInput,
  ): Promise<SendFollowupResult> {
    const context: AgentContext = {
      agentId: row.agent_id,
      mode: row.mode,
      workingDirectory: row.working_directory ?? undefined,
      repository: row.repository ?? undefined,
      branch: row.branch ?? undefined,
    };

    let sendResult;
    try {
      sendResult = await this.provider.sendMessage(context, input.message);
    } catch (error) {
      if (error instanceof BridgeError && error.code === "AGENT_BUSY") {
        const active = this.store.getActiveRun(input.agentId);
        return { status: "busy", active_run_id: active?.run_id ?? null };
      }
      throw error;
    }

    const startedStatus = PROVIDER_STATUS_MAP[sendResult.run.status];
    this.store.createRun({
      runId: sendResult.runId,
      agentId: row.agent_id,
      status: startedStatus,
      prompt: input.message,
    });
    this.store.createMessage({
      agentId: row.agent_id,
      runId: sendResult.runId,
      role: "user",
      content: input.message,
    });
    this.store.setAgentActiveRun(row.agent_id, sendResult.runId);
    this.store.touchAgent(row.agent_id, startedStatus);

    const startedAt = this.store.getRun(sendResult.runId)!.started_at;

    if (!input.waitForCompletion) {
      return {
        agent_id: row.agent_id,
        run_id: sendResult.runId,
        status: startedStatus,
        response: null,
        started_at: startedAt,
        completed_at: null,
      };
    }

    const before = Date.now();
    const { run, timedOut } = await this.provider.waitForRun(
      context,
      sendResult.runId,
      this.runTimeoutMs,
    );
    const durationMs = Date.now() - before;

    if (timedOut) {
      this.store.updateRun(sendResult.runId, { status: "timeout" });
      this.logger.warn({
        event: "cursor_run_timeout",
        agent_id: row.agent_id,
        run_id: sendResult.runId,
        duration_ms: durationMs,
      });
      // Do not clear active_run_id: the run may still be executing upstream.
      return {
        agent_id: row.agent_id,
        run_id: sendResult.runId,
        status: "timeout",
        response: null,
        started_at: startedAt,
        completed_at: null,
      };
    }

    const finalStatus = PROVIDER_STATUS_MAP[run.status];
    const completedAt = new Date().toISOString();
    this.store.updateRun(sendResult.runId, {
      status: finalStatus,
      response: run.result ?? null,
      completedAt,
      error: run.error ? JSON.stringify(run.error) : null,
    });
    await this.recordConversationEvents(row.agent_id, context, sendResult.runId, run.result);
    this.store.setAgentActiveRun(row.agent_id, null);
    this.store.touchAgent(row.agent_id, finalStatus);

    this.logger.info({
      event: "cursor_run_completed",
      agent_id: row.agent_id,
      run_id: sendResult.runId,
      status: finalStatus,
      duration_ms: durationMs,
    });

    return {
      agent_id: row.agent_id,
      run_id: sendResult.runId,
      status: finalStatus,
      response: run.result ?? null,
      started_at: startedAt,
      completed_at: completedAt,
    };
  }

  /**
   * Persists the finished run's structured transcript (tool calls +
   * assistant text) so `cursor_get_conversation` can show more than just the
   * final result. Falls back to a single assistant message with the plain
   * result text when the provider can't supply structured events.
   */
  private async recordConversationEvents(
    agentId: string,
    context: AgentContext,
    runId: string,
    fallbackResult: string | undefined,
  ): Promise<void> {
    const events = await this.provider.getConversationEvents(context, runId);
    if (events.length > 0) {
      for (const event of events) {
        this.store.createMessage({ agentId, runId, role: event.role, content: event.content });
      }
      return;
    }
    if (fallbackResult) {
      this.store.createMessage({ agentId, runId, role: "assistant", content: fallbackResult });
    }
  }

  async getRun(runId: string): Promise<PublicRun> {
    const row = this.store.getRun(runId);
    if (!row) {
      throw new BridgeError("RUN_NOT_FOUND", `No run known to the bridge with id "${runId}".`);
    }
    const terminal: RunStatus[] = ["completed", "error", "cancelled"];
    if (terminal.includes(row.status)) {
      return this.toPublicRun(runId);
    }

    const { context } = this.agents.contextFor(row.agent_id);
    const run = await this.provider.getRun(context, runId);
    const status = PROVIDER_STATUS_MAP[run.status];
    this.store.updateRun(runId, {
      status,
      response: run.result ?? row.response,
      completedAt:
        status === "completed" || status === "error" || status === "cancelled"
          ? new Date().toISOString()
          : row.completed_at,
      error: run.error ? JSON.stringify(run.error) : row.error,
    });
    if (status !== row.status && (status === "completed" || status === "error" || status === "cancelled")) {
      this.store.setAgentActiveRun(row.agent_id, null);
      this.store.touchAgent(row.agent_id, status);
    }
    return this.toPublicRun(runId);
  }

  async cancelRun(runId: string): Promise<CancelRunResultPublic> {
    const row = this.store.getRun(runId);
    if (!row) {
      throw new BridgeError("RUN_NOT_FOUND", `No run known to the bridge with id "${runId}".`);
    }
    const { context } = this.agents.contextFor(row.agent_id);
    const result = await this.provider.cancelRun(context, runId);

    if (!result.supported) {
      this.logger.info({
        event: "cursor_run_cancel_unsupported",
        agent_id: row.agent_id,
        run_id: runId,
        reason: result.reason,
      });
      return { supported: false, reason: result.reason };
    }

    const status = result.run ? PROVIDER_STATUS_MAP[result.run.status] : "cancelled";
    this.store.updateRun(runId, {
      status,
      response: result.run?.result ?? row.response,
      completedAt: new Date().toISOString(),
    });
    this.store.setAgentActiveRun(row.agent_id, null);
    this.store.touchAgent(row.agent_id, status);
    this.logger.info({ event: "cursor_run_cancelled", agent_id: row.agent_id, run_id: runId });
    return { supported: true, run_id: runId, status };
  }

  async getChanges(input: GetChangesInput) {
    const { row } = this.agents.contextFor(input.agentId);

    if (row.mode === "local") {
      if (!row.working_directory) {
        throw new BridgeError(
          "VALIDATION_ERROR",
          "Local agent has no working_directory on record; cannot inspect changes.",
        );
      }
      const changes = await getLocalGitChanges(row.working_directory, input.maxDiffChars);
      return {
        mode: "local" as const,
        branch: changes.branch ?? row.branch,
        clean: changes.clean,
        files: changes.files,
        diff_stat: changes.diff_stat,
        diff: changes.diff,
        diff_truncated: changes.diff_truncated,
        recent_commits: changes.recent_commits,
        error: changes.error,
      };
    }

    const runId = row.active_run_id ?? this.store.listRunsByAgent(row.agent_id, 1)[0]?.run_id;
    if (!runId) {
      return {
        mode: "cloud" as const,
        branch: row.branch,
        clean: true,
        files: [],
        diff_stat: "",
        diff: "",
        diff_truncated: false,
        recent_commits: [],
        note: "No runs recorded for this cloud agent yet.",
      };
    }

    const context: AgentContext = {
      agentId: row.agent_id,
      mode: row.mode,
      workingDirectory: row.working_directory ?? undefined,
      repository: row.repository ?? undefined,
      branch: row.branch ?? undefined,
    };
    const run = await this.provider.getRun(context, runId);
    const branches = run.git?.branches ?? [];
    return {
      mode: "cloud" as const,
      branch: branches[0]?.branch ?? row.branch,
      pull_request: branches[0]?.prUrl ?? null,
      pushed_branches: branches,
      note:
        "Cloud agents run in an isolated VM; the SDK doesn't expose file-level diff/status. Branch and PR links reflect what the agent has pushed. For a full diff, inspect the branch/PR in your Git host, or run this agent in mode=local.",
    };
  }
}
