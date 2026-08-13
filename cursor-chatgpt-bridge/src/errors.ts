export const errorCodes = [
  "UNAUTHORIZED",
  "PROJECT_NOT_FOUND",
  "AGENT_NOT_FOUND",
  "RUN_NOT_FOUND",
  "AGENT_BUSY",
  "CURSOR_API_ERROR",
  "RUN_TIMEOUT",
  "BLOCKED_BY_POLICY",
  "INVALID_INPUT",
  "INTERNAL_ERROR",
] as const;

export type BridgeErrorCode = (typeof errorCodes)[number];

export class BridgeError extends Error {
  constructor(
    public readonly code: BridgeErrorCode,
    message: string,
    public readonly details: Record<string, unknown> = {},
    public readonly httpStatus = 400,
  ) {
    super(message);
    this.name = "BridgeError";
  }
}

export type ErrorResponse = {
  error: {
    code: BridgeErrorCode;
    message: string;
    details: Record<string, unknown>;
  };
};

export function errorResponse(error: unknown): ErrorResponse {
  if (error instanceof BridgeError) {
    return {
      error: {
        code: error.code,
        message: error.message,
        details: error.details,
      },
    };
  }
  return {
    error: {
      code: "INTERNAL_ERROR",
      message: "Internal bridge error",
      details: {},
    },
  };
}
