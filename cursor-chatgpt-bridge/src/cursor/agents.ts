/**
 * Per-agent concurrency control.
 *
 * The bridge forbids two concurrent runs for the same agent (Cursor cloud agents
 * reject it too). A lightweight in-process lock keyed by `agentId` gives a fast,
 * safe "busy" answer for the MVP without a queueing subsystem.
 */
export class AgentLockManager {
  private readonly active = new Map<string, string>();

  /** Try to acquire the lock. Returns the active run id if already locked. */
  tryAcquire(agentId: string, runId: string): { acquired: boolean; activeRunId?: string } {
    const current = this.active.get(agentId);
    if (current) {
      return { acquired: false, activeRunId: current };
    }
    this.active.set(agentId, runId);
    return { acquired: true };
  }

  release(agentId: string): void {
    this.active.delete(agentId);
  }

  isLocked(agentId: string): boolean {
    return this.active.has(agentId);
  }

  activeRunId(agentId: string): string | undefined {
    return this.active.get(agentId);
  }
}
