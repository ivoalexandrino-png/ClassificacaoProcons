import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { BridgeError } from "../errors.js";
import type { Logger } from "../logger.js";
import type { BridgeStore } from "../storage/store.js";
import type { AgentRecord, ProjectRecord } from "../storage/types.js";
import type { CursorAgentProvider } from "./types.js";

const execFileAsync = promisify(execFile);

export interface ListedAgent {
  agent_id: string;
  project: string | null;
  repository: string | null;
  branch: string | null;
  status: string;
  last_activity_at: string;
  mode: string;
}

export class AgentService {
  private readonly locks = new Map<string, string>();

  constructor(
    private readonly store: BridgeStore,
    private readonly provider: CursorAgentProvider,
    private readonly logger: Logger,
    private readonly runTimeoutMs: number,
  ) {}

  listKnownAgents(): ListedAgent[] {
    return this.store.listAgents().map((agent) => {
      const project = agent.projectId
        ? this.store.getProjectById(agent.projectId)
        : null;
      return {
        agent_id: agent.agentId,
        project: project?.name ?? null,
        repository: agent.repository,
        branch: agent.branch,
        status: agent.status,
        last_activity_at: agent.lastActivityAt,
        mode: agent.mode,
      };
    });
  }

  getAgentDetails(agentId: string) {
    const local = this.store.requireAgent(agentId);
    const project = local.projectId
      ? this.store.getProjectById(local.projectId)
      : null;
    const activeRun = this.store.getActiveRunForAgent(agentId);

    return {
      agent_id: local.agentId,
      project: project?.name ?? null,
      repository: local.repository,
      branch: local.branch,
      working_directory: local.workingDirectory,
      status: local.status,
      last_activity_at: local.lastActivityAt,
      mode: local.mode,
      active_run_id: activeRun?.runId ?? null,
      metadata: local.metadata,
      capabilities: [
        "cursor_send_followup",
        "cursor_get_conversation",
        "cursor_get_run",
        "cursor_cancel_run",
        "cursor_get_changes",
      ],
    };
  }

  async startAgent(input: {
    project?: string;
    repository?: string;
    workingDirectory?: string;
    message: string;
    mode: "local" | "cloud";
  }) {
    let project: ProjectRecord | null = null;
    if (input.project) {
      project = this.store.requireProjectByName(input.project);
    }

    const repository = input.repository ?? project?.repository;
    const workingDirectory =
      input.workingDirectory ?? project?.workingDirectory;
    const startingRef = project?.defaultBranch ?? "main";

    if (input.mode === "local" && !workingDirectory) {
      throw new BridgeError(
        "VALIDATION_ERROR",
        "working_directory or registered project is required for local mode",
      );
    }
    if (input.mode === "cloud" && !repository) {
      throw new BridgeError(
        "VALIDATION_ERROR",
        "repository or registered project is required for cloud mode",
      );
    }

    this.logger.info("cursor_agent_create_started", {
      mode: input.mode,
      project: project?.name,
    });

    const created = await this.provider.createAgent({
      mode: input.mode,
      message: input.message,
      workingDirectory,
      repository,
      startingRef,
      projectName: project?.name,
      timeoutMs: this.runTimeoutMs,
    });

    const agent = this.store.upsertAgent({
      agentId: created.agentId,
      projectId: project?.id ?? null,
      mode: input.mode,
      branch: startingRef,
      status: created.run.status,
      workingDirectory: workingDirectory ?? null,
      repository: repository ?? null,
      metadata: { source: "cursor_start_agent" },
    });

    this.store.createRun({
      runId: created.run.runId,
      agentId: created.agentId,
      status:
        created.run.status === "completed"
          ? "completed"
          : created.run.status === "error"
            ? "error"
            : "running",
      prompt: input.message,
    });

    this.store.updateRun(created.run.runId, {
      status:
        created.run.status === "completed"
          ? "completed"
          : created.run.status === "error"
            ? "error"
            : created.run.status === "cancelled"
              ? "cancelled"
              : created.run.status === "timeout"
                ? "timeout"
                : "running",
      response: created.run.response ?? null,
      error: created.run.error ?? null,
      completedAt: created.run.completedAt ?? null,
    });

    this.store.addMessage({
      agentId: created.agentId,
      runId: created.run.runId,
      role: "user",
      content: input.message,
    });
    if (created.run.response) {
      this.store.addMessage({
        agentId: created.agentId,
        runId: created.run.runId,
        role: "assistant",
        content: created.run.response,
      });
    }

    this.logger.info("cursor_agent_create_completed", {
      agent_id: created.agentId,
      run_id: created.run.runId,
      status: created.run.status,
    });

    return {
      agent_id: agent.agentId,
      run_id: created.run.runId,
      status: created.run.status,
      response: created.run.response ?? null,
      started_at: created.run.startedAt ?? null,
      completed_at: created.run.completedAt ?? null,
      project: project?.name ?? null,
      mode: input.mode,
    };
  }

