import { BridgeError } from "../mcp/errors.js";
import type { BridgeStore } from "../storage/store.js";
import type { AgentRow, ProjectRow } from "../storage/types.js";
import type { AgentContext, CursorAgentProvider } from "./types.js";

export interface RegisterProjectInput {
  name: string;
  repository?: string;
  workingDirectory?: string;
  defaultBranch?: string;
}

export interface StartAgentInput {
  project?: string;
  repository?: string;
  workingDirectory?: string;
  message: string;
  mode: "local" | "cloud";
}

export interface PublicAgentSummary {
  agent_id: string;
  project: string | null;
  repository: string | null;
  branch: string | null;
  status: string;
  last_activity_at: string;
}

export interface PublicAgentDetails extends PublicAgentSummary {
  mode: "local" | "cloud";
  working_directory: string | null;
  active_run_id: string | null;
  created_at: string;
  metadata: Record<string, unknown> | null;
  capabilities: {
    supports_cancel: boolean;
    supports_streaming: boolean;
  };
}

function toProjectPublic(project: ProjectRow) {
  return {
    name: project.name,
    repository: project.repository,
    working_directory: project.working_directory,
    default_branch: project.default_branch,
    created_at: project.created_at,
    updated_at: project.updated_at,
  };
}

function toAgentSummary(row: AgentRow, projectName: string | null): PublicAgentSummary {
  return {
    agent_id: row.agent_id,
    project: projectName,
    repository: row.repository,
    branch: row.branch,
    status: row.status,
    last_activity_at: row.last_activity_at,
  };
}

/**
 * Orchestrates project/agent bookkeeping: combines the bridge's own SQLite
 * records (source of truth for "what does the bridge know about") with
 * live capability data from the Cursor agent provider.
 */
export class AgentService {
  constructor(
    private readonly store: BridgeStore,
    private readonly provider: CursorAgentProvider,
  ) {}

  registerProject(input: RegisterProjectInput) {
    const project = this.store.createProject({
      name: input.name,
      repository: input.repository,
      workingDirectory: input.workingDirectory,
      defaultBranch: input.defaultBranch,
    });
    return toProjectPublic(project);
  }

  listProjects() {
    return this.store.listProjects().map(toProjectPublic);
  }

  private resolveProject(name: string | undefined): ProjectRow | undefined {
    if (!name) return undefined;
    const project = this.store.getProjectByName(name);
    if (!project) {
      throw new BridgeError("PROJECT_NOT_FOUND", `No project registered with name "${name}".`);
    }
    return project;
  }

  private agentContext(row: AgentRow): AgentContext {
    return {
      agentId: row.agent_id,
      mode: row.mode,
      workingDirectory: row.working_directory ?? undefined,
      repository: row.repository ?? undefined,
      branch: row.branch ?? undefined,
    };
  }

  async startAgent(input: StartAgentInput) {
    const project = this.resolveProject(input.project);
    const workingDirectory = input.workingDirectory ?? project?.working_directory ?? undefined;
    const repository = input.repository ?? project?.repository ?? undefined;
    const branch = project?.default_branch ?? undefined;

    if (input.mode === "local" && !workingDirectory) {
      throw new BridgeError(
        "VALIDATION_ERROR",
        "mode=local requires working_directory (directly, or via a registered project).",
      );
    }
    if (input.mode === "cloud" && !repository) {
      throw new BridgeError(
        "VALIDATION_ERROR",
        "mode=cloud requires repository (directly, or via a registered project).",
      );
    }

    const { agentId, run } = await this.provider.startAgent({
      mode: input.mode,
      message: input.message,
      workingDirectory,
      repository,
      branch,
    });

    const status = run.status === "completed" ? "completed" : "running";
    this.store.createAgent({
      agentId,
      projectId: project?.id,
      mode: input.mode,
      branch,
      repository,
      workingDirectory,
      status,
    });
    this.store.createRun({ runId: run.runId, agentId, status, prompt: input.message });
    if (status !== "running") {
      this.store.updateRun(run.runId, {
        status,
        response: run.result ?? null,
        completedAt: status === "completed" ? new Date().toISOString() : null,
      });
    } else {
      this.store.setAgentActiveRun(agentId, run.runId);
    }
    this.store.createMessage({ agentId, runId: run.runId, role: "user", content: input.message });
    if (run.result) {
      this.store.createMessage({
        agentId,
        runId: run.runId,
        role: "assistant",
        content: run.result,
      });
    }

    return {
      agent_id: agentId,
      project: project?.name ?? null,
      repository: repository ?? null,
      working_directory: workingDirectory ?? null,
      mode: input.mode,
      run_id: run.runId,
      status,
    };
  }

  getAgentRowOrThrow(agentId: string): AgentRow {
    const row = this.store.getAgent(agentId);
    if (!row) {
      throw new BridgeError("AGENT_NOT_FOUND", `No agent known to the bridge with id "${agentId}".`);
    }
    return row;
  }

  private projectNameFor(row: AgentRow): string | null {
    if (!row.project_id) return null;
    return this.store.getProjectById(row.project_id)?.name ?? null;
  }

  listAgents(): PublicAgentSummary[] {
    return this.store.listAgents().map((row) => toAgentSummary(row, this.projectNameFor(row)));
  }

  async getAgent(agentId: string): Promise<PublicAgentDetails> {
    const row = this.getAgentRowOrThrow(agentId);
    const capabilities = await this.provider.getCapabilities(this.agentContext(row));
    return {
      ...toAgentSummary(row, this.projectNameFor(row)),
      mode: row.mode,
      working_directory: row.working_directory,
      active_run_id: row.active_run_id,
      created_at: row.created_at,
      metadata: row.metadata ? (JSON.parse(row.metadata) as Record<string, unknown>) : null,
      capabilities: {
        supports_cancel: capabilities.supportsCancel,
        supports_streaming: capabilities.supportsStreaming,
      },
    };
  }

  contextFor(agentId: string): { row: AgentRow; context: AgentContext } {
    const row = this.getAgentRowOrThrow(agentId);
    return { row, context: this.agentContext(row) };
  }

  getConversation(agentId: string, limit: number) {
    this.getAgentRowOrThrow(agentId);
    const messages = this.store.listMessagesByAgent(agentId, limit);
    return messages.map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
      run_id: message.run_id,
      created_at: message.created_at,
      metadata: message.metadata ? (JSON.parse(message.metadata) as Record<string, unknown>) : null,
    }));
  }
}
