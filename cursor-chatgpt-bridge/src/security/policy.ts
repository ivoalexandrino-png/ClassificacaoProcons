export interface PolicyDecision {
  allowed: boolean;
  reason?: string;
  matched_rule?: string;
  requires_explicit_authorization: boolean;
}

const dangerousRules: Array<{ name: string; pattern: RegExp }> = [
  { name: "production_action", pattern: /\b(prod|production|produção)\b/i },
  { name: "production_deploy", pattern: /\bdeploy\b.{0,30}\b(prod|production|produção)\b/i },
  { name: "database_drop", pattern: /\b(drop|truncate|delete|apagar)\b.{0,25}\b(database|banco)\b/i },
  { name: "infrastructure_destroy", pattern: /\b(terraform\s+destroy|destroy)\b/i },
  { name: "kubernetes_delete", pattern: /\bkubectl\s+delete\b/i },
  { name: "hard_reset", pattern: /\bgit\s+reset\s+--hard\b|\breset\s+--hard\b/i },
  { name: "force_push", pattern: /\bgit\s+push\b[^\n]*(--force|-f)\b|\bforce\s+push\b/i },
  {
    name: "critical_recursive_delete",
    pattern: /\brm\s+-rf\b.{0,30}(\/|~|\.git|data|database|credentials|secrets)/i,
  },
  {
    name: "credential_change",
    pattern: /\b(revogar|revoke|rotacionar|rotate)\b.{0,30}\b(credenciais?|credentials?|secrets?)\b/i,
  },
];

export function evaluatePolicy(
  message: string,
  allowDangerousActions = false,
): PolicyDecision {
  const matched = dangerousRules.find((rule) => rule.pattern.test(message));
  if (!matched) {
    return { allowed: true, requires_explicit_authorization: false };
  }
  if (allowDangerousActions) {
    return {
      allowed: true,
      matched_rule: matched.name,
      requires_explicit_authorization: false,
    };
  }
  return {
    allowed: false,
    reason: `Instruction matched dangerous-action policy rule: ${matched.name}`,
    matched_rule: matched.name,
    requires_explicit_authorization: true,
  };
}