  async sendFollowUp(input: {
    agentId: string;
    message: string;
    waitForCompletion: boolean;
  }) {
    const agent = this.store.requireAgent(input.agentId);
    const active = this.store.getActiveRunForAgent(agent.agentId);
    if (active || this.locks.has(agent.agentId)) {
      return {
        status: "busy" as const,
        active_run_id: active?.runId ?? this.locks.get(agent.agentId) ?? null,
        agent_id: agent.agentId,
      };
    }

    const provisionalRunId = `pending-${crypto.randomUUID()}`;
    this.locks.set(agent.agentId, provisionalRunId);

    try {
      const started = Date.now();
      const result = await this.provider.resumeAndSend({
        agentId: agent.agentId,
        message: input.message,
        waitForCompletion: input.waitForCompletion,
        timeoutMs: this.runTimeoutMs,
      });

      // Replace provisional lock with real run id
      this.locks.set(agent.agentId, result.runId);

      this.store.createRun({
        runId: result.runId,
        agentId: agent.agentId,
        status: result.status === "running" ? "running" : "queued",
        prompt: input.message,
      });

      this.store.addMessage({
        agentId: agent.agentId,
        runId: result.runId,
        role: "user",
        content: input.message,
      });

      if (!input.waitForCompletion) {
        this.store.updateRun(result.runId, { status: "running" });
        this.store.touchAgent(agent.agentId, "running");
        return {
          agent_id: agent.agentId,
          run_id: result.runId,
          status: "running" as const,
          response: null,
          started_at: result.startedAt ?? new Date().toISOString(),
          completed_at: null,
        };
      }

      const mappedStatus =
        result.status === "completed"
          ? "completed"
          : result.status === "error"
            ? "error"
            : result.status === "cancelled"
              ? "cancelled"
              : result.status === "timeout"
                ? "timeout"
                : "running";

      this.store.updateRun(result.runId, {
        status: mappedStatus,
        response: result.response ?? null,
        error: result.error ?? null,
        completedAt: result.completedAt ?? new Date().toISOString(),
      });

      if (result.response) {
        this.store.addMessage({
          agentId: agent.agentId,
          runId: result.runId,
          role: "assistant",
          content: result.response,
        });
      }

      if (result.status === "timeout") {
        this.store.addMessage({
          agentId: agent.agentId,
          runId: result.runId,
          role: "event",
          content: "Run wait timed out; Cursor may still be executing.",
          metadata: { event: "timeout" },
        });
      }

      this.logger.info("cursor_run_completed", {
        agent_id: agent.agentId,
        run_id: result.runId,
        status: mappedStatus,
        duration_ms: Date.now() - started,
      });

      return {
        agent_id: agent.agentId,
        run_id: result.runId,
        status: mappedStatus,
        response: result.response ?? null,
        started_at: result.startedAt ?? null,
        completed_at: result.completedAt ?? null,
        error: result.error ?? null,
      };
    } finally {
      this.locks.delete(agent.agentId);
    }
  }

  getConversation(agentId: string, limit = 20) {
    this.store.requireAgent(agentId);
    const messages = this.store.getConversation(agentId, limit);
    return {
      agent_id: agentId,
      messages: messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        run_id: m.runId,
        created_at: m.createdAt,
        metadata: m.metadata,
      })),
    };
  }

  async getChanges(agentId: string, maxDiffChars = 30_000) {
    const agent = this.store.requireAgent(agentId);
    const safeMax = Math.max(1_000, Math.min(maxDiffChars, 200_000));

    if (agent.mode === "local" && agent.workingDirectory) {
      return this.getLocalChanges(agent, safeMax);
    }

    // Cloud: best-effort metadata from latest stored run / provider
    const providerAgent = await this.provider.getAgent(agentId).catch(() => null);
    return {
      branch: agent.branch,
      clean: null,
      files: [] as string[],
      diff_stat: null,
      diff: null,
      mode: agent.mode,
      note:
        "Full working-tree diffs are available for local agents. For cloud agents, inspect PR/branch metadata from runs or the Cursor UI.",
      provider: providerAgent,
      truncated: false,
    };
  }

  private async getLocalChanges(agent: AgentRecord, maxDiffChars: number) {
    const cwd = agent.workingDirectory!;
    const run = async (args: string[]) => {
      try {
        const { stdout } = await execFileAsync("git", args, {
          cwd,
          maxBuffer: 8 * 1024 * 1024,
        });
        return stdout.trimEnd();
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "git command failed";
        throw new BridgeError("INTERNAL_ERROR", message, { cwd, args });
      }
    };

    const branch = await run(["rev-parse", "--abbrev-ref", "HEAD"]);
    const statusPorcelain = await run(["status", "--porcelain"]);
    const files = statusPorcelain
      ? statusPorcelain
          .split("\n")
          .map((line) => line.slice(3).trim())
          .filter(Boolean)
      : [];
    const diffStat = await run(["diff", "--stat"]);
    let diff = await run(["diff"]);
    let truncated = false;
    if (diff.length > maxDiffChars) {
      diff = `${diff.slice(0, maxDiffChars)}\n\n… truncated …`;
      truncated = true;
    }
    const recentCommits = await run([
      "log",
      "-5",
      "--pretty=format:%h %ad %s",
      "--date=iso",
    ]);

    return {
      branch,
      clean: files.length === 0,
      files,
      diff_stat: diffStat,
      diff,
      git_status: statusPorcelain,
      recent_commits: recentCommits.split("\n").filter(Boolean),
      working_directory: cwd,
      truncated,
      mode: "local" as const,
    };
  }
}
