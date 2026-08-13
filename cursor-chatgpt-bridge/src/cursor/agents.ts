import type { ProviderAgentInfo, ProviderRuntime } from "./types.js";

/** Cloud agent IDs are `bc-...`; anything else is a local agent. */
export function runtimeFromAgentId(agentId: string): ProviderRuntime {
  return agentId.startsWith("bc-") ? "cloud" : "local";
}

/** Shape of `SDKAgentInfo` from `@cursor/sdk` (structural subset we consume). */
export interface SdkAgentInfoLike {
  agentId: string;
  name?: string;
  summary?: string;
  status?: "running" | "finished" | "error";
  createdAt?: number;
  lastModified?: number;
  archived?: boolean;
  runtime?: "local" | "cloud";
  repos?: string[];
}

export function mapSdkAgentInfo(info: SdkAgentInfoLike): ProviderAgentInfo {
  return {
    agentId: info.agentId,
    name: info.name,
    status: info.status ?? "unknown",
    runtime: info.runtime ?? runtimeFromAgentId(info.agentId),
    repos: info.repos,
    createdAt: info.createdAt,
    lastModified: info.lastModified,
    archived: info.archived,
  };
}
