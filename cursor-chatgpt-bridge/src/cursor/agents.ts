import type { BridgeStore } from "../storage/store.js";
import type { AgentRecord } from "../storage/types.js";
import { buildAgentDetails } from "./client.js";
import type { AgentDetails, AgentMode, AgentSummary } from "./types.js";

export class AgentService {
  constructor(private readonly store: BridgeStore) {}

  listKnownAgents(): AgentSummary[] {
    const projects = this.store.listProjects();
    const projectById = new Map(projects.map((p) => [p.id, p.name]));

    return this.store.listAgents().map((agent) => ({
      agent_id: agent.agent_id,
      project: agent.project_id ? projectById.get(agent.project_id) : undefined,
      repository: agent.repository ?? undefined,
      branch: agent.branch ?? undefined,
      status: agent.status,
      last_activity_at: agent.last_activity_at,
      mode: agent.mode,
      working_directory: agent.working_directory ?? undefined,
    }));
  }

  getAgentDetails(agentId: string): AgentDetails | undefined {
    const agent = this.store.getAgent(agentId);
    if (!agent) {
      return undefined;
    }
    const project = agent.project_id
      ? this.store.getProjectById(agent.project_id)
      : undefined;
    const activeRun = this.store.getActiveRunForAgent(agentId);
    return buildAgentDetails(agent, project?.name, activeRun?.run_id);
  }

  registerAgentFromCursor(
    agentId: string,
    input: {
      project_id?: string | null;
      mode: AgentMode;
      branch?: string | null;
      status: string;
      working_directory?: string | null;
      repository?: string | null;
      metadata?: Record<string, unknown>;
    },
  ): AgentRecord {
    return this.store.upsertAgent({
      agent_id: agentId,
      ...input,
    });
  }
}
