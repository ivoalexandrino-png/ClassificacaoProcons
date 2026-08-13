const DANGEROUS_PATTERNS: Array<{ pattern: RegExp; reason: string }> = [
  { pattern: /\bprodu[cç][aã]o\b/i, reason: "mentions production environment" },
  { pattern: /\bprod\b/i, reason: "mentions prod environment" },
  { pattern: /\bproduction\b/i, reason: "mentions production" },
  { pattern: /deploy\s+(?:em\s+)?produ/i, reason: "mentions production deploy" },
  { pattern: /drop\s+database/i, reason: "mentions dropping a database" },
  { pattern: /\btruncate\b/i, reason: "mentions truncate operation" },
  { pattern: /delete\s+database/i, reason: "mentions deleting a database" },
  { pattern: /apagar\s+banco/i, reason: "mentions deleting a database (Portuguese)" },
  { pattern: /\bdestroy\b/i, reason: "mentions destroy operation" },
  { pattern: /terraform\s+destroy/i, reason: "mentions terraform destroy" },
  { pattern: /kubectl\s+delete/i, reason: "mentions kubectl delete" },
  { pattern: /reset\s+--hard/i, reason: "mentions git reset --hard" },
  { pattern: /git\s+push\s+--force/i, reason: "mentions force push" },
  { pattern: /force\s+push/i, reason: "mentions force push" },
  { pattern: /rm\s+-rf\s+\/(?:etc|usr|var|home|root)/i, reason: "mentions rm -rf on critical paths" },
  { pattern: /revogar\s+credenciais/i, reason: "mentions revoking credentials" },
  { pattern: /rotacionar\s+secrets/i, reason: "mentions rotating secrets" },
  { pattern: /rotate\s+secrets/i, reason: "mentions rotating secrets" },
];

export interface PolicyEvaluation {
  allowed: boolean;
  reason?: string;
  requiresExplicitAuthorization?: boolean;
}

export function evaluateDangerousAction(
  message: string,
  allowDangerousActions: boolean,
): PolicyEvaluation {
  if (allowDangerousActions) {
    return { allowed: true };
  }

  for (const { pattern, reason } of DANGEROUS_PATTERNS) {
    if (pattern.test(message)) {
      return {
        allowed: false,
        reason: `Blocked by policy: ${reason}`,
        requiresExplicitAuthorization: true,
      };
    }
  }

  return { allowed: true };
}
