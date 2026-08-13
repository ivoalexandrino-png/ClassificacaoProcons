import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { BridgeError } from "../errors.js";
import type {
  AgentRecord,
  CreateMessageInput,
  CreateProjectInput,
  CreateRunInput,
  MessageRecord,
  ProjectRecord,
  RunRecord,
  RunStatus,
  UpsertAgentInput,
} from "./types.js";

function nowIso(): string {
  return new Date().toISOString();
}

function parseJsonObject(raw: string | null | undefined): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return {};
  } catch {
    return {};
  }
}

export class BridgeStore {
  private readonly db: DatabaseSync;

  constructor(databasePath: string) {
    const dir = path.dirname(databasePath);
    mkdirSync(dir, { recursive: true });
    this.db = new DatabaseSync(databasePath);
    this.db.exec("PRAGMA journal_mode = WAL;");
    this.db.exec("PRAGMA foreign_keys = ON;");
    this.migrate();
  }

  healthCheck(): { ok: true } | { ok: false; error: string } {
    try {
      this.db.prepare("SELECT 1 AS ok").get();
      return { ok: true };
    } catch (error) {
      return {
        ok: false,
        error: error instanceof Error ? error.message : "database error",
      };
    }
  }

  close(): void {
    this.db.close();
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        repository TEXT NOT NULL,
        working_directory TEXT NOT NULL,
        default_branch TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        mode TEXT NOT NULL,
        branch TEXT,
        status TEXT NOT NULL,
        working_directory TEXT,
        repository TEXT,
        created_at TEXT NOT NULL,
        last_activity_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
      );

      CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        prompt TEXT NOT NULL,
        response TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        error TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
      );

      CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
        run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
      );

      CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);
      CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id, started_at DESC);
      CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id, created_at DESC);
    `);
  }

  createProject(input: CreateProjectInput): ProjectRecord {
    const existing = this.getProjectByName(input.name);
    if (existing) {
      throw new BridgeError("VALIDATION_ERROR", `Project already exists: ${input.name}`, {
        project_id: existing.id,
      });
    }

    const createdAt = nowIso();
    const record: ProjectRecord = {
      id: randomUUID(),
      name: input.name,
      repository: input.repository,
      workingDirectory: input.workingDirectory,
      defaultBranch: input.defaultBranch ?? "main",
      createdAt,
      updatedAt: createdAt,
    };

    this.db
      .prepare(
        `INSERT INTO projects
         (id, name, repository, working_directory, default_branch, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        record.id,
        record.name,
        record.repository,
        record.workingDirectory,
        record.defaultBranch,
        record.createdAt,
        record.updatedAt,
      );

    return record;
  }

  listProjects(): ProjectRecord[] {
    const rows = this.db
      .prepare(
        `SELECT id, name, repository, working_directory, default_branch, created_at, updated_at
         FROM projects ORDER BY name ASC`,
      )
      .all() as Array<Record<string, unknown>>;
    return rows.map((row) => this.mapProject(row));
  }

  getProjectById(id: string): ProjectRecord | null {
    const row = this.db
      .prepare(
        `SELECT id, name, repository, working_directory, default_branch, created_at, updated_at
         FROM projects WHERE id = ?`,
      )
      .get(id) as Record<string, unknown> | undefined;
    return row ? this.mapProject(row) : null;
  }

  getProjectByName(name: string): ProjectRecord | null {
    const row = this.db
      .prepare(
        `SELECT id, name, repository, working_directory, default_branch, created_at, updated_at
         FROM projects WHERE lower(name) = lower(?)`,
      )
      .get(name) as Record<string, unknown> | undefined;
    return row ? this.mapProject(row) : null;
  }

  requireProjectByName(name: string): ProjectRecord {
    const project = this.getProjectByName(name);
    if (!project) {
      throw new BridgeError("PROJECT_NOT_FOUND", `Project not found: ${name}`, {
        name,
      });
    }
    return project;
  }

  upsertAgent(input: UpsertAgentInput): AgentRecord {
    const existing = this.getAgent(input.agentId);
    const ts = nowIso();

    if (!existing) {
      const record: AgentRecord = {
        agentId: input.agentId,
        projectId: input.projectId ?? null,
        mode: input.mode,
        branch: input.branch ?? null,
        status: input.status ?? "idle",
        workingDirectory: input.workingDirectory ?? null,
        repository: input.repository ?? null,
        createdAt: ts,
        lastActivityAt: ts,
        metadata: input.metadata ?? {},
      };
      this.db
        .prepare(
          `INSERT INTO agents
           (agent_id, project_id, mode, branch, status, working_directory, repository,
            created_at, last_activity_at, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .run(
          record.agentId,
          record.projectId,
          record.mode,
          record.branch,
          record.status,
          record.workingDirectory,
          record.repository,
          record.createdAt,
          record.lastActivityAt,
          JSON.stringify(record.metadata),
        );
      return record;
    }

    const record: AgentRecord = {
      agentId: existing.agentId,
      projectId: input.projectId !== undefined ? input.projectId : existing.projectId,
      mode: input.mode ?? existing.mode,
      branch: input.branch !== undefined ? input.branch : existing.branch,
      status: input.status ?? existing.status,
      workingDirectory:
        input.workingDirectory !== undefined
          ? input.workingDirectory
          : existing.workingDirectory,
      repository:
        input.repository !== undefined ? input.repository : existing.repository,
      createdAt: existing.createdAt,
      lastActivityAt: ts,
      metadata: input.metadata
        ? { ...existing.metadata, ...input.metadata }
        : existing.metadata,
    };

    this.db
      .prepare(
        `UPDATE agents SET
           project_id = ?, mode = ?, branch = ?, status = ?, working_directory = ?,
           repository = ?, last_activity_at = ?, metadata = ?
         WHERE agent_id = ?`,
      )
      .run(
        record.projectId,
        record.mode,
        record.branch,
        record.status,
        record.workingDirectory,
        record.repository,
        record.lastActivityAt,
        JSON.stringify(record.metadata),
        record.agentId,
      );

    return record;
  }

  listAgents(): AgentRecord[] {
    const rows = this.db
      .prepare(
        `SELECT agent_id, project_id, mode, branch, status, working_directory, repository,
                created_at, last_activity_at, metadata
         FROM agents
         ORDER BY last_activity_at DESC`,
      )
      .all() as Array<Record<string, unknown>>;
    return rows.map((row) => this.mapAgent(row));
  }

  getAgent(agentId: string): AgentRecord | null {
    const row = this.db
      .prepare(
        `SELECT agent_id, project_id, mode, branch, status, working_directory, repository,
                created_at, last_activity_at, metadata
         FROM agents WHERE agent_id = ?`,
      )
      .get(agentId) as Record<string, unknown> | undefined;
    return row ? this.mapAgent(row) : null;
  }

  requireAgent(agentId: string): AgentRecord {
    const agent = this.getAgent(agentId);
    if (!agent) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
        agent_id: agentId,
      });
    }
    return agent;
  }

  touchAgent(agentId: string, status?: string): void {
    const ts = nowIso();
    if (status) {
      this.db
        .prepare(
          `UPDATE agents SET last_activity_at = ?, status = ? WHERE agent_id = ?`,
        )
        .run(ts, status, agentId);
      return;
    }
    this.db
      .prepare(`UPDATE agents SET last_activity_at = ? WHERE agent_id = ?`)
      .run(ts, agentId);
  }

  createRun(input: CreateRunInput): RunRecord {
    const record: RunRecord = {
      runId: input.runId,
      agentId: input.agentId,
      status: input.status,
      prompt: input.prompt,
      response: null,
      startedAt: nowIso(),
      completedAt: null,
      error: null,
      metadata: input.metadata ?? {},
    };

    this.db
      .prepare(
        `INSERT INTO runs
         (run_id, agent_id, status, prompt, response, started_at, completed_at, error, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        record.runId,
        record.agentId,
        record.status,
        record.prompt,
        record.response,
        record.startedAt,
        record.completedAt,
        record.error,
        JSON.stringify(record.metadata),
      );

    this.touchAgent(input.agentId, "running");
    return record;
  }

  updateRun(
    runId: string,
    patch: {
      status?: RunStatus;
      response?: string | null;
      error?: string | null;
      completedAt?: string | null;
      metadata?: Record<string, unknown>;
    },
  ): RunRecord {
    const existing = this.requireRun(runId);
    const next: RunRecord = {
      ...existing,
      status: patch.status ?? existing.status,
      response: patch.response !== undefined ? patch.response : existing.response,
      error: patch.error !== undefined ? patch.error : existing.error,
      completedAt:
        patch.completedAt !== undefined ? patch.completedAt : existing.completedAt,
      metadata: patch.metadata
        ? { ...existing.metadata, ...patch.metadata }
        : existing.metadata,
    };

    this.db
      .prepare(
        `UPDATE runs SET status = ?, response = ?, error = ?, completed_at = ?, metadata = ?
         WHERE run_id = ?`,
      )
      .run(
        next.status,
        next.response,
        next.error,
        next.completedAt,
        JSON.stringify(next.metadata),
        next.runId,
      );

    if (
      next.status === "completed" ||
      next.status === "error" ||
      next.status === "cancelled" ||
      next.status === "timeout"
    ) {
      this.touchAgent(next.agentId, next.status);
    }

    return next;
  }

  getRun(runId: string): RunRecord | null {
    const row = this.db
      .prepare(
        `SELECT run_id, agent_id, status, prompt, response, started_at, completed_at, error, metadata
         FROM runs WHERE run_id = ?`,
      )
      .get(runId) as Record<string, unknown> | undefined;
    return row ? this.mapRun(row) : null;
  }

  requireRun(runId: string): RunRecord {
    const run = this.getRun(runId);
    if (!run) {
      throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: runId });
    }
    return run;
  }

  getActiveRunForAgent(agentId: string): RunRecord | null {
    const row = this.db
      .prepare(
        `SELECT run_id, agent_id, status, prompt, response, started_at, completed_at, error, metadata
         FROM runs
         WHERE agent_id = ? AND status IN ('queued', 'running')
         ORDER BY started_at DESC
         LIMIT 1`,
      )
      .get(agentId) as Record<string, unknown> | undefined;
    return row ? this.mapRun(row) : null;
  }

  addMessage(input: CreateMessageInput): MessageRecord {
    const record: MessageRecord = {
      id: randomUUID(),
      agentId: input.agentId,
      runId: input.runId ?? null,
      role: input.role,
      content: input.content,
      createdAt: nowIso(),
      metadata: input.metadata ?? {},
    };

    this.db
      .prepare(
        `INSERT INTO messages
         (id, agent_id, run_id, role, content, created_at, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        record.id,
        record.agentId,
        record.runId,
        record.role,
        record.content,
        record.createdAt,
        JSON.stringify(record.metadata),
      );

    this.touchAgent(input.agentId);
    return record;
  }

  getConversation(agentId: string, limit = 20): MessageRecord[] {
    const safeLimit = Math.max(1, Math.min(limit, 200));
    const rows = this.db
      .prepare(
        `SELECT id, agent_id, run_id, role, content, created_at, metadata
         FROM messages
         WHERE agent_id = ?
         ORDER BY created_at DESC, rowid DESC
         LIMIT ?`,
      )
      .all(agentId, safeLimit) as Array<Record<string, unknown>>;

    return rows.map((row) => this.mapMessage(row)).reverse();
  }

  private mapProject(row: Record<string, unknown>): ProjectRecord {
    return {
      id: String(row.id),
      name: String(row.name),
      repository: String(row.repository),
      workingDirectory: String(row.working_directory),
      defaultBranch: String(row.default_branch),
      createdAt: String(row.created_at),
      updatedAt: String(row.updated_at),
    };
  }

  private mapAgent(row: Record<string, unknown>): AgentRecord {
    return {
      agentId: String(row.agent_id),
      projectId: row.project_id == null ? null : String(row.project_id),
      mode: row.mode === "cloud" ? "cloud" : "local",
      branch: row.branch == null ? null : String(row.branch),
      status: String(row.status),
      workingDirectory:
        row.working_directory == null ? null : String(row.working_directory),
      repository: row.repository == null ? null : String(row.repository),
      createdAt: String(row.created_at),
      lastActivityAt: String(row.last_activity_at),
      metadata: parseJsonObject(
        typeof row.metadata === "string" ? row.metadata : undefined,
      ),
    };
  }

  private mapRun(row: Record<string, unknown>): RunRecord {
    return {
      runId: String(row.run_id),
      agentId: String(row.agent_id),
      status: String(row.status) as RunStatus,
      prompt: String(row.prompt),
      response: row.response == null ? null : String(row.response),
      startedAt: String(row.started_at),
      completedAt: row.completed_at == null ? null : String(row.completed_at),
      error: row.error == null ? null : String(row.error),
      metadata: parseJsonObject(
        typeof row.metadata === "string" ? row.metadata : undefined,
      ),
    };
  }

  private mapMessage(row: Record<string, unknown>): MessageRecord {
    return {
      id: String(row.id),
      agentId: String(row.agent_id),
      runId: row.run_id == null ? null : String(row.run_id),
      role: String(row.role) as MessageRecord["role"],
      content: String(row.content),
      createdAt: String(row.created_at),
      metadata: parseJsonObject(
        typeof row.metadata === "string" ? row.metadata : undefined,
      ),
    };
  }
}
