import type { RunStatus } from "../storage/types.js";
import type { ProviderRun } from "./types.js";

/** SDK run status → bridge run status. */
export function mapSdkStatus(status: string | undefined): RunStatus {
  switch (status) {
    case "finished":
      return "completed";
    case "running":
      return "running";
    case "error":
      return "error";
    case "cancelled":
      return "cancelled";
    default:
      return "running";
  }
}

/** Shape shared by the SDK `Run` handle and `RunResult`. */
export interface SdkRunLike {
  id: string;
  agentId?: string;
  status?: string;
  result?: string;
  error?: { message: string; code?: string };
  git?: { branches?: { repoUrl: string; branch?: string; prUrl?: string }[] };
  createdAt?: number;
}

export function normalizeRun(
  run: SdkRunLike,
  agentId: string,
  startedAt: string,
): ProviderRun {
  const status = mapSdkStatus(run.status);
  const terminal = status !== "running";
  return {
    runId: run.id,
    agentId: run.agentId ?? agentId,
    status,
    response: run.result,
    error: run.error?.message,
    startedAt,
    completedAt: terminal ? new Date().toISOString() : undefined,
    git: run.git?.branches?.map((b) => ({
      repoUrl: b.repoUrl,
      branch: b.branch,
      prUrl: b.prUrl,
    })),
  };
}

const TIMEOUT = Symbol("run-timeout");

/**
 * Await `promise`, resolving to the timeout sentinel if it does not settle in
 * `timeoutMs`. The underlying run is deliberately NOT cancelled on timeout so
 * the caller can keep the run id and query it later.
 */
export async function waitWithTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
): Promise<T | typeof TIMEOUT> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<typeof TIMEOUT>((resolve) => {
    timer = setTimeout(() => resolve(TIMEOUT), timeoutMs);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export { TIMEOUT };
