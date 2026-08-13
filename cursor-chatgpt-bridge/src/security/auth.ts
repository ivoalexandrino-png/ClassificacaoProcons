import { timingSafeEqual } from "node:crypto";
import type { NextFunction, Request, Response } from "express";
import { errorBody } from "../mcp/errors.js";

const BEARER_PREFIX = "Bearer ";

function safeCompare(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) {
    // Still run a comparison of equal-length buffers to avoid a short-circuit
    // timing signal on length, then fail deterministically.
    timingSafeEqual(bufA, bufA);
    return false;
  }
  return timingSafeEqual(bufA, bufB);
}

export function extractBearerToken(header: string | undefined): string | undefined {
  if (!header || !header.startsWith(BEARER_PREFIX)) return undefined;
  const token = header.slice(BEARER_PREFIX.length).trim();
  return token.length > 0 ? token : undefined;
}

export function isAuthorized(header: string | undefined, expectedToken: string): boolean {
  const provided = extractBearerToken(header);
  if (!provided) return false;
  return safeCompare(provided, expectedToken);
}

/**
 * Express middleware enforcing `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>`.
 * Never logs the token or the raw Authorization header.
 */
export function createAuthMiddleware(expectedToken: string) {
  return function authMiddleware(req: Request, res: Response, next: NextFunction): void {
    if (!isAuthorized(req.header("authorization"), expectedToken)) {
      res
        .status(401)
        .json(
          errorBody(
            "UNAUTHORIZED",
            "Missing or invalid bearer token. Send 'Authorization: Bearer <CURSOR_BRIDGE_TOKEN>'.",
          ),
        );
      return;
    }
    next();
  };
}
