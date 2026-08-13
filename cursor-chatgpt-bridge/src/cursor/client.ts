import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { promisify } from "node:util";
import type { AppConfig } from "../config.js";
import { BridgeError } from "../errors.js";
import type { Logger } from "../logger.js";
import type {
  AgentDetails,
  AgentMode,
  AgentSummary,
  CancelRunResult,
  CreateAgentInput,
  CursorAgentProvider,
  RunDetails,
  SendMessageInput,
} from "./types.js";

const execFileAsync = promisify(execFile);

type SdkAgent = {
  agentId: string;
  send: (message: string | { text: string }) => Promise<SdkRun>;
  close?: () => void;
};

type SdkRun = {
  id: string;
  agentId: string;
  status: string;
  result?: string;
  error?: { message: string; code?: string };
  wait: () => Promise<SdkRunResult>;
  cancel: () => Promise<void>;
  stream: () => AsyncGenerator<SdkMessage>;
};

type SdkRunResult = {
  id: string;
  status: "finished" | "error" | "cancelled";
  result?: string;
  error?: { message: string; code?: string };
};

type SdkMessage = {
  type: string;
  text?: string;
  name?: string;
  status?: string;
  message?: { content?: Array<{ type: string; text?: string }> };
};

type SdkModule = {
  Agent: {
    create: (options: Record<string, unknown>) => Promise<SdkAgent>;
    resume: (agentId: string, options?: Record<string, unknown>) => Promise<SdkAgent>;
    list: (options?: Record<string, unknown>) => Promise<{ items: SdkAgentInfo[] }>;
    get: (agentId: string, options?: Record<string, unknown>) => Promise<SdkAgentInfo>;
    getRun: (runId: string, options?: Record<string, unknown>) => Promise<SdkRun>;
    cancelRun: (runId: string, options?: Record<string, unknown>) => Promise<void>;
  };
};

type SdkAgentInfo = {
  agentId: string;
  name?: string;
  status?: string;
  updatedAt?: number;
  createdAt?: number;
};

function mapRunStatus(status: string): RunDetails["status"] {
  switch (status) {
    case "running":
    case "CREATING":
    case "RUNNING":
      return "running";
    case "finished":
    case "FINISHED":
    case "COMPLETED":
      return "completed";
    case "error":
    case "ERROR":
    case "FAILED":
      return "error";
    case "cancelled":
    case "CANCELLED":
      return "cancelled";
    case "timeout":
      return "timeout";
    default:
      return "running";
  }
}

function isCloudAgent(agentId: string): boolean {
  return agentId.startsWith("bc-");
}

function extractAssistantText(events: SdkMessage[]): string {
  const chunks: string[] = [];
  for (const event of events) {
    if (event.type === "assistant" && event.message?.content) {
      for (const block of event.message.content) {
        if (block.type === "text" && block.text) {
          chunks.push(block.text);
        }
      }
    }
    if (event.type === "thinking" && event.text) {
      chunks.push(event.text);
    }
  }
  return chunks.join("");
}

export class CursorSdkProvider implements CursorAgentProvider {
  private sdk: SdkModule | null = null;
  private readonly agentHandles = new Map<string, SdkAgent>();

  constructor(
    private readonly config: AppConfig,
    private readonly logger: Logger,
  ) {}

  private async loadSdk(): Promise<SdkModule> {
    if (this.sdk) {
      return this.sdk;
    }
    try {
      const imported = await import("@cursor/sdk");
      this.sdk = imported as SdkModule;
      return this.sdk;
    } catch (error) {
      throw new BridgeError(
        "CURSOR_API_ERROR",
        "Failed to load @cursor/sdk. Ensure Node.js >= 22.13 and the package is installed.",
        { cause: error instanceof Error ? error.message : String(error) },
      );
    }
  }

  private requireApiKey(): string {
    const key = this.config.cursorApiKey?.trim();
    if (!key) {
      throw new BridgeError(
        "CURSOR_API_ERROR",
        "CURSOR_API_KEY is not configured. Set it in the environment to use Cursor agents.",
      );
    }
    return key;
  }

  private baseOptions(workingDirectory?: string): Record<string, unknown> {
    return {
      apiKey: this.requireApiKey(),
      model: { id: this.config.defaultModel },
      ...(workingDirectory ? { local: { cwd: workingDirectory } } : {}),
    };
  }

  private async getOrResumeAgent(
    agentId: string,
    workingDirectory?: string,
  ): Promise<SdkAgent> {
    const cached = this.agentHandles.get(agentId);
    if (cached) {
      return cached;
    }

    const sdk = await this.loadSdk();
    const options = this.baseOptions(workingDirectory);
    const agent = await sdk.Agent.resume(agentId, options);
    this.agentHandles.set(agentId, agent);
    return agent;
  }

