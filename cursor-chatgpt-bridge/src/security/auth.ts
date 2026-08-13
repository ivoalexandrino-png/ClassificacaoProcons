import { timingSafeEqual } from "node:crypto";

/**
 * Bearer-token authentication for the bridge.
 *
 * Every remote request must carry `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>`.
 * The comparison is constant-time to avoid leaking the token through timing.
 */

export type AuthResult =
  | { ok: true }
  | { ok: false; reason: "not_configured" | "missing" | "invalid" };

/** Extract the token from an `Authorization: Bearer <token>` header value. */
export function extractBearerToken(headerValue: string | undefined | null): string | undefined {
  if (!headerValue) return undefined;
  const match = /^Bearer\s+(.+)$/i.exec(headerValue.trim());
  return match?.[1]?.trim() || undefined;
}

/** Constant-time string comparison that tolerates differing lengths. */
export function safeCompare(a: string, b: string): boolean {
  const bufferA = Buffer.from(a, "utf8");
  const bufferB = Buffer.from(b, "utf8");
  if (bufferA.length !== bufferB.length) {
    // Still run a comparison to keep timing uniform, then fail.
    timingSafeEqual(bufferA, bufferA);
    return false;
  }
  return timingSafeEqual(bufferA, bufferB);
}

/**
 * Authorize a request.
 *
 * When no token is configured the server refuses all requests (fail closed):
 * an unauthenticated MCP server is explicitly disallowed.
 */
export function authorize(
  configuredToken: string | undefined,
  headerValue: string | undefined | null,
): AuthResult {
  if (!configuredToken) {
    return { ok: false, reason: "not_configured" };
  }
  const provided = extractBearerToken(headerValue);
  if (!provided) {
    return { ok: false, reason: "missing" };
  }
  if (!safeCompare(provided, configuredToken)) {
    return { ok: false, reason: "invalid" };
  }
  return { ok: true };
}
