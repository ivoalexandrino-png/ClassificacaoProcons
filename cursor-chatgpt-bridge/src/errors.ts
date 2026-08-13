export type ErrorCode =
  | "UNAUTHORIZED"
  | "PROJECT_NOT_FOUND"
  | "AGENT_NOT_FOUND"
  | "RUN_NOT_FOUND"
  | "AGENT_BUSY"
  | "CURSOR_API_ERROR"
  | "RUN_TIMEOUT"
  | "BLOCKED_BY_POLICY"
  | "INTERNAL_ERROR"
  | "VALIDATION_ERROR"
  | "NOT_SUPPORTED";

export class BridgeError extends Error {
  readonly code: ErrorCode;
  readonly details: Record<string, unknown>;
  readonly httpStatus: number;

  constructor(
    code: ErrorCode,
    message: string,
    details: Record<string, unknown> = {},
    httpStatus?: number,
  ) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.details = details;
    this.httpStatus = httpStatus ?? defaultHttpStatus(code);
  }
}

function defaultHttpStatus(code: ErrorCode): number {
  switch (code) {
    case "UNAUTHORIZED":
      return 401;
    case "PROJECT_NOT_FOUND":
    case "AGENT_NOT_FOUND":
    case "RUN_NOT_FOUND":
      return 404;
    case "AGENT_BUSY":
    case "BLOCKED_BY_POLICY":
    case "VALIDATION_ERROR":
      return 409;
    case "RUN_TIMEOUT":
      return 504;
    case "NOT_SUPPORTED":
      return 501;
    case "CURSOR_API_ERROR":
      return 502;
    default:
      return 500;
  }
}

export function toErrorPayload(error: unknown): {
  error: { code: ErrorCode; message: string; details: Record<string, unknown> };
} {
  if (error instanceof BridgeError) {
    return {
      error: {
        code: error.code,
        message: error.message,
        details: error.details,
      },
    };
  }

  const message =
    error instanceof Error ? error.message : "Unexpected internal error";

  return {
    error: {
      code: "INTERNAL_ERROR",
      message,
      details: {},
    },
  };
}

export function toolErrorResult(error: unknown): {
  content: Array<{ type: "text"; text: string }>;
  isError: true;
  structuredContent: ReturnType<typeof toErrorPayload>;
} {
  const payload = toErrorPayload(error);
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
    isError: true,
    structuredContent: payload,
  };
}

export function toolSuccessResult(data: unknown): {
  content: Array<{ type: "text"; text: string }>;
  structuredContent: Record<string, unknown>;
} {
  const text = JSON.stringify(data, null, 2);
  const structuredContent =
    data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, unknown>)
      : { result: data };
  return {
    content: [{ type: "text", text }],
    structuredContent,
  };
}
