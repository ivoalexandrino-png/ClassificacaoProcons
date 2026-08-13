import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import Database from "better-sqlite3";
import type { AgentRecord, MessageRecord, Project, RunRecord } from "../cursor/types.js";

const now = () => new Date().toISOString();
const stringify = (value: Record<string, unknown>) => JSON.stringify(value);
const parse = (value: string) => JSON.parse(value) as Record<string, unknown>;

export class BridgeStore {
  private readonly db: Database.Database;

  constructor(databasePath: string) {
    mkdirSync(dirname(databasePath), { recursive: true });
    this.db = new Database(databasePath);
    this.db.pragma("journal_mode = WAL");
    this.migrate();
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, repository TEXT NOT NULL,
        working_directory TEXT NOT NULL, default_branch TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), mode TEXT NOT NULL,
        branch TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, last_activity_at TEXT NOT NULL, metadata TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(agent_id), status TEXT NOT NULL,
        prompt TEXT NOT NULL, response TEXT, started_at TEXT NOT NULL, completed_at TEXT, error TEXT
      );
      CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL REFERENCES agents(agent_id), run_id TEXT,
        role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL, metadata TEXT NOT NULL
      );
    `);
  }

  close(): void { this.db.close(); }

  registerProject(input: Omit<Project, "id" | "createdAt" | "updatedAt">): Project {
    const timestamp = now();
    this.db.prepare(`
      INSERT INTO projects (name, repository, working_directory, default_branch, created_at, updated_at)
      VALUES (@name, @repository, @workingDirectory, @defaultBranch, @timestamp, @timestamp)
      ON CONFLICT(name) DO UPDATE SET repository = excluded.repository, working_directory = excluded.working_directory,
      default_branch = excluded.default_branch, updated_at = excluded.updated_at
    `).run({ ...input, timestamp });
    return this.getProjectByName(input.name)!;
  }

  listProjects(): Project[] {
    return this.db.prepare("SELECT * FROM projects ORDER BY name").all().map(this.toProject);
  }

  getProjectByName(name: string): Project | undefined {
    const row = this.db.prepare("SELECT * FROM projects WHERE name = ?").get(name);
    return row ? this.toProject(row) : undefined;
  }

  getProject(id: number): Project | undefined {
    const row = this.db.prepare("SELECT * FROM projects WHERE id = ?").get(id);
    return row ? this.toProject(row) : undefined;
  }

  createAgent(agent: AgentRecord): void {
    this.db.prepare(`
      INSERT INTO agents (agent_id, project_id, mode, branch, status, created_at, last_activity_at, metadata)
      VALUES (@agentId, @projectId, @mode, @branch, @status, @createdAt, @lastActivityAt, @metadata)
    `).run({ ...agent, metadata: stringify(agent.metadata) });
  }

  getAgent(agentId: string): AgentRecord | undefined {
    const row = this.db.prepare("SELECT * FROM agents WHERE agent_id = ?").get(agentId);
    return row ? this.toAgent(row) : undefined;
  }

  listAgents(): AgentRecord[] {
    return this.db.prepare("SELECT * FROM agents ORDER BY last_activity_at DESC").all().map(this.toAgent);
  }

  updateAgentStatus(agentId: string, status: AgentRecord["status"]): void {
    this.db.prepare("UPDATE agents SET status = ?, last_activity_at = ? WHERE agent_id = ?").run(status, now(), agentId);
  }

  createRun(run: RunRecord): void {
    this.db.prepare(`
      INSERT INTO runs (run_id, agent_id, status, prompt, response, started_at, completed_at, error)
      VALUES (@runId, @agentId, @status, @prompt, @response, @startedAt, @completedAt, @error)
    `).run(run);
  }

  getRun(runId: string): RunRecord | undefined {
    const row = this.db.prepare("SELECT * FROM runs WHERE run_id = ?").get(runId);
    return row ? this.toRun(row) : undefined;
  }

  updateRun(runId: string, update: Pick<RunRecord, "status" | "response" | "completedAt" | "error">): void {
    this.db.prepare(`
      UPDATE runs SET status = @status, response = @response, completed_at = @completedAt, error = @error WHERE run_id = @runId
    `).run({ runId, ...update });
  }

  addMessage(message: Omit<MessageRecord, "id" | "createdAt"> & { createdAt?: string }): void {
    this.db.prepare(`
      INSERT INTO messages (agent_id, run_id, role, content, created_at, metadata)
      VALUES (@agentId, @runId, @role, @content, @createdAt, @metadata)
    `).run({ ...message, createdAt: message.createdAt ?? now(), metadata: stringify(message.metadata) });
  }

  getConversation(agentId: string, limit: number): MessageRecord[] {
    return this.db.prepare(`
      SELECT * FROM (SELECT * FROM messages WHERE agent_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC
    `).all(agentId, limit).map(this.toMessage);
  }

  private toProject = (row: Record<string, unknown>): Project => ({
    id: row.id as number, name: row.name as string, repository: row.repository as string,
    workingDirectory: row.working_directory as string, defaultBranch: row.default_branch as string,
    createdAt: row.created_at as string, updatedAt: row.updated_at as string
  });
  private toAgent = (row: Record<string, unknown>): AgentRecord => ({
    agentId: row.agent_id as string, projectId: row.project_id as number, mode: row.mode as AgentRecord["mode"],
    branch: row.branch as string | null, status: row.status as AgentRecord["status"],
    createdAt: row.created_at as string, lastActivityAt: row.last_activity_at as string, metadata: parse(row.metadata as string)
  });
  private toRun = (row: Record<string, unknown>): RunRecord => ({
    runId: row.run_id as string, agentId: row.agent_id as string, status: row.status as RunRecord["status"],
    prompt: row.prompt as string, response: row.response as string | null, startedAt: row.started_at as string,
    completedAt: row.completed_at as string | null, error: row.error as string | null
  });
  private toMessage = (row: Record<string, unknown>): MessageRecord => ({
    id: row.id as number, agentId: row.agent_id as string, runId: row.run_id as string | null,
    role: row.role as MessageRecord["role"], content: row.content as string, createdAt: row.created_at as string,
    metadata: parse(row.metadata as string)
  });
}
