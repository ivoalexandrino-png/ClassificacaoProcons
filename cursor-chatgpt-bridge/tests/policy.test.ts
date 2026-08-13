import { describe, expect, it } from "vitest";
import { extractBearerToken, isAuthorized, safeTokenEquals } from "../src/security/auth.js";
import { evaluateDangerousAction } from "../src/security/policy.js";

describe("auth", () => {
  it("should reject request without token", () => {
    expect(isAuthorized("secret-token", undefined)).toBe(false);
  });

  it("should reject incorrect token", () => {
    expect(isAuthorized("secret-token", "Bearer wrong-token")).toBe(false);
  });

  it("should accept correct token", () => {
    expect(isAuthorized("secret-token", "Bearer secret-token")).toBe(true);
  });

  it("should extract bearer token from header", () => {
    expect(extractBearerToken("Bearer abc")).toBe("abc");
  });

  it("should compare tokens safely", () => {
    expect(safeTokenEquals("abc", "abc")).toBe(true);
    expect(safeTokenEquals("abc", "abd")).toBe(false);
  });
});

describe("policy", () => {
  it("should block dangerous action without authorization", () => {
    const result = evaluateDangerousAction("deploy em produção agora", false);
    expect(result.allowed).toBe(false);
    expect(result.requiresExplicitAuthorization).toBe(true);
  });

  it("should allow common action", () => {
    const result = evaluateDangerousAction("add unit tests for parser", false);
    expect(result.allowed).toBe(true);
  });

  it("should allow dangerous action when explicitly authorized", () => {
    const result = evaluateDangerousAction("terraform destroy", true);
    expect(result.allowed).toBe(true);
  });
});
