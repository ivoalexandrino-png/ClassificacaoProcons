/**
 * In-process lock per agent_id so the bridge never sends two concurrent
 * follow-ups to the same agent. The Cursor API also rejects concurrent runs
 * (409 agent_busy); this lock lets us answer with a clean `busy` payload
 * before ever hitting the API.
 */
export class AgentLocks {
  private readonly active = new Map<string, string>();

  /** Returns true if the lock was acquired; false when the agent is busy. */
  acquire(agentId: string, runId: string): boolean {
    if (this.active.has(agentId)) return false;
    this.active.set(agentId, runId);
    return true;
  }

  release(agentId: string, runId?: string): void {
    if (runId === undefined || this.active.get(agentId) === runId) {
      this.active.delete(agentId);
    }
  }

  activeRunId(agentId: string): string | undefined {
    return this.active.get(agentId);
  }

  isBusy(agentId: string): boolean {
    return this.active.has(agentId);
  }
}
