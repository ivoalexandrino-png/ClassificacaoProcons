import { describe, expect, it } from "vitest";
import {
  assertAuthorized,
  extractBearerToken,
  tokensMatch,
} from "../src/security/auth.js";
import { evaluateDangerousActions } from "../src/security/policy.js";
import { BridgeError } from "../src/errors.js";

describe("authentication", () => {
  it("should reject request when token is missing", () => {
    expect(() => assertAuthorized(undefined, "secret")).toThrowError(BridgeError);
    try {
      assertAuthorized(undefined, "secret");
    } catch (error) {
      expect(error).toBeInstanceOf(BridgeError);
      expect((error as BridgeError).code).toBe("UNAUTHORIZED");
    }
  });

  it("should reject request when token is incorrect", () => {
    expect(() =>
      assertAuthorized("Bearer wrong-token", "correct-token"),
    ).toThrowError(/Invalid bearer token/);
  });

  it("should accept request when token is correct", () => {
    expect(() =>
      assertAuthorized("Bearer correct-token", "correct-token"),
    ).not.toThrow();
    expect(extractBearerToken("Bearer abc")).toBe("abc");
    expect(tokensMatch("same", "same")).toBe(true);
    expect(tokensMatch("same", "diff")).toBe(false);
  });
});

describe("dangerous action policy", () => {
  it("should block dangerous action when authorization flag is false", () => {
    const result = evaluateDangerousActions(
      "Please run terraform destroy in production",
      false,
    );
    expect(result.allowed).toBe(false);
    expect(result.requiresExplicitAuthorization).toBe(true);
    expect(result.matched.length).toBeGreaterThan(0);
  });

  it("should allow common action when no dangerous pattern is present", () => {
    const result = evaluateDangerousActions(
      "Run the unit tests and fix failing assertions",
      false,
    );
    expect(result.allowed).toBe(true);
    expect(result.matched).toEqual([]);
  });

  it("should allow dangerous action only when allow_dangerous_actions is true", () => {
    const result = evaluateDangerousActions(
      "git push --force origin feature",
      true,
    );
    expect(result.allowed).toBe(true);
    expect(result.requiresExplicitAuthorization).toBe(true);
  });
});