  async listAgentsFromCursor(options?: {
    mode?: AgentMode;
    workingDirectory?: string;
  }): Promise<AgentSummary[]> {
    const sdk = await this.loadSdk();
    const mode = options?.mode ?? "local";
    const listOptions: Record<string, unknown> = {
      limit: 100,
    };

    if (mode === "cloud") {
      listOptions.runtime = "cloud";
      listOptions.apiKey = this.requireApiKey();
    } else {
      listOptions.runtime = "local";
      if (options?.workingDirectory) {
        listOptions.cwd = options.workingDirectory;
      }
    }

    const { items } = await sdk.Agent.list(listOptions);
    return items.map((item) => ({
      agent_id: item.agentId,
      status: item.status ?? "unknown",
      last_activity_at: item.updatedAt
        ? new Date(item.updatedAt).toISOString()
        : new Date().toISOString(),
      mode: isCloudAgent(item.agentId) ? "cloud" : "local",
    }));
  }

  async getAgentFromCursor(
    agentId: string,
    options?: { workingDirectory?: string },
  ): Promise<AgentSummary | undefined> {
    const sdk = await this.loadSdk();
    try {
      const info = await sdk.Agent.get(agentId, {
        ...this.baseOptions(options?.workingDirectory),
      });
      return {
        agent_id: info.agentId,
        status: info.status ?? "unknown",
        last_activity_at: info.updatedAt
          ? new Date(info.updatedAt).toISOString()
          : new Date().toISOString(),
        mode: isCloudAgent(info.agentId) ? "cloud" : "local",
      };
    } catch {
      return undefined;
    }
  }

  async createAgent(input: CreateAgentInput): Promise<{ agentId: string; runId: string }> {
    const sdk = await this.loadSdk();
    const options: Record<string, unknown> = {
      apiKey: this.requireApiKey(),
      model: { id: input.model ?? this.config.defaultModel },
    };

    if (input.mode === "cloud") {
      if (!input.repository) {
        throw new BridgeError(
          "VALIDATION_ERROR",
          "repository is required for cloud agents",
        );
      }
      options.cloud = {
        repos: [
          {
            url: input.repository,
            startingRef: input.branch ?? "main",
          },
        ],
      };
    } else {
      const cwd = input.workingDirectory;
      if (!cwd || !existsSync(cwd)) {
        throw new BridgeError(
          "VALIDATION_ERROR",
          "working_directory must exist for local agents",
          { working_directory: cwd },
        );
      }
      options.local = { cwd };
    }

    const agent = await sdk.Agent.create(options);
    this.agentHandles.set(agent.agentId, agent);

    const run = await agent.send(input.message);
    return { agentId: agent.agentId, runId: run.id };
  }

  async resumeAgent(agentId: string, options?: { workingDirectory?: string }): Promise<void> {
    await this.getOrResumeAgent(agentId, options?.workingDirectory);
  }

  private async waitForSdkRun(
    run: SdkRun,
    agentId: string,
    startedAt: string,
    timeoutMs: number,
  ): Promise<RunDetails> {
    const events: SdkMessage[] = [];

    const waitPromise = (async (): Promise<SdkRunResult> => {
      for await (const event of run.stream()) {
        events.push(event as SdkMessage);
      }
      return run.wait();
    })();

    const timeoutPromise = new Promise<"timeout">((resolve) => {
      setTimeout(() => resolve("timeout"), timeoutMs);
    });

    const outcome = await Promise.race([waitPromise, timeoutPromise]);

    if (outcome === "timeout") {
      return {
        run_id: run.id,
        agent_id: agentId,
        status: "timeout",
        response: extractAssistantText(events),
        started_at: startedAt,
        error: "Run exceeded configured timeout",
      };
    }

    const result = outcome;
    const response = result.result ?? extractAssistantText(events);
    return {
      run_id: run.id,
      agent_id: agentId,
      status: mapRunStatus(result.status),
      response,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      error: result.error?.message ?? null,
    };
  }

  async sendMessage(input: SendMessageInput): Promise<RunDetails> {
    const agent = await this.getOrResumeAgent(input.agentId, input.workingDirectory);
    const startedAt = new Date().toISOString();

    try {
      const run = await agent.send(input.message);

      if (!input.waitForCompletion) {
        void this.waitForSdkRun(run, input.agentId, startedAt, input.timeoutMs).then((result) => {
          this.logger.info("cursor_run_background_completed", {
            agent_id: input.agentId,
            run_id: run.id,
            status: result.status,
          });
        }).catch((error) => {
          this.logger.error("cursor_run_background_failed", {
            agent_id: input.agentId,
            run_id: run.id,
            error: error instanceof Error ? error.message : String(error),
          });
        });

        return {
          run_id: run.id,
          agent_id: input.agentId,
          status: "running",
          started_at: startedAt,
        };
      }

      return await this.waitForSdkRun(run, input.agentId, startedAt, input.timeoutMs);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (message.toLowerCase().includes("busy")) {
        throw new BridgeError("AGENT_BUSY", "Agent is busy with another run", {
          agent_id: input.agentId,
        });
      }
      throw new BridgeError("CURSOR_API_ERROR", message, { agent_id: input.agentId });
    }
  }

