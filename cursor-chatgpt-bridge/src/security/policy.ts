const dangerousPatterns = [
  /\bprodução\b/i, /\bprod\b/i, /\bproduction\b/i, /deploy\s+(em\s+)?produção/i,
  /\bdrop\s+database\b/i, /\btruncate\b/i, /delete\s+database/i, /apagar\s+banco/i,
  /\bdestroy\b/i, /terraform\s+destroy/i, /kubectl\s+delete/i, /git\s+reset\s+--hard/i,
  /git\s+push\s+--force/i, /\brm\s+-rf\s+(\/|~|\/etc|\/usr|\/var)\b/i,
  /revogar\s+credenciais/i, /rotacionar\s+secrets/i
];

export interface PolicyDecision {
  allowed: boolean;
  reason?: string;
  requiresExplicitAuthorization: boolean;
}

export function evaluateInstruction(message: string, allowDangerousActions = false): PolicyDecision {
  const match = dangerousPatterns.find((pattern) => pattern.test(message));
  if (!match || allowDangerousActions) return { allowed: true, requiresExplicitAuthorization: false };
  return {
    allowed: false,
    reason: `Potentially dangerous instruction matched policy pattern: ${match.source}`,
    requiresExplicitAuthorization: true
  };
}
