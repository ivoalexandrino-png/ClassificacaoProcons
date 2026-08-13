import { describe, expect, it } from "vitest";

import { evaluateMessage, normalizeForPolicy } from "../src/security/policy.js";

describe("normalizeForPolicy", () => {
  it("should lowercase and strip accents", () => {
    expect(normalizeForPolicy("Deploy em PRODUÇÃO")).toBe("deploy em producao");
  });
});

describe("evaluateMessage", () => {
  const dangerous = [
    "faça o deploy em produção agora",
    "deploy to production please",
    "roda isso no ambiente prod",
    "DROP DATABASE users;",
    "truncate the orders table",
    "delete database staging",
    "pode apagar o banco de dados",
    "terraform destroy -auto-approve",
    "kubectl delete deployment api",
    "git reset --hard origin/main",
    "faz um force push da branch",
    "git push --force origin main",
    "git push -f origin main",
    "rm -rf /var/www",
    "revogar credenciais do serviço",
    "rotacionar secrets do cluster",
    "rotate secrets in vault",
  ];

  for (const message of dangerous) {
    it(`should block: "${message}"`, () => {
      const decision = evaluateMessage(message);
      expect(decision.allowed).toBe(false);
      expect(decision.matches.length).toBeGreaterThan(0);
      expect(decision.reason).toContain("allow_dangerous_actions");
    });
  }

  const safe = [
    "adicione testes para o parser de e-mails",
    "corrija o bug no cálculo do desconto e rode os testes",
    "refatore a função fetchPendingOrders",
    "crie um commit com as mudanças na branch de feature",
    "atualize o README com instruções de instalação",
    "rode npm run lint e corrija os avisos",
  ];

  for (const message of safe) {
    it(`should allow: "${message}"`, () => {
      const decision = evaluateMessage(message);
      expect(decision.allowed).toBe(true);
      expect(decision.matches).toHaveLength(0);
    });
  }

  it("should allow a dangerous message when explicitly authorized", () => {
    const decision = evaluateMessage("git push --force origin main", true);
    expect(decision.allowed).toBe(true);
    expect(decision.matches.length).toBeGreaterThan(0);
  });

  it("should never report authorization it did not receive", () => {
    const decision = evaluateMessage("drop database prod");
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toBeTruthy();
  });
});
