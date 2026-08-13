import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import Database from "better-sqlite3";

import type {
  AgentRow,
  CreateMessageInput,
  CreateProjectInput,
  CreateRunInput,
  MessageRow,
  ProjectRow,
  RunRow,
  Store,
  UpdateRunInput,
  UpsertAgentInput,
} from "./types.js";

interface RawAgentRow extends Omit<AgentRow, "metadata"> {
  metadata: string;
}

interface RawMessageRow extends Omit<MessageRow, "metadata"> {
  metadata: string;
}

/**
 * SQLite-backed persistence for projects, agents, runs and messages.
 *
 * Everything that flows through the bridge is recorded here so ChatGPT can
 * reconstruct a conversation and its results without copying anything by hand.
 * Pass `:memory:` as the path for tests.
 */
export class SqliteStore implements Store {
  private readonly db: Database.Database;

  constructor(databasePath: string) {
    if (databasePath !== ":memory:") {
      mkdirSync(dirname(databasePath), { recursive: true });
    }
    this.db = new Database(databasePath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("foreign_keys = ON");
    this.migrate();
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        repository TEXT,
        working_directory TEXT,
        default_branch TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        mode TEXT NOT NULL,
        branch TEXT,
        status TEXT,
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
        prompt TEXT,
        response TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        error TEXT
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

      CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id);
      CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
    `);
  }

  // ---- Projects ---------------------------------------------------------

  createProject(input: CreateProjectInput): ProjectRow {
    const now = nowIso();
    const existing = this.findProjectByName(input.name);
    if (existing) {
      this.db
        .prepare(
          `UPDATE projects
             SET repository = @repository,
                 working_directory = @workingDirectory,
                 default_branch = @defaultBranch,
                 updated_at = @now
           WHERE id = @id`,
        )
        .run({
          id: existing.id,
          repository: input.repository ?? existing.repository,
          workingDirectory: input.workingDirectory ?? existing.working_directory,
          defaultBranch: input.defaultBranch ?? existing.default_branch,
          now,
        });
      return this.getProject(existing.id)!;
    }

    const id = randomUUID();
    this.db
      .prepare(
        `INSERT INTO projects (id, name, repository, working_directory, default_branch, created_at, updated_at)
         VALUES (@id, @name, @repository, @workingDirectory, @defaultBranch, @now, @now)`,
      )
      .run({
        id,
        name: input.name,
        repository: input.repository ?? null,
        workingDirectory: input.workingDirectory ?? null,
        defaultBranch: input.defaultBranch ?? null,
        now,
      });
    return this.getProject(id)!;
  }

  listProjects(): ProjectRow[] {
    return this.db.prepare(`SELECT * FROM projects ORDER BY created_at DESC`).all() as ProjectRow[];
  }

  getProject(id: string): ProjectRow | null {
    return (this.db.prepare(`SELECT * FROM projects WHERE id = ?`).get(id) as ProjectRow) ?? null;
  }

  findProjectByName(name: string): ProjectRow | null {
    return (
      (this.db
        .prepare(`SELECT * FROM projects WHERE name = ? COLLATE NOCASE`)
        .get(name) as ProjectRow) ?? null
    );
  }

  findProjectByRepository(repository: string): ProjectRow | null {
    return (
      (this.db
        .prepare(`SELECT * FROM projects WHERE repository = ? COLLATE NOCASE`)
        .get(repository) as ProjectRow) ?? null
    );
  }

  // ---- Agents -----------------------------------------------------------

  upsertAgent(input: UpsertAgentInput): AgentRow {
    const now = nowIso();
    const existing = this.getAgent(input.agentId);
    const metadata = JSON.stringify(input.metadata ?? existing?.metadata ?? {});

    if (existing) {
      this.db
        .prepare(
          `UPDATE agents
              SET project_id = @projectId,
                  mode = @mode,
                  branch = @branch,
                  status = @status,
                  working_directory = @workingDirectory,
                  repository = @repository,
                  last_activity_at = @now,
                  metadata = @metadata
            WHERE agent_id = @agentId`,
        )
        .run({
          agentId: input.agentId,
          projectId: input.projectId ?? existing.project_id,
          mode: input.mode,
          branch: input.branch ?? existing.branch,
          status: input.status ?? existing.status,
          workingDirectory: input.workingDirectory ?? existing.working_directory,
          repository: input.repository ?? existing.repository,
          now,
          metadata,
        });
      return this.getAgent(input.agentId)!;
    }

    this.db
      .prepare(
        `INSERT INTO agents (agent_id, project_id, mode, branch, status, working_directory, repository, created_at, last_activity_at, metadata)
         VALUES (@agentId, @projectId, @mode, @branch, @status, @workingDirectory, @repository, @now, @now, @metadata)`,
      )
      .run({
        agentId: input.agentId,
        projectId: input.projectId ?? null,
        mode: input.mode,
        branch: input.branch ?? null,
        status: input.status ?? null,
        workingDirectory: input.workingDirectory ?? null,
        repository: input.repository ?? null,
        now,
        metadata,
      });
    return this.getAgent(input.agentId)!;
  }

  listAgents(): AgentRow[] {
    const rows = this.db
      .prepare(`SELECT * FROM agents ORDER BY last_activity_at DESC`)
      .all() as RawAgentRow[];
    return rows.map(deserializeAgent);
  }

  getAgent(agentId: string): AgentRow | null {
    const row = this.db.prepare(`SELECT * FROM agents WHERE agent_id = ?`).get(agentId) as
      | RawAgentRow
      | undefined;
    return row ? deserializeAgent(row) : null;
  }

  touchAgent(agentId: string, status?: string | null): void {
    this.db
      .prepare(
        `UPDATE agents
            SET last_activity_at = @now,
                status = COALESCE(@status, status)
          WHERE agent_id = @agentId`,
      )
      .run({ agentId, now: nowIso(), status: status ?? null });
  }

  // ---- Runs -------------------------------------------------------------

  createRun(input: CreateRunInput): RunRow {
    this.db
      .prepare(
        `INSERT INTO runs (run_id, agent_id, status, prompt, response, started_at, completed_at, error)
         VALUES (@runId, @agentId, @status, @prompt, NULL, @startedAt, NULL, NULL)`,
      )
      .run({
        runId: input.runId,
        agentId: input.agentId,
        status: input.status,
        prompt: input.prompt ?? null,
        startedAt: input.startedAt ?? nowIso(),
      });
    return this.getRun(input.runId)!;
  }

  updateRun(runId: string, patch: UpdateRunInput): RunRow | null {
    const existing = this.getRun(runId);
    if (!existing) return null;
    this.db
      .prepare(
        `UPDATE runs
            SET status = @status,
                response = @response,
                completed_at = @completedAt,
                error = @error
          WHERE run_id = @runId`,
      )
      .run({
        runId,
        status: patch.status ?? existing.status,
        response: patch.response ?? existing.response,
        completedAt: patch.completedAt ?? existing.completed_at,
        error: patch.error ?? existing.error,
      });
    return this.getRun(runId);
  }

  getRun(runId: string): RunRow | null {
    return (this.db.prepare(`SELECT * FROM runs WHERE run_id = ?`).get(runId) as RunRow) ?? null;
  }

  listRunsByAgent(agentId: string, limit = 20): RunRow[] {
    return this.db
      .prepare(`SELECT * FROM runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT ?`)
      .all(agentId, limit) as RunRow[];
  }

  getActiveRunForAgent(agentId: string): RunRow | null {
    return (
      (this.db
        .prepare(
          `SELECT * FROM runs WHERE agent_id = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1`,
        )
        .get(agentId) as RunRow) ?? null
    );
  }

  // ---- Messages ---------------------------------------------------------

  createMessage(input: CreateMessageInput): MessageRow {
    const id = randomUUID();
    this.db
      .prepare(
        `INSERT INTO messages (id, agent_id, run_id, role, content, created_at, metadata)
         VALUES (@id, @agentId, @runId, @role, @content, @now, @metadata)`,
      )
      .run({
        id,
        agentId: input.agentId,
        runId: input.runId ?? null,
        role: input.role,
        content: input.content,
        now: nowIso(),
        metadata: JSON.stringify(input.metadata ?? {}),
      });
    return this.listMessageById(id)!;
  }

  listMessagesByAgent(agentId: string, limit = 20): MessageRow[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM (
           SELECT * FROM messages WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?
         ) ORDER BY created_at ASC`,
      )
      .all(agentId, limit) as RawMessageRow[];
    return rows.map(deserializeMessage);
  }

  private listMessageById(id: string): MessageRow | null {
    const row = this.db.prepare(`SELECT * FROM messages WHERE id = ?`).get(id) as
      | RawMessageRow
      | undefined;
    return row ? deserializeMessage(row) : null;
  }

  // ---- Lifecycle --------------------------------------------------------

  healthcheck(): boolean {
    try {
      this.db.prepare("SELECT 1").get();
      return true;
    } catch {
      return false;
    }
  }

  close(): void {
    this.db.close();
  }
}

function deserializeAgent(row: RawAgentRow): AgentRow {
  return { ...row, metadata: safeParse(row.metadata) };
}

function deserializeMessage(row: RawMessageRow): MessageRow {
  return { ...row, metadata: safeParse(row.metadata) };
}

function safeParse(json: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(json) as unknown;
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function nowIso(): string {
  return new Date().toISOString();
}
