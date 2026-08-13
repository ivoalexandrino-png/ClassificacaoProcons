import Database from "better-sqlite3";
import { randomUUID } from "node:crypto";
import type {
  AgentRecord,
  MessageRecord,
  MessageRole,
  ProjectRecord,
  RunRecord,
} from "./types.js";

export class BridgeStore {
  private readonly db: Database.Database;

  constructor(databasePath: string) {
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
        repository TEXT NOT NULL,
        working_directory TEXT NOT NULL,
        default_branch TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id),
        mode TEXT NOT NULL,
        branch TEXT,
        status TEXT NOT NULL,
        working_directory TEXT,
        repository TEXT,
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
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL REFERENCES agents(agent_id),
        run_id TEXT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        metadata TEXT
      );

      CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);
      CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id);
      CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id, created_at);
    `);
  }

  healthCheck(): boolean {
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

  registerProject(input: {
    name: string;
    repository: string;
    working_directory: string;
    default_branch: string;
  }): ProjectRecord {
    const now = new Date().toISOString();
    const existing = this.getProjectByName(input.name);
    if (existing) {
      this.db
        .prepare(
          `UPDATE projects
           SET repository = ?, working_directory = ?, default_branch = ?, updated_at = ?
           WHERE id = ?`,
        )
        .run(input.repository, input.working_directory, input.default_branch, now, existing.id);
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
        input.repository,
        input.working_directory,
        input.default_branch,
        now,
        now,
      );
    return this.getProjectById(id)!;
  }

  listProjects(): ProjectRecord[] {
    return this.db
      .prepare("SELECT * FROM projects ORDER BY name ASC")
      .all() as ProjectRecord[];
  }

  getProjectById(id: string): ProjectRecord | undefined {
    return this.db.prepare("SELECT * FROM projects WHERE id = ?").get(id) as
      | ProjectRecord
      | undefined;
  }

  getProjectByName(name: string): ProjectRecord | undefined {
    return this.db.prepare("SELECT * FROM projects WHERE name = ?").get(name) as
      | ProjectRecord
      | undefined;
  }

  upsertAgent(input: {
    agent_id: string;
    project_id?: string | null;
    mode: "local" | "cloud";
    branch?: string | null;
    status: string;
    working_directory?: string | null;
    repository?: string | null;
    metadata?: Record<string, unknown>;
  }): AgentRecord {
    const now = new Date().toISOString();
    const metadata = input.metadata ? JSON.stringify(input.metadata) : null;
    const existing = this.getAgent(input.agent_id);

    if (existing) {
      this.db
        .prepare(
          `UPDATE agents
           SET project_id = ?, mode = ?, branch = ?, status = ?, working_directory = ?,
               repository = ?, last_activity_at = ?, metadata = ?
           WHERE agent_id = ?`,
        )
        .run(
          input.project_id ?? existing.project_id,
          input.mode,
          input.branch ?? existing.branch,
          input.status,
          input.working_directory ?? existing.working_directory,
          input.repository ?? existing.repository,
          now,
          metadata ?? existing.metadata,
          input.agent_id,
        );
    } else {
      this.db
        .prepare(
          `INSERT INTO agents (
             agent_id, project_id, mode, branch, status, working_directory,
             repository, created_at, last_activity_at, metadata
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .run(
          input.agent_id,
          input.project_id ?? null,
          input.mode,
          input.branch ?? null,
          input.status,
          input.working_directory ?? null,
          input.repository ?? null,
          now,
          now,
          metadata,
        );
    }

    return this.getAgent(input.agent_id)!;
  }

  listAgents(): AgentRecord[] {
    return this.db
      .prepare("SELECT * FROM agents ORDER BY last_activity_at DESC")
      .all() as AgentRecord[];
  }

  getAgent(agentId: string): AgentRecord | undefined {
    return this.db.prepare("SELECT * FROM agents WHERE agent_id = ?").get(agentId) as
      | AgentRecord
      | undefined;
  }

  createRun(input: {
    run_id: string;
    agent_id: string;
    status: string;
    prompt: string;
  }): RunRecord {
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO runs (run_id, agent_id, status, prompt, response, started_at, completed_at, error)
         VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL)`,
      )
      .run(input.run_id, input.agent_id, input.status, input.prompt, now);
    return this.getRun(input.run_id)!;
  }

  updateRun(
    runId: string,
    patch: {
      status?: string;
      response?: string | null;
      completed_at?: string | null;
      error?: string | null;
    },
  ): RunRecord {
    const existing = this.getRun(runId);
    if (!existing) {
      throw new Error(`Run not found: ${runId}`);
    }
    this.db
      .prepare(
        `UPDATE runs
         SET status = ?, response = ?, completed_at = ?, error = ?
         WHERE run_id = ?`,
      )
      .run(
        patch.status ?? existing.status,
        patch.response ?? existing.response,
        patch.completed_at ?? existing.completed_at,
        patch.error ?? existing.error,
        runId,
      );
    return this.getRun(runId)!;
  }

  getRun(runId: string): RunRecord | undefined {
    return this.db.prepare("SELECT * FROM runs WHERE run_id = ?").get(runId) as
      | RunRecord
      | undefined;
  }

  getActiveRunForAgent(agentId: string): RunRecord | undefined {
    return this.db
      .prepare(
        `SELECT * FROM runs
         WHERE agent_id = ? AND status IN ('running', 'pending', 'CREATING', 'RUNNING')
         ORDER BY started_at DESC LIMIT 1`,
      )
      .get(agentId) as RunRecord | undefined;
  }

  addMessage(input: {
    agent_id: string;
    run_id?: string | null;
    role: MessageRole;
    content: string;
    metadata?: Record<string, unknown>;
  }): MessageRecord {
    const id = randomUUID();
    const now = new Date().toISOString();
    const metadata = input.metadata ? JSON.stringify(input.metadata) : null;
    this.db
      .prepare(
        `INSERT INTO messages (id, agent_id, run_id, role, content, created_at, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(id, input.agent_id, input.run_id ?? null, input.role, input.content, now, metadata);
    return this.getMessage(id)!;
  }

  getMessage(id: string): MessageRecord | undefined {
    return this.db.prepare("SELECT * FROM messages WHERE id = ?").get(id) as
      | MessageRecord
      | undefined;
  }

  getConversation(agentId: string, limit = 20): MessageRecord[] {
    return this.db
      .prepare(
        `SELECT * FROM messages
         WHERE agent_id = ?
         ORDER BY created_at DESC
         LIMIT ?`,
      )
      .all(agentId, limit) as MessageRecord[];
  }
}
