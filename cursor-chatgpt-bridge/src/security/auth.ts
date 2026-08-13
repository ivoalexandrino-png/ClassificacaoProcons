import { timingSafeEqual } from "node:crypto";

export function extractBearerToken(authorizationHeader: string | undefined): string | undefined {
  if (!authorizationHeader) {
    return undefined;
  }
  const match = authorizationHeader.match(/^Bearer\s+(.+)$/i);
  return match?.[1]?.trim();
}

export function safeTokenEquals(expected: string, provided: string): boolean {
  if (!expected || !provided) {
    return false;
  }
  const expectedBuf = Buffer.from(expected);
  const providedBuf = Buffer.from(provided);
  if (expectedBuf.length !== providedBuf.length) {
    return false;
  }
  return timingSafeEqual(expectedBuf, providedBuf);
}

export function isAuthorized(expectedToken: string, authorizationHeader: string | undefined): boolean {
  if (!expectedToken) {
    return false;
  }
  const provided = extractBearerToken(authorizationHeader);
  if (!provided) {
    return false;
  }
  return safeTokenEquals(expectedToken, provided);
}
