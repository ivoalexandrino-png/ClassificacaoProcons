/**
 * Standardized error taxonomy for the bridge.
 *
 * Handlers throw {@link BridgeError} with one of these codes; the MCP and HTTP
 * layers translate them into a consistent, non-leaky JSON envelope. Stack traces
 * are never surfaced to callers.
 */
export const ErrorCodes = {
  UNAUTHORIZED: "UNAUTHORIZED",
  PROJECT_NOT_FOUND: "PROJECT_NOT_FOUND",
  AGENT_NOT_FOUND: "AGENT_NOT_FOUND",
  RUN_NOT_FOUND: "RUN_NOT_FOUND",
  AGENT_BUSY: "AGENT_BUSY",
  CURSOR_API_ERROR: "CURSOR_API_ERROR",
  RUN_TIMEOUT: "RUN_TIMEOUT",
  BLOCKED_BY_POLICY: "BLOCKED_BY_POLICY",
  VALIDATION_ERROR: "VALIDATION_ERROR",
  INTERNAL_ERROR: "INTERNAL_ERROR",
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];

export interface BridgeErrorEnvelope {
  error: {
    code: ErrorCode;
    message: string;
    details: Record<string, unknown>;
  };
}

export class BridgeError extends Error {
  readonly code: ErrorCode;
  readonly details: Record<string, unknown>;

  constructor(code: ErrorCode, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
  }

  toEnvelope(): BridgeErrorEnvelope {
    return {
      error: {
        code: this.code,
        message: this.message,
        details: this.details,
      },
    };
  }
}

/** Convenience constructors for the most common cases. */
export const errors = {
  unauthorized: (message = "Missing or invalid bearer token") =>
    new BridgeError(ErrorCodes.UNAUTHORIZED, message),
  projectNotFound: (details: Record<string, unknown> = {}) =>
    new BridgeError(ErrorCodes.PROJECT_NOT_FOUND, "Project not found", details),
  agentNotFound: (details: Record<string, unknown> = {}) =>
    new BridgeError(ErrorCodes.AGENT_NOT_FOUND, "Cursor agent not found", details),
  runNotFound: (details: Record<string, unknown> = {}) =>
    new BridgeError(ErrorCodes.RUN_NOT_FOUND, "Run not found", details),
  cursorApi: (message: string, details: Record<string, unknown> = {}) =>
    new BridgeError(ErrorCodes.CURSOR_API_ERROR, message, details),
  validation: (message: string, details: Record<string, unknown> = {}) =>
    new BridgeError(ErrorCodes.VALIDATION_ERROR, message, details),
  internal: (message = "Internal error", details: Record<string, unknown> = {}) =>
    new BridgeError(ErrorCodes.INTERNAL_ERROR, message, details),
};

/** Coerce any thrown value into a BridgeError without leaking internals. */
export function toBridgeError(err: unknown): BridgeError {
  if (err instanceof BridgeError) return err;
  if (err instanceof Error && err.name === "ZodError") {
    return new BridgeError(ErrorCodes.VALIDATION_ERROR, "Invalid tool input", {
      issues: safeZodIssues(err),
    });
  }
  const message = err instanceof Error ? err.message : "Unexpected error";
  return new BridgeError(ErrorCodes.INTERNAL_ERROR, message);
}

function safeZodIssues(err: Error): unknown {
  const issues = (err as unknown as { issues?: unknown }).issues;
  return Array.isArray(issues) ? issues : [];
}
