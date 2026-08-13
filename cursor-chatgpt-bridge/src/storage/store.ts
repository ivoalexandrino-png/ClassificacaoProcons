import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import path from "node:path";

import Database from "better-sqlite3";

import type {
  AgentMode,
  AgentRecord,
  MessageRecord,
  MessageRole,
  ProjectRecord,
  RunRecord,
  RunStatus,
} from "./types.js";

const SCHEMA = `
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
  project_id TEXT REFERENCES projects(id),
  mode TEXT NOT NULL DEFAULT 'cloud',
  branch TEXT,
  status TEXT NOT NULL DEFAULT 'unknown',
  created_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  status TEXT NOT NULL,
  prompt TEXT NOT NULL,
  response TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL REFERENCES agents(agent_id),
  run_id TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id, id);
`;

function now(): string {
  return new Date().toISOString();
}

function parseJson(value: string | null | undefined): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

interface AgentRow extends Omit<AgentRecord, "metadata"> {
  metadata: string;
}

interface MessageRow extends Omit<MessageRecord, "metadata"> {
  metadata: string;
}

export class BridgeStore {
  private readonly db: Database.Database;

  constructor(databasePath: string) {
    if (databasePath !== ":memory:") {
      mkdirSync(path.dirname(path.resolve(databasePath)), { recursive: true });
    }
    this.db = new Database(databasePath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("foreign_keys = ON");
    this.db.exec(SCHEMA);
  }

  close(): void {
    this.db.close();
  }

  // ---------------------------------------------------------------- projects

  registerProject(input: {
    name: string;
    repository?: string | null;
    working_directory?: string | null;
    default_branch?: string | null;
  }): ProjectRecord {
    const existing = this.getProjectByName(input.name);
    const ts = now();
    if (existing) {
      this.db
        .prepare(
          `UPDATE projects SET repository = ?, working_directory = ?, default_branch = ?, updated_at = ? WHERE id = ?`,
        )
        .run(
          input.repository ?? existing.repository,
          input.working_directory ?? existing.working_directory,
          input.default_branch ?? existing.default_branch,
          ts,
          existing.id,
        );
      return this.getProjectById(existing.id)!;
    }
    const id = randomUUID();
    this.db
      .prepare(
        `INSERT INTO projects (id, name, repository, working_directory, default_branch, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        input.name,
        input.repository ?? null,
        input.working_directory ?? null,
        input.default_branch ?? null,
        ts,
        ts,
      );
    return this.getProjectById(id)!;
  }

  getProjectById(id: string): ProjectRecord | undefined {
    return this.db.prepare(`SELECT * FROM projects WHERE id = ?`).get(id) as
      | ProjectRecord
      | undefined;
  }

  getProjectByName(name: string): ProjectRecord | undefined {
    return this.db
      .prepare(`SELECT * FROM projects WHERE name = ? COLLATE NOCASE`)
      .get(name) as ProjectRecord | undefined;
  }

  listProjects(): ProjectRecord[] {
    return this.db.prepare(`SELECT * FROM projects ORDER BY name`).all() as ProjectRecord[];
  }

  // ------------------------------------------------------------------ agents

  upsertAgent(input: {
    agent_id: string;
    project_id?: string | null;
    mode?: AgentMode;
    branch?: string | null;
    status?: string;
    metadata?: Record<string, unknown>;
  }): AgentRecord {
    const existing = this.getAgent(input.agent_id);
    const ts = now();
    if (existing) {
      const metadata = input.metadata
        ? { ...existing.metadata, ...input.metadata }
        : existing.metadata;
      this.db
        .prepare(
          `UPDATE agents SET project_id = ?, mode = ?, branch = ?, status = ?, last_activity_at = ?, metadata = ? WHERE agent_id = ?`,
        )
        .run(
          input.project_id ?? existing.project_id,
          input.mode ?? existing.mode,
          input.branch ?? existing.branch,
          input.status ?? existing.status,
          ts,
          JSON.stringify(metadata),
          input.agent_id,
        );
      return this.getAgent(input.agent_id)!;
    }
    this.db
      .prepare(
        `INSERT INTO agents (agent_id, project_id, mode, branch, status, created_at, last_activity_at, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        input.agent_id,
        input.project_id ?? null,
        input.mode ?? "cloud",
        input.branch ?? null,
        input.status ?? "unknown",
        ts,
        ts,
        JSON.stringify(input.metadata ?? {}),
      );
    return this.getAgent(input.agent_id)!;
  }

  getAgent(agentId: string): AgentRecord | undefined {
    const row = this.db.prepare(`SELECT * FROM agents WHERE agent_id = ?`).get(agentId) as
      | AgentRow
      | undefined;
    if (!row) return undefined;
    return { ...row, metadata: parseJson(row.metadata) };
  }

  listAgents(): AgentRecord[] {
    const rows = this.db
      .prepare(`SELECT * FROM agents ORDER BY last_activity_at DESC`)
      .all() as AgentRow[];
    return rows.map((row) => ({ ...row, metadata: parseJson(row.metadata) }));
  }

  touchAgent(agentId: string, status?: string): void {
    if (status) {
      this.db
        .prepare(`UPDATE agents SET last_activity_at = ?, status = ? WHERE agent_id = ?`)
        .run(now(), status, agentId);
    } else {
      this.db
        .prepare(`UPDATE agents SET last_activity_at = ? WHERE agent_id = ?`)
        .run(now(), agentId);
    }
  }

  // -------------------------------------------------------------------- runs

  createRun(input: { run_id: string; agent_id: string; prompt: string }): RunRecord {
    this.db
      .prepare(
        `INSERT INTO runs (run_id, agent_id, status, prompt, started_at) VALUES (?, ?, 'running', ?, ?)`,
      )
      .run(input.run_id, input.agent_id, input.prompt, now());
    return this.getRun(input.run_id)!;
  }

  updateRun(
    runId: string,
    update: { status?: RunStatus; response?: string | null; error?: string | null; completed?: boolean },
  ): RunRecord | undefined {
    const existing = this.getRun(runId);
    if (!existing) return undefined;
    this.db
      .prepare(`UPDATE runs SET status = ?, response = ?, error = ?, completed_at = ? WHERE run_id = ?`)
      .run(
        update.status ?? existing.status,
        update.response !== undefined ? update.response : existing.response,
        update.error !== undefined ? update.error : existing.error,
        update.completed ? now() : existing.completed_at,
        runId,
      );
    return this.getRun(runId);
  }

  getRun(runId: string): RunRecord | undefined {
    return this.db.prepare(`SELECT * FROM runs WHERE run_id = ?`).get(runId) as
      | RunRecord
      | undefined;
  }

  listRunsForAgent(agentId: string, limit = 20): RunRecord[] {
    return this.db
      .prepare(`SELECT * FROM runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT ?`)
      .all(agentId, limit) as RunRecord[];
  }

  getActiveRunForAgent(agentId: string): RunRecord | undefined {
    return this.db
      .prepare(
        `SELECT * FROM runs WHERE agent_id = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1`,
      )
      .get(agentId) as RunRecord | undefined;
  }

  // ---------------------------------------------------------------- messages

  addMessage(input: {
    agent_id: string;
    run_id?: string | null;
    role: MessageRole;
    content: string;
    metadata?: Record<string, unknown>;
  }): MessageRecord {
    const result = this.db
      .prepare(
        `INSERT INTO messages (agent_id, run_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?)`,
      )
      .run(
        input.agent_id,
        input.run_id ?? null,
        input.role,
        input.content,
        now(),
        JSON.stringify(input.metadata ?? {}),
      );
    return this.getMessage(Number(result.lastInsertRowid))!;
  }

  getMessage(id: number): MessageRecord | undefined {
    const row = this.db.prepare(`SELECT * FROM messages WHERE id = ?`).get(id) as
      | MessageRow
      | undefined;
    if (!row) return undefined;
    return { ...row, metadata: parseJson(row.metadata) };
  }

  /** Most recent `limit` messages for an agent, returned in chronological order. */
  getConversation(agentId: string, limit = 20): MessageRecord[] {
    const rows = this.db
      .prepare(`SELECT * FROM messages WHERE agent_id = ? ORDER BY id DESC LIMIT ?`)
      .all(agentId, limit) as MessageRow[];
    return rows.reverse().map((row) => ({ ...row, metadata: parseJson(row.metadata) }));
  }
}
