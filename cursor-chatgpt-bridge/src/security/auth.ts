import { timingSafeEqual } from "node:crypto";
import type { RequestHandler } from "express";
import { BridgeError, toErrorPayload } from "../errors.js";

export function extractBearerToken(
  authorizationHeader: string | undefined,
): string | null {
  if (!authorizationHeader) return null;
  const match = /^Bearer\s+(.+)$/i.exec(authorizationHeader.trim());
  if (!match) return null;
  const token = match[1]?.trim();
  return token ? token : null;
}

export function tokensMatch(expected: string, provided: string): boolean {
  const a = Buffer.from(expected);
  const b = Buffer.from(provided);
  if (a.length !== b.length) {
    // Constant-time style rejection without leaking length via early equality.
    timingSafeEqual(a, Buffer.alloc(a.length));
    return false;
  }
  return timingSafeEqual(a, b);
}

export function assertAuthorized(
  authorizationHeader: string | undefined,
  expectedToken: string,
): void {
  if (!expectedToken) {
    throw new BridgeError("UNAUTHORIZED", "Bridge token is not configured");
  }
  const provided = extractBearerToken(authorizationHeader);
  if (!provided) {
    throw new BridgeError("UNAUTHORIZED", "Missing or invalid Authorization header");
  }
  if (!tokensMatch(expectedToken, provided)) {
    throw new BridgeError("UNAUTHORIZED", "Invalid bearer token");
  }
}

export function createBearerAuthMiddleware(expectedToken: string): RequestHandler {
  return (req, res, next) => {
    try {
      assertAuthorized(req.header("authorization") ?? undefined, expectedToken);
      next();
    } catch (error) {
      const payload = toErrorPayload(error);
      const status = error instanceof BridgeError ? error.httpStatus : 401;
      res.status(status).json(payload);
    }
  };
}
