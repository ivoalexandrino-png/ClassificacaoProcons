export class AgentLock {
  private readonly activeRuns = new Map<string, string>();

  acquire(agentId: string, runId: string): boolean {
    if (this.activeRuns.has(agentId)) return false;
    this.activeRuns.set(agentId, runId);
    return true;
  }

  replace(agentId: string, currentRunId: string, nextRunId: string): boolean {
    if (this.activeRuns.get(agentId) !== currentRunId) return false;
    this.activeRuns.set(agentId, nextRunId);
    return true;
  }

  release(agentId: string, runId: string): void {
    if (this.activeRuns.get(agentId) === runId) {
      this.activeRuns.delete(agentId);
    }
  }

  getActiveRun(agentId: string): string | undefined {
    return this.activeRuns.get(agentId);
  }
}
