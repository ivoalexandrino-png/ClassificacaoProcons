import { describe, expect, it } from "vitest";

import { evaluatePolicy } from "../src/security/policy.js";

describe("evaluatePolicy", () => {
  it("should allow an ordinary development instruction", () => {
    const decision = evaluatePolicy("Add a unit test for the auth middleware", false);
    expect(decision.blocked).toBe(false);
    expect(decision.matches).toHaveLength(0);
  });

  it.each([
    ["Please deploy this to production now", "production"],
    ["run drop database analytics", "database"],
    ["execute terraform destroy on the cluster", "destroy"],
    ["git push --force to main", "git"],
    ["rm -rf / to clean up", "filesystem"],
    ["rotate the secrets in vault", "secrets"],
    ["faça o deploy em produção", "deploy"],
    ["apagar banco de dados de clientes", "database"],
  ])("should block dangerous instruction: %s", (message, category) => {
    const decision = evaluatePolicy(message, false);
    expect(decision.blocked).toBe(true);
    expect(decision.reason).toBeTruthy();
    expect(decision.matches.some((m) => m.category === category)).toBe(true);
  });

  it("should not block when explicit authorization is provided", () => {
    const decision = evaluatePolicy("deploy to production", true);
    expect(decision.blocked).toBe(false);
    expect(decision.matches.length).toBeGreaterThan(0);
  });

  it("should not flag benign words that merely contain a keyword", () => {
    const decision = evaluatePolicy("Write a reproduction case for the bug", false);
    expect(decision.blocked).toBe(false);
  });
});
