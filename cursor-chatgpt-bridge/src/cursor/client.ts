import { BridgeError, ErrorCodes, errors } from "../errors.js";
import type { Logger } from "../logger.js";
import type { AgentMode } from "../storage/types.js";
import { normalizeRun, TIMEOUT, waitWithTimeout, type SdkRunLike } from "./runs.js";
import type {
  CancelResult,
  CancelRunParams,
  CursorAgentProvider,
  GetRunParams,
  ProviderAgentInfo,
  ProviderRun,
  ProviderStartResult,
  SendFollowupParams,
  StartAgentParams,
} from "./types.js";

/**
 * Minimal structural view of the `@cursor/sdk` surface actually used here. Kept
 * local so the rest of the app never imports the SDK types directly, which makes
 * future SDK changes a one-file concern.
 */
interface SdkModule {
  Agent: {
    create(options: Record<string, unknown>): Promise<SdkAgentHandle>;
    resume(agentId: string, options?: Record<string, unknown>): Promise<SdkAgentHandle>;
    get(agentId: string, options?: Record<string, unknown>): Promise<SdkAgentInfo>;
    list(options?: Record<string, unknown>): Promise<{ items: SdkAgentInfo[]; nextCursor?: string }>;
    getRun(runId: string, options?: Record<string, unknown>): Promise<SdkRunHandle>;
    cancelRun(runId: string, options?: Record<string, unknown>): Promise<void>;
  };
  JsonlLocalAgentStore: new (dir: string) => unknown;
}

interface SdkRunHandle extends SdkRunLike {
  wait(): Promise<SdkRunLike>;
  cancel(): Promise<void>;
  supports?(op: string): boolean;
}

interface SdkAgentHandle {
  agentId: string;
  model?: { id?: string };
  send(message: string, options?: Record<string, unknown>): Promise<SdkRunHandle>;
  close?(): void;
}

interface SdkAgentInfo {
  agentId: string;
  name?: string;
  summary?: string;
  status?: string;
  lastModified?: number;
  createdAt?: number;
  runtime?: string;
  repos?: string[];
}

export interface CursorSdkProviderOptions {
  apiKey: string | undefined;
  model: string;
  localStorePath: string;
  logger: Logger;
}

/**
 * {@link CursorAgentProvider} implementation backed by the official
 * `@cursor/sdk`. The SDK is imported lazily so the server can boot (and expose
 * `/health`) without an API key, and so type-only/cloud-only consumers don't pay
 * the local agent import cost.
 */
export class CursorSdkProvider implements CursorAgentProvider {
  readonly configured: boolean;

  private readonly opts: CursorSdkProviderOptions;
  private sdkPromise: Promise<SdkModule> | undefined;
  private localStore: unknown;

  constructor(options: CursorSdkProviderOptions) {
    this.opts = options;
    this.configured = options.apiKey !== undefined;
  }

  private async loadSdk(): Promise<SdkModule> {
    if (!this.opts.apiKey) {
      throw errors.cursorApi("CURSOR_API_KEY is not configured on the bridge");
    }
    if (!this.sdkPromise) {
      this.sdkPromise = import("@cursor/sdk") as unknown as Promise<SdkModule>;
    }
    return this.sdkPromise;
  }

  private async getLocalStore(sdk: SdkModule): Promise<unknown> {
    if (!this.localStore) {
      this.localStore = new sdk.JsonlLocalAgentStore(this.opts.localStorePath);
    }
    return this.localStore;
  }

  private modelSelection(model?: string): { id: string } {
    return { id: model ?? this.opts.model };
  }

  async startAgent(params: StartAgentParams): Promise<ProviderStartResult> {
    const sdk = await this.loadSdk();
    const startedAt = new Date().toISOString();

    const createOptions: Record<string, unknown> = {
      apiKey: this.opts.apiKey,
      model: this.modelSelection(params.model),
    };

    if (params.mode === "local") {
      createOptions.local = {
        cwd: params.workingDirectory ?? process.cwd(),
        store: await this.getLocalStore(sdk),
      };
    } else {
      const repos = params.repository
        ? [{ url: params.repository, startingRef: params.branch }]
        : [];
      createOptions.cloud = { repos, autoCreatePR: false };
    }

    let agent: SdkAgentHandle;
    try {
      agent = await sdk.Agent.create(createOptions);
    } catch (err) {
      throw this.wrapSdkError(err, "Agent.create failed");
    }

    const run = await this.dispatch(agent, params.message, params, startedAt);
    if (params.mode === "local") agent.close?.();

    return {
      agentId: agent.agentId,
      mode: params.mode,
      model: agent.model?.id ?? this.modelSelection(params.model).id,
      run,
    };
  }

