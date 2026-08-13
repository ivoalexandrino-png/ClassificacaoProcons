import { describe, expect, it } from "vitest";

import { authorize, extractBearerToken, safeCompare } from "../src/security/auth.js";

describe("bearer auth", () => {
  const token = "s3cr3t-token";

  it("should extract a bearer token from the header", () => {
    expect(extractBearerToken("Bearer abc123")).toBe("abc123");
    expect(extractBearerToken("bearer   spaced ")).toBe("spaced");
    expect(extractBearerToken(undefined)).toBeUndefined();
    expect(extractBearerToken("Basic abc")).toBeUndefined();
  });

  it("should compare strings safely", () => {
    expect(safeCompare("a", "a")).toBe(true);
    expect(safeCompare("a", "b")).toBe(false);
    expect(safeCompare("short", "longer-value")).toBe(false);
  });

  it("should reject a request without a token", () => {
    const result = authorize(token, undefined);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("missing");
  });

  it("should reject a request with an incorrect token", () => {
    const result = authorize(token, "Bearer wrong");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid");
  });

  it("should accept a request with the correct token", () => {
    const result = authorize(token, `Bearer ${token}`);
    expect(result.ok).toBe(true);
  });

  it("should fail closed when no token is configured", () => {
    const result = authorize(undefined, "Bearer anything");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("not_configured");
  });
});
