import { Agent } from "@cursor/sdk";
import type { SDKAgent } from "@cursor/sdk";
import { BridgeError } from "../errors.js";
import type { Logger } from "../logger.js";
import type {
  CreateAgentParams,
  CursorAgentProvider,
  ProviderAgentInfo,
  ProviderConversationMessage,
  ProviderRunResult,
  SendFollowUpParams,
} from "./types.js";

function isCloudAgentId(agentId: string): boolean {
  return agentId.startsWith("bc-");
}

function mapRunStatus(
  status: string | undefined,
): ProviderRunResult["status"] {
  switch (status) {
    case "finished":
      return "completed";
    case "error":
      return "error";
    case "cancelled":
      return "cancelled";
    case "running":
      return "running";
    default:
      return status === "timeout" ? "timeout" : "running";
  }
}

async function waitWithTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  onTimeout: () => void,
): Promise<{ timedOut: false; value: T } | { timedOut: true }> {
  let timer: NodeJS.Timeout | undefined;
  try {
    const result = await Promise.race([
      promise.then((value) => ({ timedOut: false as const, value })),
      new Promise<{ timedOut: true }>((resolve) => {
        timer = setTimeout(() => {
          onTimeout();
          resolve({ timedOut: true });
        }, timeoutMs);
      }),
    ]);
    return result;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function extractAssistantText(message: unknown): string {
  if (typeof message === "string") return message;
  if (!message || typeof message !== "object") return JSON.stringify(message);

  const obj = message as Record<string, unknown>;
  if (typeof obj.text === "string") return obj.text;
  if (typeof obj.content === "string") return obj.content;

  if (Array.isArray(obj.content)) {
    return obj.content
      .map((block) => {
        if (!block || typeof block !== "object") return "";
        const b = block as Record<string, unknown>;
        if (b.type === "text" && typeof b.text === "string") return b.text;
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }

  return JSON.stringify(message);
}

export class SdkCursorAgentProvider implements CursorAgentProvider {
  private readonly handles = new Map<string, SDKAgent>();

  constructor(
    private readonly apiKey: string | undefined,
    private readonly defaultModel: string,
    private readonly logger: Logger,
  ) {}

  isConfigured(): boolean {
    return Boolean(this.apiKey);
  }

  private requireApiKey(): string {
    if (!this.apiKey) {
      throw new BridgeError(
        "CURSOR_API_ERROR",
        "CURSOR_API_KEY is not configured",
      );
    }
    return this.apiKey;
  }

  private async getHandle(agentId: string): Promise<SDKAgent> {
    const cached = this.handles.get(agentId);
    if (cached) return cached;

    try {
      const agent = await Agent.resume(agentId, {
        apiKey: this.requireApiKey(),
        model: { id: this.defaultModel },
      });
      this.handles.set(agentId, agent);
      return agent;
    } catch (error) {
      throw new BridgeError(
        "CURSOR_API_ERROR",
        error instanceof Error ? error.message : "Failed to resume agent",
        { agent_id: agentId },
      );
    }
  }

  async createAgent(params: CreateAgentParams): Promise<{
    agentId: string;
    run: ProviderRunResult;
  }> {
    const apiKey = this.requireApiKey();
    const modelId = params.modelId ?? this.defaultModel;
    const startedAt = new Date().toISOString();

    try {
      let agent: SDKAgent;
      if (params.mode === "cloud") {
        if (!params.repository) {
          throw new BridgeError(
            "VALIDATION_ERROR",
            "repository is required for cloud mode",
          );
        }
        agent = await Agent.create({
          apiKey,
          model: { id: modelId },
          name: params.projectName,
          cloud: {
            repos: [
              {
                url: params.repository,
                startingRef: params.startingRef,
              },
            ],
            metadata: params.projectName
              ? { project: params.projectName }
              : undefined,
          },
        });
      } else {
        if (!params.workingDirectory) {
          throw new BridgeError(
            "VALIDATION_ERROR",
            "working_directory is required for local mode",
          );
        }
        agent = await Agent.create({
          apiKey,
          model: { id: modelId },
          name: params.projectName,
          local: {
            cwd: params.workingDirectory,
          },
        });
      }

      this.handles.set(agent.agentId, agent);
      const run = await agent.send(params.message);
      const providerRun = await this.consumeRun(run, {
        waitForCompletion: true,
        timeoutMs: params.timeoutMs ?? 900_000,
        startedAt,
      });

      return { agentId: agent.agentId, run: providerRun };
    } catch (error) {
      if (error instanceof BridgeError) throw error;
      throw new BridgeError(
        "CURSOR_API_ERROR",
        error instanceof Error ? error.message : "Failed to create agent",
      );
    }
  }

  async resumeAndSend(params: SendFollowUpParams): Promise<ProviderRunResult> {
    const startedAt = new Date().toISOString();
    try {
      const agent = await this.getHandle(params.agentId);
      const run = await agent.send(params.message);
      return await this.consumeRun(run, {
        waitForCompletion: params.waitForCompletion,
        timeoutMs: params.timeoutMs,
        startedAt,
      });
    } catch (error) {
      if (error instanceof BridgeError) throw error;
      const message =
        error instanceof Error ? error.message : "Failed to send follow-up";
      if (/busy/i.test(message)) {
        throw new BridgeError("AGENT_BUSY", message, {
          agent_id: params.agentId,
        });
      }
      throw new BridgeError("CURSOR_API_ERROR", message, {
        agent_id: params.agentId,
      });
    }
  }

  private async consumeRun(
    run: Awaited<ReturnType<SDKAgent["send"]>>,
    options: {
      waitForCompletion: boolean;
      timeoutMs: number;
      startedAt: string;
    },
  ): Promise<ProviderRunResult> {
    if (!options.waitForCompletion) {
      return {
        runId: run.id,
        agentId: run.agentId,
        status: "running",
        startedAt: options.startedAt,
      };
    }

    // Drain stream in background so events are not buffered forever.
    const streamTask = (async () => {
      try {
        for await (const _event of run.stream()) {
          // intentionally drain
        }
      } catch {
        // wait() below is authoritative for terminal status
      }
    })();

    const waited = await waitWithTimeout(run.wait(), options.timeoutMs, () => {
      this.logger.warn("cursor_run_wait_timeout", {
        run_id: run.id,
        agent_id: run.agentId,
        timeout_ms: options.timeoutMs,
      });
    });

    void streamTask;

    if (waited.timedOut) {
      return {
        runId: run.id,
        agentId: run.agentId,
        status: "timeout",
        response: run.result,
        startedAt: options.startedAt,
        completedAt: new Date().toISOString(),
      };
    }

    const result = waited.value;
    return {
      runId: result.id,
      agentId: run.agentId,
      status: mapRunStatus(result.status),
      response: result.result,
      error: result.error?.message,
      startedAt: options.startedAt,
      completedAt: new Date().toISOString(),
      durationMs: result.durationMs,
      git: result.git
        ? {
            branches: result.git.branches,
          }
        : undefined,
    };
  }

  async getAgent(agentId: string): Promise<ProviderAgentInfo | null> {
    try {
      const info = await Agent.get(agentId, {
        apiKey: this.requireApiKey(),
      });
      return this.mapAgentInfo(info);
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      if (/not found/i.test(message)) return null;
      throw new BridgeError(
        "CURSOR_API_ERROR",
        message || "Failed to get agent",
        { agent_id: agentId },
      );
    }
  }

  async listAgents(): Promise<ProviderAgentInfo[]> {
    const apiKey = this.requireApiKey();
    const agents: ProviderAgentInfo[] = [];

    try {
      const cloud = await Agent.list({ runtime: "cloud", apiKey, limit: 50 });
      agents.push(...cloud.items.map((item) => this.mapAgentInfo(item)));
    } catch (error) {
      this.logger.warn("cursor_list_cloud_failed", {
        message: error instanceof Error ? error.message : String(error),
      });
    }

    try {
      const local = await Agent.list({ runtime: "local", limit: 50 });
      agents.push(...local.items.map((item) => this.mapAgentInfo(item)));
    } catch (error) {
      this.logger.warn("cursor_list_local_failed", {
        message: error instanceof Error ? error.message : String(error),
      });
    }

    return agents;
  }

  async getRun(
    runId: string,
    agentId?: string,
  ): Promise<ProviderRunResult | null> {
    try {
      const options =
        agentId && isCloudAgentId(agentId)
          ? {
              runtime: "cloud" as const,
              agentId,
              apiKey: this.requireApiKey(),
            }
          : {
              runtime: "local" as const,
              apiKey: this.requireApiKey(),
            };

      const run = await Agent.getRun(runId, options);
      return {
        runId: run.id,
        agentId: run.agentId,
        status: mapRunStatus(run.status),
        response: run.result,
        error: run.error?.message,
        startedAt: run.createdAt
          ? new Date(run.createdAt).toISOString()
          : undefined,
        durationMs: run.durationMs,
        git: run.git ? { branches: run.git.branches } : undefined,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      if (/not found/i.test(message)) return null;
      throw new BridgeError(
        "CURSOR_API_ERROR",
        message || "Failed to get run",
        { run_id: runId, agent_id: agentId },
      );
    }
  }

  async cancelRun(
    runId: string,
    agentId?: string,
  ): Promise<{ supported: true } | { supported: false; reason: string }> {
    try {
      const options =
        agentId && isCloudAgentId(agentId)
          ? {
              runtime: "cloud" as const,
              agentId,
              apiKey: this.requireApiKey(),
            }
          : {
              runtime: "local" as const,
              apiKey: this.requireApiKey(),
            };

      await Agent.cancelRun(runId, options);
      return { supported: true };
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Cancel failed";
      if (/unsupported|not supported/i.test(message)) {
        return { supported: false, reason: message };
      }
      throw new BridgeError("CURSOR_API_ERROR", message, {
        run_id: runId,
        agent_id: agentId,
      });
    }
  }

  async listConversation(
    agentId: string,
    limit = 20,
  ): Promise<ProviderConversationMessage[]> {
    if (isCloudAgentId(agentId)) {
      // Official Agent.messages.list is documented for local agents.
      return [];
    }

    try {
      const messages = await Agent.messages.list(agentId, {
        runtime: "local",
        limit,
      });
      return messages.map((msg) => ({
        role: msg.type,
        content: extractAssistantText(msg.message),
        metadata: { uuid: msg.uuid, source: "cursor_sdk" },
      }));
    } catch (error) {
      this.logger.warn("cursor_messages_list_failed", {
        agent_id: agentId,
        message: error instanceof Error ? error.message : String(error),
      });
      return [];
    }
  }

  private mapAgentInfo(info: {
    agentId: string;
    name?: string;
    summary?: string;
    status?: string;
    lastModified?: number;
    createdAt?: number;
    runtime?: string;
    cwd?: string;
    repos?: string[];
    metadata?: Record<string, string>;
  }): ProviderAgentInfo {
    const mode: ProviderAgentInfo["mode"] =
      info.runtime === "cloud" || isCloudAgentId(info.agentId)
        ? "cloud"
        : info.runtime === "local"
          ? "local"
          : isCloudAgentId(info.agentId)
            ? "cloud"
            : "local";

    return {
      agentId: info.agentId,
      name: info.name,
      summary: info.summary,
      status: info.status,
      mode,
      workingDirectory: info.cwd,
      repositories: info.repos,
      lastActivityAt: info.lastModified
        ? new Date(info.lastModified).toISOString()
        : undefined,
      createdAt: info.createdAt
        ? new Date(info.createdAt).toISOString()
        : undefined,
      metadata: info.metadata,
      capabilities: [
        "send_followup",
        "get_run",
        "cancel_run",
        mode === "local" ? "local_git_changes" : "cloud_git_metadata",
      ],
    };
  }
}

export class MockCursorAgentProvider implements CursorAgentProvider {
  private agents = new Map<string, ProviderAgentInfo>();
  private runs = new Map<string, ProviderRunResult>();
  private conversations = new Map<string, ProviderConversationMessage[]>();
  private active = new Set<string>();
  private cancelSupported = true;
  private configured = true;

  setConfigured(value: boolean): void {
    this.configured = value;
  }

  setCancelSupported(value: boolean): void {
    this.cancelSupported = value;
  }

  isConfigured(): boolean {
    return this.configured;
  }

  async createAgent(params: CreateAgentParams): Promise<{
    agentId: string;
    run: ProviderRunResult;
  }> {
    const agentId =
      params.mode === "cloud"
        ? `bc-mock-${crypto.randomUUID()}`
        : `agent-mock-${crypto.randomUUID()}`;
    const runId = `run-mock-${crypto.randomUUID()}`;
    const now = new Date().toISOString();

    this.agents.set(agentId, {
      agentId,
      name: params.projectName ?? agentId,
      status: "finished",
      mode: params.mode,
      workingDirectory: params.workingDirectory,
      repositories: params.repository ? [params.repository] : [],
      branch: params.startingRef,
      lastActivityAt: now,
      createdAt: now,
      capabilities: ["send_followup", "get_run", "cancel_run"],
    });

    const run: ProviderRunResult = {
      runId,
      agentId,
      status: "completed",
      response: `Mock response to: ${params.message}`,
      startedAt: now,
      completedAt: now,
    };
    this.runs.set(runId, run);
    this.conversations.set(agentId, [
      { role: "user", content: params.message, createdAt: now },
      { role: "assistant", content: run.response ?? "", createdAt: now },
    ]);
    return { agentId, run };
  }

  async resumeAndSend(params: SendFollowUpParams): Promise<ProviderRunResult> {
    if (!this.agents.has(params.agentId)) {
      throw new BridgeError("AGENT_NOT_FOUND", "Cursor agent not found", {
        agent_id: params.agentId,
      });
    }
    if (this.active.has(params.agentId)) {
      throw new BridgeError("AGENT_BUSY", "Agent is busy", {
        agent_id: params.agentId,
      });
    }

    const runId = `run-mock-${crypto.randomUUID()}`;
    const startedAt = new Date().toISOString();

    if (!params.waitForCompletion) {
      const run: ProviderRunResult = {
        runId,
        agentId: params.agentId,
        status: "running",
        startedAt,
      };
      this.runs.set(runId, run);
      this.active.add(params.agentId);
      return run;
    }

    const completedAt = new Date().toISOString();
    const run: ProviderRunResult = {
      runId,
      agentId: params.agentId,
      status: "completed",
      response: `Mock follow-up response to: ${params.message}`,
      startedAt,
      completedAt,
    };
    this.runs.set(runId, run);
    const history = this.conversations.get(params.agentId) ?? [];
    history.push(
      { role: "user", content: params.message, createdAt: startedAt },
      { role: "assistant", content: run.response ?? "", createdAt: completedAt },
    );
    this.conversations.set(params.agentId, history);
    const agent = this.agents.get(params.agentId)!;
    agent.lastActivityAt = completedAt;
    agent.status = "finished";
    return run;
  }

  async getAgent(agentId: string): Promise<ProviderAgentInfo | null> {
    return this.agents.get(agentId) ?? null;
  }

  async listAgents(): Promise<ProviderAgentInfo[]> {
    return [...this.agents.values()];
  }

  async getRun(runId: string): Promise<ProviderRunResult | null> {
    return this.runs.get(runId) ?? null;
  }

  async cancelRun(
    runId: string,
  ): Promise<{ supported: true } | { supported: false; reason: string }> {
    if (!this.cancelSupported) {
      return {
        supported: false,
        reason: "Cancel is not supported by this mock configuration",
      };
    }
    const run = this.runs.get(runId);
    if (!run) {
      throw new BridgeError("RUN_NOT_FOUND", "Run not found", { run_id: runId });
    }
    run.status = "cancelled";
    run.completedAt = new Date().toISOString();
    this.active.delete(run.agentId);
    return { supported: true };
  }

  async listConversation(
    agentId: string,
    limit = 20,
  ): Promise<ProviderConversationMessage[]> {
    const all = this.conversations.get(agentId) ?? [];
    return all.slice(-limit);
  }
}