  async sendFollowup(params: SendFollowupParams): Promise<ProviderRun> {
    const sdk = await this.loadSdk();
    const startedAt = new Date().toISOString();

    const resumeOptions: Record<string, unknown> = { apiKey: this.opts.apiKey };
    if (params.mode === "local") {
      resumeOptions.local = {
        cwd: params.workingDirectory ?? process.cwd(),
        store: await this.getLocalStore(sdk),
      };
    }

    let agent: SdkAgentHandle;
    try {
      agent = await sdk.Agent.resume(params.agentId, resumeOptions);
    } catch (err) {
      throw this.wrapSdkError(err, "Agent.resume failed");
    }

    const run = await this.dispatch(agent, params.message, params, startedAt);
    if (params.mode === "local") agent.close?.();
    return run;
  }

  private async dispatch(
    agent: SdkAgentHandle,
    message: string,
    params: { model?: string; waitForCompletion: boolean; timeoutMs: number },
    startedAt: string,
  ): Promise<ProviderRun> {
    let run: SdkRunHandle;
    try {
      run = await agent.send(message, { model: this.modelSelection(params.model) });
    } catch (err) {
      throw this.wrapSdkError(err, "agent.send failed");
    }

    if (!params.waitForCompletion) {
      return normalizeRun(run, agent.agentId, startedAt);
    }

    const outcome = await waitWithTimeout(run.wait(), params.timeoutMs);
    if (outcome === TIMEOUT) {
      return {
        runId: run.id,
        agentId: agent.agentId,
        status: "timeout",
        startedAt,
      };
    }
    return normalizeRun(outcome, agent.agentId, startedAt);
  }

  async getRun(params: GetRunParams): Promise<ProviderRun> {
    const sdk = await this.loadSdk();
    const options: Record<string, unknown> =
      params.mode === "cloud"
        ? { runtime: "cloud", agentId: params.agentId, apiKey: this.opts.apiKey }
        : {
            runtime: "local",
            cwd: params.workingDirectory ?? process.cwd(),
            store: await this.getLocalStore(sdk),
          };
    let run: SdkRunHandle;
    try {
      run = await sdk.Agent.getRun(params.runId, options);
    } catch (err) {
      throw this.wrapSdkError(err, "Agent.getRun failed");
    }
    return normalizeRun(run, params.agentId, new Date().toISOString());
  }

  async cancelRun(params: CancelRunParams): Promise<CancelResult> {
    const sdk = await this.loadSdk();
    const options: Record<string, unknown> =
      params.mode === "cloud"
        ? { runtime: "cloud", agentId: params.agentId, apiKey: this.opts.apiKey }
        : {
            runtime: "local",
            cwd: params.workingDirectory ?? process.cwd(),
            store: await this.getLocalStore(sdk),
          };
    try {
      await sdk.Agent.cancelRun(params.runId, options);
      return { supported: true, cancelled: true };
    } catch (err) {
      throw this.wrapSdkError(err, "Agent.cancelRun failed");
    }
  }

  async listCloudAgents(): Promise<ProviderAgentInfo[]> {
    const sdk = await this.loadSdk();
    try {
      const { items } = await sdk.Agent.list({ runtime: "cloud", apiKey: this.opts.apiKey });
      return items.map((info) => this.toProviderInfo(info, "cloud"));
    } catch (err) {
      throw this.wrapSdkError(err, "Agent.list failed");
    }
  }

  async getAgentInfo(agentId: string, mode: AgentMode): Promise<ProviderAgentInfo | null> {
    const sdk = await this.loadSdk();
    const options: Record<string, unknown> =
      mode === "cloud"
        ? { apiKey: this.opts.apiKey }
        : { cwd: process.cwd(), store: await this.getLocalStore(sdk) };
    try {
      const info = await sdk.Agent.get(agentId, options);
      return this.toProviderInfo(info, mode);
    } catch (err) {
      const bridgeErr = this.wrapSdkError(err, "Agent.get failed");
      if (bridgeErr.code === "AGENT_NOT_FOUND") return null;
      throw bridgeErr;
    }
  }

  private toProviderInfo(info: SdkAgentInfo, mode: AgentMode): ProviderAgentInfo {
    return {
      agentId: info.agentId,
      name: info.name,
      summary: info.summary,
      status: info.status,
      mode,
      repository: info.repos?.[0],
      lastActivityAt: info.lastModified
        ? new Date(info.lastModified).toISOString()
        : undefined,
    };
  }

  private wrapSdkError(err: unknown, context: string) {
    const name = err instanceof Error ? err.name : "";
    const message = err instanceof Error ? err.message : String(err);
    this.opts.logger.error("cursor_sdk_error", { context, name });
    if (name === "AgentNotFoundError") {
      return errors.agentNotFound({ context });
    }
    if (name === "AgentBusyError") {
      return new BridgeError(ErrorCodes.AGENT_BUSY, "Cursor agent is busy", { context });
    }
    return errors.cursorApi(`${context}: ${message}`, { name });
  }
}
