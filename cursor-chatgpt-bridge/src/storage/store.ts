import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { BridgeError } from "../errors.js";
import type {
  AgentMode,
  AgentRecord,
  MessageRecord,
  MessageRole,
  ProjectRecord,
  RunRecord,
  RunStatus,
} from "./types.js";

type DatabaseRow = Record<string, unknown>;

function jsonObject(value: unknown): Record<string, unknown> {
  if (typeof value !== "string") return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function mapProject(row: DatabaseRow): ProjectRecord {
  return row as unknown as ProjectRecord;
}

function mapAgent(row: DatabaseRow): AgentRecord {
  return {
    ...(row as unknown as Omit<AgentRecord, "metadata">),
    metadata: jsonObject(row.metadata),
  };
}

function mapRun(row: DatabaseRow): RunRecord {
  return {
    ...(row as unknown as Omit<RunRecord, "metadata">),
    metadata: jsonObject(row.metadata),
  };
}

function mapMessage(row: DatabaseRow): MessageRecord {
  return {
    ...(row as unknown as Omit<MessageRecord, "metadata">),
    metadata: jsonObject(row.metadata),
  };
}

export class BridgeStore {
  private readonly database: Database.Database;

  constructor(databasePath: string) {
    if (databasePath !== ":memory:") {
      fs.mkdirSync(path.dirname(databasePath), { recursive: true });
    }
    this.database = new Database(databasePath);
    this.database.pragma("foreign_keys = ON");
    this.database.pragma("journal_mode = WAL");
    this.migrate();
  }

  private migrate(): void {
    this.database.exec(`
      CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        repository TEXT NOT NULL,
        working_directory TEXT NOT NULL,
        default_branch TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        mode TEXT NOT NULL CHECK(mode IN ('local', 'cloud')),
        branch TEXT,
        status TEXT NOT NULL,
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
        run_id TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool', 'system')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
      );
      CREATE INDEX IF NOT EXISTS idx_agents_project_activity
        ON agents(project_id, last_activity_at DESC);
      CREATE INDEX IF NOT EXISTS idx_runs_agent_started
        ON runs(agent_id, started_at DESC);
      CREATE INDEX IF NOT EXISTS idx_messages_agent_created
        ON messages(agent_id, created_at DESC);
    `);
  }

  close(): void {
    this.database.close();
  }

  isHealthy(): boolean {
    const row = this.database.prepare("SELECT 1 AS healthy").get() as DatabaseRow;
    return row.healthy === 1;
  }

  registerProject(input: {
    name: string;
    repository: string;
    workingDirectory: string;
    defaultBranch: string;
  }): ProjectRecord {
    const now = new Date().toISOString();
    const existing = this.getProjectByName(input.name);
    if (existing) {
      if (
        existing.repository !== input.repository ||
        existing.working_directory !== input.workingDirectory ||
        existing.default_branch !== input.defaultBranch
      ) {
        throw new BridgeError(
          "INVALID_INPUT",
          "Registered project mappings are immutable",
          { project: existing.name },
          409,
        );
      }
      return existing;
    }
    const id = randomUUID();
    this.database
      .prepare(
        `INSERT INTO projects
         (id, name, repository, working_directory, default_branch, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        input.name,
        input.repository,
        input.workingDirectory,
        input.defaultBranch,
        now,
        now,
      );
    return this.getProjectById(id)!;
  }

  listProjects(): ProjectRecord[] {
    return (
      this.database.prepare("SELECT * FROM projects ORDER BY name COLLATE NOCASE").all() as DatabaseRow[]
    ).map(mapProject);
  }

  getProjectByName(name: string): ProjectRecord | undefined {
    const row = this.database
      .prepare("SELECT * FROM projects WHERE name = ? COLLATE NOCASE")
      .get(name) as DatabaseRow | undefined;
    return row ? mapProject(row) : undefined;
  }

  getProjectById(id: string): ProjectRecord | undefined {
    const row = this.database.prepare("SELECT * FROM projects WHERE id = ?").get(id) as
      | DatabaseRow
      | undefined;
    return row ? mapProject(row) : undefined;
  }

  createAgent(input: {
    agentId: string;
    projectId: string;
    mode: AgentMode;
    branch?: string;
    status?: string;
    metadata?: Record<string, unknown>;
  }): AgentRecord {
    const now = new Date().toISOString();
    this.database
      .prepare(
        `INSERT INTO agents
         (agent_id, project_id, mode, branch, status, created_at, last_activity_at, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        input.agentId,
        input.projectId,
        input.mode,
        input.branch ?? null,
        input.status ?? "idle",
        now,
        now,
        JSON.stringify(input.metadata ?? {}),
      );
    return this.getAgent(input.agentId)!;
  }

  getAgent(agentId: string): AgentRecord | undefined {
    const row = this.database.prepare("SELECT * FROM agents WHERE agent_id = ?").get(agentId) as
      | DatabaseRow
      | undefined;
    return row ? mapAgent(row) : undefined;
  }

  listAgents(): Array<AgentRecord & { project: string; repository: string; working_directory: string }> {
    const rows = this.database
      .prepare(
        `SELECT agents.*, projects.name AS project, projects.repository,
                projects.working_directory
         FROM agents JOIN projects ON projects.id = agents.project_id
         ORDER BY agents.last_activity_at DESC`,
      )
      .all() as DatabaseRow[];
    return rows.map((row) => ({
      ...mapAgent(row),
      project: String(row.project),
      repository: String(row.repository),
      working_directory: String(row.working_directory),
    }));
  }

  updateAgent(agentId: string, status: string, metadata?: Record<string, unknown>): void {
    const now = new Date().toISOString();
    if (metadata) {
      this.database
        .prepare(
          "UPDATE agents SET status = ?, last_activity_at = ?, metadata = ? WHERE agent_id = ?",
        )
        .run(status, now, JSON.stringify(metadata), agentId);
    } else {
      this.database
        .prepare("UPDATE agents SET status = ?, last_activity_at = ? WHERE agent_id = ?")
        .run(status, now, agentId);
    }
  }

  createRun(input: {
    runId: string;
    agentId: string;
    prompt: string;
    status?: RunStatus;
    metadata?: Record<string, unknown>;
  }): RunRecord {
    const now = new Date().toISOString();
    this.database
      .prepare(
        `INSERT INTO runs
         (run_id, agent_id, status, prompt, response, started_at, completed_at, error, metadata)
         VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, ?)`,
      )
      .run(
        input.runId,
        input.agentId,
        input.status ?? "running",
        input.prompt,
        now,
        JSON.stringify(input.metadata ?? {}),
      );
    return this.getRun(input.runId)!;
  }

  beginRun(input: {
    runId: string;
    agentId: string;
    prompt: string;
    metadata?: Record<string, unknown>;
  }): RunRecord {
    return this.database.transaction(() => {
      const run = this.createRun(input);
      this.addMessage({
        agentId: input.agentId,
        runId: input.runId,
        role: "user",
        content: input.prompt,
      });
      this.updateAgent(input.agentId, "running");
      return run;
    })();
  }

  getRun(runId: string): RunRecord | undefined {
    const row = this.database.prepare("SELECT * FROM runs WHERE run_id = ?").get(runId) as
      | DatabaseRow
      | undefined;
    return row ? mapRun(row) : undefined;
  }

  getActiveRun(agentId: string): RunRecord | undefined {
    const row = this.database
      .prepare(
        `SELECT * FROM runs
         WHERE agent_id = ? AND status IN ('running', 'timeout')
         ORDER BY started_at DESC LIMIT 1`,
      )
      .get(agentId) as DatabaseRow | undefined;
    return row ? mapRun(row) : undefined;
  }

  getLatestRun(agentId: string): RunRecord | undefined {
    const row = this.database
      .prepare("SELECT * FROM runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT 1")
      .get(agentId) as DatabaseRow | undefined;
    return row ? mapRun(row) : undefined;
  }

  completeRun(
    runId: string,
    status: Exclude<RunStatus, "running">,
    response: string | null,
    error: string | null,
    metadata?: Record<string, unknown>,
  ): boolean {
    const completedAt = status === "timeout" ? null : new Date().toISOString();
    const allowedCurrentStatuses =
      status === "timeout" ? "status = 'running'" : "status IN ('running', 'timeout')";
    const result = this.database
      .prepare(
        `UPDATE runs SET status = ?, response = ?, completed_at = ?, error = ?,
         metadata = COALESCE(?, metadata)
         WHERE run_id = ? AND ${allowedCurrentStatuses}`,
      )
      .run(
        status,
        response,
        completedAt,
        error,
        metadata ? JSON.stringify(metadata) : null,
        runId,
      );
    return result.changes === 1;
  }

  finalizeRun(input: {
    runId: string;
    status: Exclude<RunStatus, "running" | "timeout">;
    response: string | null;
    error: string | null;
    metadata: Record<string, unknown>;
    messages: Array<{
      role: MessageRole;
      content: string;
      metadata?: Record<string, unknown>;
    }>;
  }): boolean {
    return this.database.transaction(() => {
      const finalized = this.completeRun(
        input.runId,
        input.status,
        input.response,
        input.error,
        input.metadata,
      );
      if (!finalized) return false;
      const run = this.getRun(input.runId);
      if (!run) return false;
      for (const message of input.messages) {
        this.addMessage({
          agentId: run.agent_id,
          runId: input.runId,
          role: message.role,
          content: message.content,
          metadata: message.metadata,
        });
      }
      return true;
    })();
  }

  addMessage(input: {
    agentId: string;
    runId?: string;
    role: MessageRole;
    content: string;
    metadata?: Record<string, unknown>;
  }): MessageRecord {
    const id = randomUUID();
    const createdAt = new Date().toISOString();
    this.database
      .prepare(
        `INSERT INTO messages
         (id, agent_id, run_id, role, content, created_at, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        input.agentId,
        input.runId ?? null,
        input.role,
        input.content,
        createdAt,
        JSON.stringify(input.metadata ?? {}),
      );
    const row = this.database.prepare("SELECT * FROM messages WHERE id = ?").get(id) as DatabaseRow;
    return mapMessage(row);
  }

  getConversation(agentId: string, limit: number): MessageRecord[] {
    const rows = this.database
      .prepare(
        `SELECT * FROM (
           SELECT *, rowid AS sequence FROM messages
           WHERE agent_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?
         ) ORDER BY created_at ASC, sequence ASC`,
      )
      .all(agentId, limit) as DatabaseRow[];
    return rows.map(mapMessage);
  }
}
