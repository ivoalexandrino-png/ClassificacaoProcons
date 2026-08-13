import type { AgentMode, MessageRole } from "../storage/types.js";

export interface ProviderAgent {
  agentId: string;
  mode: AgentMode;
  capabilities: {
    followup: boolean;
    conversation: boolean;
    cancel: boolean;
    localChanges: boolean;
  };
  metadata: Record<string, unknown>;
}

export interface ProviderMessage {
  role: MessageRole;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface ProviderRunResult {
  runId: string;
  status: "completed" | "error" | "cancelled";
  response: string | null;
  error: string | null;
  messages: ProviderMessage[];
  metadata: Record<string, unknown>;
}

export interface ProviderRun {
  runId: string;
  agentId: string;
  status: "running" | "completed" | "error" | "cancelled";
  supportsCancel: boolean;
  wait(): Promise<ProviderRunResult>;
  cancel(): Promise<void>;
}

export interface CreateAgentRequest {
  mode: AgentMode;
  repository: string;
  workingDirectory: string;
  branch: string;
  project: string;
}

export interface AgentRuntimeContext {
  mode: AgentMode;
  workingDirectory: string;
}

export interface CursorAgentProvider {
  isConfigured(): boolean;
  createAgent(request: CreateAgentRequest): Promise<ProviderAgent>;
  sendMessage(
    agentId: string,
    message: string,
    context: AgentRuntimeContext,
  ): Promise<ProviderRun>;
  getRun(
    agentId: string,
    runId: string,
    context: AgentRuntimeContext,
  ): Promise<ProviderRun>;
  cancelRun(
    agentId: string,
    runId: string,
    context: AgentRuntimeContext,
  ): Promise<{ supported: boolean; reason?: string }>;
}
