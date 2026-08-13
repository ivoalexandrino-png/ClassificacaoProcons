import { timingSafeEqual } from "node:crypto";

function extractBearer(header: string | undefined): string | undefined {
  if (!header) return undefined;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match?.[1];
}

export function isAuthorized(
  authorizationHeader: string | undefined,
  expectedToken: string,
): boolean {
  const suppliedToken = extractBearer(authorizationHeader);
  if (!suppliedToken) return false;
  const supplied = Buffer.from(suppliedToken);
  const expected = Buffer.from(expectedToken);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}
