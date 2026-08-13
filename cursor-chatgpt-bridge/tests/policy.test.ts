import { describe, expect, it } from "vitest";
import { evaluatePolicy } from "../src/security/policy.js";

describe("dangerous action policy", () => {
  it.each([
    "deploy em produção",
    "git reset --hard HEAD~1",
    "git push origin main --force",
    "terraform destroy",
    "kubectl delete namespace payments",
    "drop database customers",
    "rm -rf /",
    "rm -fr /",
    "rotacionar secrets agora",
  ])("should block dangerous instruction without authorization: %s", (message) => {
    expect(evaluatePolicy(message)).toMatchObject({
      allowed: false,
      requires_explicit_authorization: true,
    });
  });

  it("should allow ordinary coding work", () => {
    expect(evaluatePolicy("Add unit tests and run lint")).toEqual({
      allowed: true,
      requires_explicit_authorization: false,
    });
  });

  it("should allow a matched action only with explicit authorization", () => {
    expect(evaluatePolicy("terraform destroy", true)).toMatchObject({
      allowed: true,
      matched_rule: "infrastructure_destroy",
      requires_explicit_authorization: false,
    });
  });
});