  async waitForRunCompletion(
    agentId: string,
    runId: string,
    options?: { workingDirectory?: string; timeoutMs?: number },
  ): Promise<RunDetails> {
    const sdk = await this.loadSdk();
    const getRunOptions: Record<string, unknown> = isCloudAgent(agentId)
      ? { runtime: "cloud", agentId, apiKey: this.requireApiKey() }
      : { runtime: "local", ...this.baseOptions(options?.workingDirectory) };

    const run = await sdk.Agent.getRun(runId, getRunOptions);
    return this.waitForSdkRun(
      run,
      agentId,
      new Date().toISOString(),
      options?.timeoutMs ?? this.config.runTimeoutMs,
    );
  }

  async getRun(
    agentId: string,
    runId: string,
    options?: { workingDirectory?: string },
  ): Promise<RunDetails> {
    const sdk = await this.loadSdk();
    const getRunOptions: Record<string, unknown> = isCloudAgent(agentId)
      ? { runtime: "cloud", agentId, apiKey: this.requireApiKey() }
      : { runtime: "local", ...this.baseOptions(options?.workingDirectory) };

    const run = await sdk.Agent.getRun(runId, getRunOptions);
    return {
      run_id: run.id,
      agent_id: agentId,
      status: mapRunStatus(run.status),
      response: run.result,
      started_at: new Date().toISOString(),
      error: run.error?.message ?? null,
    };
  }

  async cancelRun(
    agentId: string,
    runId: string,
    options?: { workingDirectory?: string },
  ): Promise<CancelRunResult> {
    const sdk = await this.loadSdk();
    try {
      const cancelOptions: Record<string, unknown> = isCloudAgent(agentId)
        ? { runtime: "cloud", agentId, apiKey: this.requireApiKey() }
        : { runtime: "local", ...this.baseOptions(options?.workingDirectory) };

      await sdk.Agent.cancelRun(runId, cancelOptions);
      return {
        supported: true,
        run_id: runId,
        status: "cancelled",
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (
        message.includes("not supported") ||
        message.includes("unsupported") ||
        message.includes("not cancellable")
      ) {
        return {
          supported: false,
          reason: message,
        };
      }
      throw new BridgeError("CURSOR_API_ERROR", message, { run_id: runId });
    }
  }
}

export async function getGitChanges(
  workingDirectory: string,
  maxDiffChars = 30000,
): Promise<{
  branch: string;
  clean: boolean;
  files: string[];
  diff_stat: string;
  diff: string;
}> {
  if (!existsSync(workingDirectory)) {
    throw new BridgeError("VALIDATION_ERROR", "Working directory does not exist", {
      working_directory: workingDirectory,
    });
  }

  const branch = (
    await execFileAsync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
      cwd: workingDirectory,
    })
  ).stdout.trim();

  const statusOutput = (
    await execFileAsync("git", ["status", "--porcelain"], { cwd: workingDirectory })
  ).stdout.trim();

  const files = statusOutput
    ? statusOutput
        .split("\n")
        .map((line) => line.slice(3).trim())
        .filter(Boolean)
    : [];

  const diffStat = (
    await execFileAsync("git", ["diff", "--stat"], { cwd: workingDirectory })
  ).stdout.trim();

  let diff = (
    await execFileAsync("git", ["diff"], { cwd: workingDirectory })
  ).stdout;

  if (diff.length > maxDiffChars) {
    diff = `${diff.slice(0, maxDiffChars)}\n… [truncated]`;
  }

  return {
    branch,
    clean: files.length === 0,
    files,
    diff_stat: diffStat,
    diff,
  };
}

export function buildAgentDetails(
  record: {
    agent_id: string;
    project_id: string | null;
    mode: AgentMode;
    branch: string | null;
    status: string;
    working_directory: string | null;
    repository: string | null;
    last_activity_at: string;
    metadata: string | null;
  },
  projectName?: string,
  activeRunId?: string,
): AgentDetails {
  let metadata: Record<string, unknown> | undefined;
  if (record.metadata) {
    try {
      metadata = JSON.parse(record.metadata) as Record<string, unknown>;
    } catch {
      metadata = undefined;
    }
  }

  return {
    agent_id: record.agent_id,
    project: projectName,
    repository: record.repository ?? undefined,
    branch: record.branch ?? undefined,
    status: record.status,
    last_activity_at: record.last_activity_at,
    mode: record.mode,
    working_directory: record.working_directory ?? undefined,
    active_run_id: activeRunId,
    metadata,
    capabilities: {
      cancel_run: true,
      get_changes: record.mode === "local" && Boolean(record.working_directory),
      conversation_history: true,
    },
  };
}
