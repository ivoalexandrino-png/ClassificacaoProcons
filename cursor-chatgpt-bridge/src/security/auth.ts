import { createHash, timingSafeEqual } from "node:crypto";

import type { NextFunction, Request, Response } from "express";

/**
 * Constant-time comparison of two strings. Hashing first guarantees equal
 * buffer lengths, so no length information leaks either.
 */
export function safeTokenCompare(provided: string, expected: string): boolean {
  const a = createHash("sha256").update(provided).digest();
  const b = createHash("sha256").update(expected).digest();
  return timingSafeEqual(a, b);
}

export function extractBearerToken(authorizationHeader: string | undefined): string | undefined {
  if (!authorizationHeader) return undefined;
  const match = /^Bearer\s+(.+)$/i.exec(authorizationHeader.trim());
  return match?.[1];
}

/**
 * Express middleware enforcing `Authorization: Bearer <token>`.
 * The bridge refuses to start HTTP mode without a token, so `expectedToken`
 * is always a non-empty string here.
 */
export function createAuthMiddleware(expectedToken: string) {
  return function authMiddleware(req: Request, res: Response, next: NextFunction): void {
    const provided = extractBearerToken(req.headers.authorization);
    if (!provided || !safeTokenCompare(provided, expectedToken)) {
      res.status(401).json({
        error: {
          code: "UNAUTHORIZED",
          message: "Missing or invalid bearer token",
          details: {},
        },
      });
      return;
    }
    next();
  };
}
