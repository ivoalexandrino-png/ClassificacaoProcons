/**
 * `CursorSdkProvider` — the only module that touches `@cursor/sdk` directly.
 *
 * SDK surface used (verified against @cursor/sdk 1.0.x docs):
 *   - Agent.create({ apiKey, local | cloud })  → SDKAgent (agentId, send)
 *   - Agent.resume(agentId, { apiKey, local? }) → SDKAgent (context preserved)
 *   - agent.send(message)                       → Run (id, wait, cancel)
 *   - Agent.list / Agent.get / Agent.getRun / Agent.cancelRun
 *   - Errors: AgentNotFoundError, AgentBusyError, AuthenticationError,
 *             UnsupportedRunOperationError
 */
import {
  Agent,
  AgentBusyError,
  AgentNotFoundError,
  AuthenticationError,
  UnsupportedRunOperationError,
  type SDKAgent,
} from "@cursor/sdk";

import { BridgeError } from "../errors.js";
import { mapSdkAgentInfo, runtimeFromAgentId } from "./agents.js";
import { mapSdkRunResult, mapSdkRunSnapshot, type SdkRunLike } from "./runs.js";
import type {
  CreateAgentOptions,
  CursorAgentProvider,
  ProviderAgentInfo,
  ProviderRunHandle,
  ProviderRunSnapshot,
  SendFollowupOptions,
} from "./types.js";

function mapSdkError(err: unknown, agentId?: string): never {
  if (err instanceof BridgeError) throw err;
  if (err instanceof AgentNotFoundError) {
    throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", { agent_id: agentId });
  }
  if (err instanceof AgentBusyError) {
    throw new BridgeError("AGENT_BUSY", "Cursor agent already has an active run", {
      agent_id: agentId,
    });
  }
  if (err instanceof AuthenticationError) {
    throw new BridgeError("CURSOR_API_ERROR", "Cursor API authentication failed", {
      hint: "Check CURSOR_API_KEY",
    });
  }
  const message = err instanceof Error ? err.message : String(err);
  throw new BridgeError("CURSOR_API_ERROR", `Cursor SDK error: ${message}`, {
    agent_id: agentId,
  });
}

export class CursorSdkProvider implements CursorAgentProvider {
  private readonly apiKey: string | undefined;
  private readonly handles = new Map<string, SDKAgent>();

  constructor(apiKey: string | undefined) {
    this.apiKey = apiKey;
  }

  get configured(): boolean {
    return Boolean(this.apiKey);
  }

  private requireApiKey(): string {
    if (!this.apiKey) {
      throw new BridgeError("NOT_CONFIGURED", "CURSOR_API_KEY is not configured", {
        hint: "Set CURSOR_API_KEY in the bridge environment",
      });
    }
    return this.apiKey;
  }

  private async resumeAgent(agentId: string, options?: SendFollowupOptions): Promise<SDKAgent> {
    const cached = this.handles.get(agentId);
    if (cached) return cached;
    const apiKey = this.requireApiKey();
    try {
      const resumeOptions: Record<string, unknown> = { apiKey };
      if (runtimeFromAgentId(agentId) === "local" && options?.workingDirectory) {
        resumeOptions.local = { cwd: options.workingDirectory };
      }
      const agent = await Agent.resume(agentId, resumeOptions);
      this.handles.set(agentId, agent);
      return agent;
    } catch (err) {
      mapSdkError(err, agentId);
    }
  }

  async createAgent(
    options: CreateAgentOptions,
  ): Promise<{ agent: ProviderAgentInfo; run: ProviderRunHandle }> {
    const apiKey = this.requireApiKey();
    try {
      const agentOptions: Record<string, unknown> = { apiKey };
      if (options.mode === "local") {
        agentOptions.local = { cwd: options.workingDirectory };
      } else {
        agentOptions.cloud = {
          repos: options.repository
            ? [
                {
                  url: options.repository,
                  ...(options.branch ? { startingRef: options.branch } : {}),
                },
              ]
            : [],
        };
      }
      const agent = await Agent.create(agentOptions as Parameters<typeof Agent.create>[0]);
      this.handles.set(agent.agentId, agent);
      const run = await agent.send(options.message);
      return {
        agent: {
          agentId: agent.agentId,
          runtime: options.mode,
          status: "running",
          repos: options.repository ? [options.repository] : undefined,
        },
        run: this.wrapRun(run, agent.agentId),
      };
    } catch (err) {
      mapSdkError(err);
    }
  }

  async sendFollowup(
    agentId: string,
    message: string,
    options?: SendFollowupOptions,
  ): Promise<ProviderRunHandle> {
    const agent = await this.resumeAgent(agentId, options);
    try {
      const run = await agent.send(message);
      return this.wrapRun(run, agentId);
    } catch (err) {
      mapSdkError(err, agentId);
    }
  }

  private wrapRun(
    run: { id: string; wait(): Promise<unknown> },
    agentId: string,
  ): ProviderRunHandle {
    return {
      runId: run.id,
      agentId,
      wait: async () => {
        try {
          const result = (await run.wait()) as SdkRunLike & { id: string };
          return mapSdkRunResult(result);
        } catch (err) {
          mapSdkError(err, agentId);
        }
      },
    };
  }

  async listAgents(limit = 50): Promise<ProviderAgentInfo[]> {
    const apiKey = this.requireApiKey();
    try {
      const { items } = await Agent.list({ runtime: "cloud", limit, apiKey });
      return items.map(mapSdkAgentInfo);
    } catch (err) {
      mapSdkError(err);
    }
  }

  async getAgent(agentId: string): Promise<ProviderAgentInfo> {
    const apiKey = this.requireApiKey();
    try {
      const info = await Agent.get(agentId, { apiKey });
      return mapSdkAgentInfo(info);
    } catch (err) {
      mapSdkError(err, agentId);
    }
  }

  async getRun(agentId: string, runId: string): Promise<ProviderRunSnapshot> {
    const apiKey = this.requireApiKey();
    try {
      const run =
        runtimeFromAgentId(agentId) === "cloud"
          ? await Agent.getRun(runId, { runtime: "cloud", agentId, apiKey })
          : await Agent.getRun(runId, {});
      return mapSdkRunSnapshot(run as unknown as SdkRunLike, agentId);
    } catch (err) {
      mapSdkError(err, agentId);
    }
  }

  async cancelRun(
    agentId: string,
    runId: string,
  ): Promise<{ supported: boolean; reason?: string }> {
    const apiKey = this.requireApiKey();
    try {
      if (runtimeFromAgentId(agentId) === "cloud") {
        await Agent.cancelRun(runId, { runtime: "cloud", agentId, apiKey });
      } else {
        await Agent.cancelRun(runId, {});
      }
      return { supported: true };
    } catch (err) {
      if (err instanceof UnsupportedRunOperationError) {
        return {
          supported: false,
          reason: `Cancellation is not supported for this run: ${err.message}`,
        };
      }
      mapSdkError(err, agentId);
    }
  }
}
