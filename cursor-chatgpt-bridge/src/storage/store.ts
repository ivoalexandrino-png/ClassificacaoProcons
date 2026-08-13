import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import Database from "better-sqlite3";
import type {
  AgentRow,
  CreateAgentInput,
  CreateMessageInput,
  CreateProjectInput,
  CreateRunInput,
  MessageRow,
  ProjectRow,
  RunRow,
  RunStatus,
  UpdateRunInput,
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
  mode TEXT NOT NULL,
  branch TEXT,
  repository TEXT,
  working_directory TEXT,
  status TEXT NOT NULL,
  active_run_id TEXT,
  created_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL,
  metadata TEXT
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
  run_id TEXT REFERENCES runs(run_id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_agents_project_id ON agents(project_id);
CREATE INDEX IF NOT EXISTS idx_runs_agent_id ON runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent_id ON messages(agent_id, id);
`;

function nowIso(): string {
  return new Date().toISOString();
}

/**
 * SQLite-backed persistence for projects, agents, runs, and messages.
 *
 * All methods are synchronous (better-sqlite3 is a sync driver); callers
 * that need an async-looking surface can simply await the return value,
 * since awaiting a non-promise resolves immediately.
 */
export class BridgeStore {
  private readonly db: Database.Database;

  constructor(databasePath: string) {
    if (databasePath !== ":memory:") {
      mkdirSync(dirname(databasePath), { recursive: true });
    }
    this.db = new Database(databasePath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("foreign_keys = ON");
    this.db.exec(SCHEMA);
  }

  close(): void {
    this.db.close();
  }

  // ---------------------------------------------------------------------
  // Projects
  // ---------------------------------------------------------------------

  createProject(input: CreateProjectInput): ProjectRow {
    const existing = this.getProjectByName(input.name);
    if (existing) {
      return this.updateProject(existing.id, input);
    }
    const id = randomUUID();
    const timestamp = nowIso();
    this.db
      .prepare(
        `INSERT INTO projects (id, name, repository, working_directory, default_branch, created_at, updated_at)
         VALUES (@id, @name, @repository, @workingDirectory, @defaultBranch, @createdAt, @updatedAt)`,
      )
      .run({
        id,
        name: input.name,
        repository: input.repository ?? null,
        workingDirectory: input.workingDirectory ?? null,
        defaultBranch: input.defaultBranch ?? null,
        createdAt: timestamp,
        updatedAt: timestamp,
      });
    return this.getProjectById(id)!;
  }

  updateProject(id: string, input: CreateProjectInput): ProjectRow {
    this.db
      .prepare(
        `UPDATE projects
         SET repository = @repository, working_directory = @workingDirectory,
             default_branch = @defaultBranch, updated_at = @updatedAt
         WHERE id = @id`,
      )
      .run({
        id,
        repository: input.repository ?? null,
        workingDirectory: input.workingDirectory ?? null,
        defaultBranch: input.defaultBranch ?? null,
        updatedAt: nowIso(),
      });
    return this.getProjectById(id)!;
  }

  getProjectById(id: string): ProjectRow | undefined {
    return this.db.prepare(`SELECT * FROM projects WHERE id = ?`).get(id) as ProjectRow | undefined;
  }

  getProjectByName(name: string): ProjectRow | undefined {
    return this.db.prepare(`SELECT * FROM projects WHERE name = ?`).get(name) as
      | ProjectRow
      | undefined;
  }

  listProjects(): ProjectRow[] {
    return this.db.prepare(`SELECT * FROM projects ORDER BY created_at ASC`).all() as ProjectRow[];
  }

  // ---------------------------------------------------------------------
  // Agents
  // ---------------------------------------------------------------------

  createAgent(input: CreateAgentInput): AgentRow {
    const timestamp = nowIso();
    this.db
      .prepare(
        `INSERT INTO agents (agent_id, project_id, mode, branch, repository, working_directory,
                              status, active_run_id, created_at, last_activity_at, metadata)
         VALUES (@agentId, @projectId, @mode, @branch, @repository, @workingDirectory,
                 @status, NULL, @createdAt, @lastActivityAt, @metadata)`,
      )
      .run({
        agentId: input.agentId,
        projectId: input.projectId ?? null,
        mode: input.mode,
        branch: input.branch ?? null,
        repository: input.repository ?? null,
        workingDirectory: input.workingDirectory ?? null,
        status: input.status,
        createdAt: timestamp,
        lastActivityAt: timestamp,
        metadata: input.metadata ? JSON.stringify(input.metadata) : null,
      });
    return this.getAgent(input.agentId)!;
  }

  getAgent(agentId: string): AgentRow | undefined {
    return this.db.prepare(`SELECT * FROM agents WHERE agent_id = ?`).get(agentId) as
      | AgentRow
      | undefined;
  }

  listAgents(): AgentRow[] {
    return this.db
      .prepare(`SELECT * FROM agents ORDER BY last_activity_at DESC`)
      .all() as AgentRow[];
  }

  listAgentsByProject(projectId: string): AgentRow[] {
    return this.db
      .prepare(`SELECT * FROM agents WHERE project_id = ? ORDER BY last_activity_at DESC`)
      .all(projectId) as AgentRow[];
  }

  touchAgent(agentId: string, status?: RunStatus): void {
    if (status) {
      this.db
        .prepare(`UPDATE agents SET status = ?, last_activity_at = ? WHERE agent_id = ?`)
        .run(status, nowIso(), agentId);
    } else {
      this.db.prepare(`UPDATE agents SET last_activity_at = ? WHERE agent_id = ?`).run(
        nowIso(),
        agentId,
      );
    }
  }

  setAgentActiveRun(agentId: string, runId: string | null): void {
    this.db
      .prepare(`UPDATE agents SET active_run_id = ?, last_activity_at = ? WHERE agent_id = ?`)
      .run(runId, nowIso(), agentId);
  }

  // ---------------------------------------------------------------------
  // Runs
  // ---------------------------------------------------------------------

  createRun(input: CreateRunInput): RunRow {
    const timestamp = nowIso();
    this.db
      .prepare(
        `INSERT INTO runs (run_id, agent_id, status, prompt, response, started_at, completed_at, error)
         VALUES (@runId, @agentId, @status, @prompt, NULL, @startedAt, NULL, NULL)`,
      )
      .run({
        runId: input.runId,
        agentId: input.agentId,
        status: input.status,
        prompt: input.prompt,
        startedAt: timestamp,
      });
    return this.getRun(input.runId)!;
  }

  getRun(runId: string): RunRow | undefined {
    return this.db.prepare(`SELECT * FROM runs WHERE run_id = ?`).get(runId) as
      | RunRow
      | undefined;
  }

  updateRun(runId: string, input: UpdateRunInput): RunRow {
    const current = this.getRun(runId);
    if (!current) {
      throw new Error(`Run not found: ${runId}`);
    }
    this.db
      .prepare(
        `UPDATE runs
         SET status = @status, response = @response, completed_at = @completedAt, error = @error
         WHERE run_id = @runId`,
      )
      .run({
        runId,
        status: input.status ?? current.status,
        response: input.response !== undefined ? input.response : current.response,
        completedAt: input.completedAt !== undefined ? input.completedAt : current.completed_at,
        error: input.error !== undefined ? input.error : current.error,
      });
    return this.getRun(runId)!;
  }

  listRunsByAgent(agentId: string, limit = 20): RunRow[] {
    return this.db
      .prepare(`SELECT * FROM runs WHERE agent_id = ? ORDER BY started_at DESC LIMIT ?`)
      .all(agentId, limit) as RunRow[];
  }

  /** The most recent non-terminal run for an agent, if any (used for busy/lock checks). */
  getActiveRun(agentId: string): RunRow | undefined {
    return this.db
      .prepare(
        `SELECT * FROM runs
         WHERE agent_id = ? AND status IN ('queued', 'creating', 'running')
         ORDER BY started_at DESC LIMIT 1`,
      )
      .get(agentId) as RunRow | undefined;
  }

  // ---------------------------------------------------------------------
  // Messages
  // ---------------------------------------------------------------------

  createMessage(input: CreateMessageInput): MessageRow {
    const timestamp = nowIso();
    const result = this.db
      .prepare(
        `INSERT INTO messages (agent_id, run_id, role, content, created_at, metadata)
         VALUES (@agentId, @runId, @role, @content, @createdAt, @metadata)`,
      )
      .run({
        agentId: input.agentId,
        runId: input.runId ?? null,
        role: input.role,
        content: input.content,
        createdAt: timestamp,
        metadata: input.metadata ? JSON.stringify(input.metadata) : null,
      });
    return this.getMessageById(Number(result.lastInsertRowid))!;
  }

  getMessageById(id: number): MessageRow | undefined {
    return this.db.prepare(`SELECT * FROM messages WHERE id = ?`).get(id) as
      | MessageRow
      | undefined;
  }

  /** Most recent messages for an agent, oldest first (natural conversation order). */
  listMessagesByAgent(agentId: string, limit = 20): MessageRow[] {
    const rows = this.db
      .prepare(`SELECT * FROM messages WHERE agent_id = ? ORDER BY id DESC LIMIT ?`)
      .all(agentId, limit) as MessageRow[];
    return rows.reverse();
  }
}

let sharedStore: BridgeStore | undefined;

export function getSharedStore(databasePath: string): BridgeStore {
  sharedStore ??= new BridgeStore(databasePath);
  return sharedStore;
}

export function resetSharedStore(): void {
  sharedStore?.close();
  sharedStore = undefined;
}
