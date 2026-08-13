import { Agent } from "@cursor/sdk";
import type { ConversationTurn, Run, SDKAgent } from "@cursor/sdk";
import { BridgeError } from "../errors.js";
import type {
  AgentRuntimeContext,
  CreateAgentRequest,
  CursorAgentProvider,
  ProviderAgent,
  ProviderMessage,
  ProviderRun,
  ProviderRunResult,
} from "./types.js";

function statusOf(status: Run["status"]): ProviderRun["status"] {
  if (status === "finished") return "completed";
  return status;
}

function terminalStatus(
  status: "finished" | "error" | "cancelled",
): ProviderRunResult["status"] {
  return status === "finished" ? "completed" : status;
}

function limitedJson(value: unknown, maxCharacters = 10_000): string {
  const serialized = JSON.stringify(value);
  if (!serialized) return "";
  if (serialized.length <= maxCharacters) return serialized;
  return `${serialized.slice(0, maxCharacters)}…[truncated]`;
}

function conversationMessages(turns: ConversationTurn[]): ProviderMessage[] {
  const messages: ProviderMessage[] = [];
  for (const item of turns) {
    if (item.type === "shellConversationTurn") {
      messages.push({
        role: "tool",
        content: limitedJson(item.turn),
        metadata: { type: "shellConversationTurn" },
      });
      continue;
    }
    for (const step of item.turn.steps) {
      if (step.type === "toolCall") {
        messages.push({
          role: "tool",
          content: limitedJson(step.message),
          metadata: { type: "toolCall" },
        });
      }
    }
  }
  return messages;
}

export class CursorSdkProvider implements CursorAgentProvider {
  constructor(
    private readonly apiKey: string | undefined,
    private readonly model: string,
  ) {}

  isConfigured(): boolean {
    return Boolean(this.apiKey ?? process.env.CURSOR_API_KEY);
  }

  async createAgent(request: CreateAgentRequest): Promise<ProviderAgent> {
    try {
      const common = {
        apiKey: this.apiKey,
        model: { id: this.model },
      };
      const agent =
        request.mode === "local"
          ? await Agent.create({
              ...common,
              local: { cwd: request.workingDirectory },
            })
          : await Agent.create({
              ...common,
              cloud: {
                repos: [{ url: request.repository, startingRef: request.branch }],
                autoCreatePR: false,
                metadata: {
                  bridge_project: request.project,
                  bridge_repository: request.repository,
                },
              },
            });
      const result: ProviderAgent = {
        agentId: agent.agentId,
        mode: request.mode,
        capabilities: {
          followup: true,
          conversation: true,
          cancel: true,
          localChanges: request.mode === "local",
        },
        metadata: { model: this.model },
      };
      agent.close();
      return result;
    } catch (error) {
      throw this.cursorError("Unable to create Cursor agent", error);
    }
  }

  async sendMessage(
    agentId: string,
    message: string,
    context: AgentRuntimeContext,
  ): Promise<ProviderRun> {
    let agent: SDKAgent | undefined;
    try {
      agent = await Agent.resume(agentId, {
        apiKey: this.apiKey,
        model: { id: this.model },
        ...(context.mode === "local"
          ? { local: { cwd: context.workingDirectory } }
          : {}),
      });
      const run = await agent.send(message);
      return this.wrapRun(run, agent);
    } catch (error) {
      agent?.close();
      throw this.cursorError("Unable to send prompt to Cursor agent", error);
    }
  }

  async getRun(
    agentId: string,
    runId: string,
    context: AgentRuntimeContext,
  ): Promise<ProviderRun> {
    try {
      const run = await Agent.getRun(
        runId,
        context.mode === "cloud"
          ? { runtime: "cloud", agentId, apiKey: this.apiKey }
          : { runtime: "local", cwd: context.workingDirectory },
      );
      return this.wrapRun(run);
    } catch (error) {
      throw this.cursorError("Unable to read Cursor run", error);
    }
  }

  async cancelRun(
    agentId: string,
    runId: string,
    context: AgentRuntimeContext,
  ): Promise<{ supported: boolean; reason?: string }> {
    try {
      const run = await this.getRun(agentId, runId, context);
      if (!run.supportsCancel) {
        return { supported: false, reason: "Cursor SDK reports that this run cannot be cancelled" };
      }
      await run.cancel();
      return { supported: true };
    } catch (error) {
      if (error instanceof BridgeError) throw error;
      throw this.cursorError("Unable to cancel Cursor run", error);
    }
  }

  private wrapRun(run: Run, agent?: SDKAgent): ProviderRun {
    let waitPromise: Promise<ProviderRunResult> | undefined;
    return {
      runId: run.id,
      agentId: run.agentId,
      status: statusOf(run.status),
      supportsCancel: run.supports("cancel"),
      wait: () => {
        waitPromise ??= this.waitForRun(run).finally(() => agent?.close());
        return waitPromise;
      },
      cancel: async () => {
        try {
          await run.cancel();
        } finally {
          agent?.close();
        }
      },
    };
  }

  private async waitForRun(run: Run): Promise<ProviderRunResult> {
    const result = await run.wait();
    let messages: ProviderMessage[] = [];
    if (run.supports("conversation")) {
      try {
        messages = conversationMessages(await run.conversation());
      } catch {
        messages = [];
      }
    }
    return {
      runId: result.id,
      status: terminalStatus(result.status),
      response: result.result ?? null,
      error: result.error?.message ?? null,
      messages,
      metadata: {
        request_id: result.requestId,
        duration_ms: result.durationMs,
        git: result.git,
        model: result.model,
        usage: result.usage,
      },
    };
  }

  private cursorError(message: string, error: unknown): BridgeError {
    const reason = error instanceof Error ? error.message : "Unknown Cursor SDK error";
    return new BridgeError("CURSOR_API_ERROR", message, { reason }, 502);
  }
}
