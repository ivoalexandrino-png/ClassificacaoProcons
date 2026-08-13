export interface PolicyMatch {
  pattern: string;
  description: string;
}

export interface PolicyEvaluation {
  allowed: boolean;
  matched: PolicyMatch[];
  reason?: string;
  requiresExplicitAuthorization: boolean;
}

const DANGEROUS_PATTERNS: Array<{ regex: RegExp; description: string }> = [
  { regex: /\bprodução\b/i, description: "produção" },
  { regex: /\bproducao\b/i, description: "producao" },
  { regex: /\bproduction\b/i, description: "production" },
  { regex: /\bdeploy(?:ing|ed|s)?\s+(?:to\s+)?(?:prod|production|produção|producao)\b/i, description: "deploy to production" },
  { regex: /\bdrop\s+database\b/i, description: "drop database" },
  { regex: /\btruncate\b/i, description: "truncate" },
  { regex: /\bdelete\s+database\b/i, description: "delete database" },
  { regex: /\bapagar\s+banco\b/i, description: "apagar banco" },
  { regex: /\bdestroy\b/i, description: "destroy" },
  { regex: /\bterraform\s+destroy\b/i, description: "terraform destroy" },
  { regex: /\bkubectl\s+delete\b/i, description: "kubectl delete" },
  { regex: /\breset\s+--hard\b/i, description: "reset --hard" },
  { regex: /\bforce\s+push\b/i, description: "force push" },
  { regex: /\bgit\s+push\s+[^\n]*--force\b/i, description: "git push --force" },
  { regex: /\bgit\s+push\s+-f\b/i, description: "git push -f" },
  { regex: /\brm\s+-rf\s+(\/|~|\$HOME|\/etc|\/var|\/usr|\/home)\b/i, description: "rm -rf critical path" },
  { regex: /\brevogar\s+credenciais\b/i, description: "revogar credenciais" },
  { regex: /\brotacionar\s+secrets?\b/i, description: "rotacionar secrets" },
  { regex: /\brotate\s+secrets?\b/i, description: "rotate secrets" },
  { regex: /\brevoke\s+(?:credentials?|tokens?|keys?)\b/i, description: "revoke credentials" },
];

function normalizeMessage(message: string): string {
  return message.normalize("NFKC");
}

export function evaluateDangerousActions(
  message: string,
  allowDangerousActions = false,
): PolicyEvaluation {
  const text = normalizeMessage(message);
  const matched: PolicyMatch[] = [];

  for (const rule of DANGEROUS_PATTERNS) {
    if (rule.regex.test(text)) {
      matched.push({
        pattern: rule.regex.source,
        description: rule.description,
      });
    }
  }

  // Special-case bare "prod" with word boundaries more carefully
  if (/\bprod\b/i.test(text) && !matched.some((m) => m.description === "prod")) {
    matched.push({ pattern: "\\bprod\\b", description: "prod" });
  }

  if (matched.length === 0) {
    return {
      allowed: true,
      matched: [],
      requiresExplicitAuthorization: false,
    };
  }

  if (allowDangerousActions) {
    return {
      allowed: true,
      matched,
      requiresExplicitAuthorization: true,
      reason:
        "Dangerous patterns detected but allow_dangerous_actions=true was provided.",
    };
  }

  const labels = matched.map((m) => m.description).join(", ");
  return {
    allowed: false,
    matched,
    requiresExplicitAuthorization: true,
    reason: `Blocked potentially dangerous instruction(s): ${labels}. Re-send with allow_dangerous_actions=true only after explicit human authorization.`,
  };
}
