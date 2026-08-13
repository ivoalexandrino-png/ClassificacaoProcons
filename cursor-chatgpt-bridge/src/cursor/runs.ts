import type {
  ProviderGitInfo,
  ProviderRunResult,
  ProviderRunSnapshot,
  ProviderRunStatus,
} from "./types.js";

/** Structural subset of the SDK `Run` / `RunResult` shapes we consume. */
export interface SdkRunLike {
  id: string;
  agentId?: string;
  status: "running" | "finished" | "error" | "cancelled";
  result?: string;
  error?: { message: string; code?: string };
  git?: ProviderGitInfo;
  durationMs?: number;
}

export function mapRunStatus(status: SdkRunLike["status"]): ProviderRunStatus {
  return status === "finished" ? "completed" : status;
}

export function mapSdkRunResult(run: SdkRunLike): ProviderRunResult {
  const status = mapRunStatus(run.status);
  return {
    runId: run.id,
    status: status === "running" ? "error" : status,
    response: run.result,
    errorMessage: run.error?.message,
    git: run.git,
    durationMs: run.durationMs,
  };
}

export function mapSdkRunSnapshot(run: SdkRunLike, agentId: string): ProviderRunSnapshot {
  return {
    runId: run.id,
    agentId: run.agentId ?? agentId,
    status: mapRunStatus(run.status),
    response: run.result,
    errorMessage: run.error?.message,
    git: run.git,
  };
}
