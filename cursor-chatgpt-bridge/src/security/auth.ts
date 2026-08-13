import { timingSafeEqual } from "node:crypto";
import type { RequestHandler } from "express";

export function bearerAuth(expectedToken: string): RequestHandler {
  return (request, response, next) => {
    const header = request.header("authorization");
    const receivedToken = header?.startsWith("Bearer ") ? header.slice("Bearer ".length) : "";
    const expected = Buffer.from(expectedToken);
    const received = Buffer.from(receivedToken);
    const valid = expected.length === received.length && timingSafeEqual(expected, received);
    if (!valid) {
      response.status(401).json({ error: { code: "UNAUTHORIZED", message: "Valid bearer token required", details: {} } });
      return;
    }
    next();
  };
}
