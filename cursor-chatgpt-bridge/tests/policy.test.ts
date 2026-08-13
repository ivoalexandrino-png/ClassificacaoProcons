import { describe, expect, it } from "vitest";
import { evaluateMessagePolicy } from "../src/security/policy.js";

describe("evaluateMessagePolicy", () => {
  it("should allow an ordinary development instruction", () => {
    const result = evaluateMessagePolicy("Adicione um teste para a função de parsing.", false);
    expect(result.blocked).toBe(false);
    expect(result.matches).toHaveLength(0);
  });

  it.each([
    "Faça o deploy em produção agora",
    "rode terraform destroy no ambiente",
    "kubectl delete deployment api -n prod",
    "git push --force para main",
    "git reset --hard HEAD~5 e force push",
    "TRUNCATE TABLE users;",
    "apagar banco de dados de clientes",
    "revogar credenciais do serviço de pagamento",
    "rotacionar secrets do banco",
    "rm -rf / --no-preserve-root",
  ])("should block a dangerous action by default: %s", (message) => {
    const result = evaluateMessagePolicy(message, false);
    expect(result.blocked).toBe(true);
    expect(result.matches.length).toBeGreaterThan(0);
    expect(result.reason).toBeDefined();
  });

  it("should not block a dangerous action when allow_dangerous_actions is true", () => {
    const result = evaluateMessagePolicy("Faça o deploy em produção agora", true);
    expect(result.blocked).toBe(false);
    // Matches are still reported for auditing even when explicitly authorized.
    expect(result.matches.length).toBeGreaterThan(0);
  });

  it("should never claim authorization was granted when it was not requested", () => {
    const result = evaluateMessagePolicy("drop database legacy_orders", false);
    expect(result.blocked).toBe(true);
    expect(result.reason).toMatch(/explicit/i);
  });
});
