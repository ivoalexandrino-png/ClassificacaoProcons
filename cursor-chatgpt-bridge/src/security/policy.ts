/**
 * Policy layer: a keyword barrier against instructions that look destructive
 * or production-related. This is intentionally a best-effort filter, not a
 * complete security solution — the real boundary is that the Cursor agent
 * works on branches and never deploys silently.
 */

export interface PolicyMatch {
  category: string;
  pattern: string;
}

export interface PolicyDecision {
  allowed: boolean;
  matches: PolicyMatch[];
  reason: string | null;
}

interface PolicyRule {
  category: string;
  /** Regex applied to the normalized (lowercase, accent-stripped) message. */
  regex: RegExp;
  label: string;
}

/** Lowercase and strip diacritics so "produção" matches "producao". */
export function normalizeForPolicy(message: string): string {
  return message
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

const RULES: PolicyRule[] = [
  { category: "production", regex: /\bproduction\b/, label: "production" },
  { category: "production", regex: /\bproducao\b/, label: "produção" },
  { category: "production", regex: /\bprod\b/, label: "prod" },
  { category: "production", regex: /\bdeploy(?:\s+\w+){0,3}\s+(?:em|to|na|no)\s+prod(?:ucao|uction)?\b/, label: "deploy em produção" },
  { category: "database", regex: /\bdrop\s+(?:database|table|schema)\b/, label: "drop database" },
  { category: "database", regex: /\btruncate\b/, label: "truncate" },
  { category: "database", regex: /\bdelete\s+database\b/, label: "delete database" },
  { category: "database", regex: /\bapagar\s+(?:o\s+)?banco\b/, label: "apagar banco" },
  { category: "infrastructure", regex: /\bdestroy\b/, label: "destroy" },
  { category: "infrastructure", regex: /\bterraform\s+destroy\b/, label: "terraform destroy" },
  { category: "infrastructure", regex: /\bkubectl\s+delete\b/, label: "kubectl delete" },
  { category: "git", regex: /\breset\s+--hard\b/, label: "reset --hard" },
  { category: "git", regex: /\bforce[\s-]?push\b/, label: "force push" },
  { category: "git", regex: /\bgit\s+push\s+(?:\S+\s+)*--force\b/, label: "git push --force" },
  { category: "git", regex: /\bgit\s+push\s+(?:\S+\s+)*-f\b/, label: "git push -f" },
  { category: "filesystem", regex: /\brm\s+-r?f\w*\b/, label: "rm -rf" },
  { category: "credentials", regex: /\brevogar\s+credenciais\b/, label: "revogar credenciais" },
  { category: "credentials", regex: /\brevoke\s+credentials?\b/, label: "revoke credentials" },
  { category: "credentials", regex: /\brotacionar\s+secrets?\b/, label: "rotacionar secrets" },
  { category: "credentials", regex: /\brotate\s+secrets?\b/, label: "rotate secrets" },
];

/**
 * Evaluate a message that will be forwarded to a Cursor agent.
 * Returns `allowed: false` when the message matches a dangerous pattern and
 * the caller did not pass explicit authorization.
 */
export function evaluateMessage(message: string, allowDangerousActions = false): PolicyDecision {
  const normalized = normalizeForPolicy(message);
  const matches: PolicyMatch[] = [];
  for (const rule of RULES) {
    if (rule.regex.test(normalized)) {
      matches.push({ category: rule.category, pattern: rule.label });
    }
  }
  if (matches.length === 0 || allowDangerousActions) {
    return { allowed: true, matches, reason: null };
  }
  const patterns = matches.map((m) => m.pattern).join(", ");
  return {
    allowed: false,
    matches,
    reason:
      `Message matches dangerous-action patterns (${patterns}). ` +
      `Re-send with allow_dangerous_actions=true only after the human user explicitly authorized it.`,
  };
}
