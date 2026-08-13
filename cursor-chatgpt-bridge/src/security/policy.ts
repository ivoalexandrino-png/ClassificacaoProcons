/**
 * Additional safety barrier over the instructions ChatGPT forwards to Cursor.
 *
 * This is a heuristic guardrail, not a perfect security boundary: it flags
 * prompts that look like destructive or production-facing operations and
 * requires the caller to pass `allow_dangerous_actions: true` to proceed.
 * The bridge never fabricates that authorization on its own.
 */

export interface PolicyMatch {
  pattern: string;
  category: string;
}

export interface PolicyDecision {
  blocked: boolean;
  matches: PolicyMatch[];
  reason?: string;
}

interface Rule {
  category: string;
  /** Human-readable label used in the reason/report. */
  label: string;
  regex: RegExp;
}

/**
 * Rules are intentionally conservative and word-boundary aware where it matters
 * to reduce false positives (e.g. "production" matches, but not "reproduction").
 */
const RULES: Rule[] = [
  { category: "production", label: "production", regex: /\bprod(?:uction)?\b/i },
  { category: "production", label: "produção", regex: /\bprodu[çc][aã]o\b/i },
  { category: "deploy", label: "deploy to production", regex: /\bdeploy\b[^.\n]*\bprod(?:uction)?\b/i },
  { category: "deploy", label: "deploy em produção", regex: /\bdeploy\b[^.\n]*\bprodu[çc][aã]o\b/i },
  { category: "database", label: "drop database", regex: /\bdrop\s+database\b/i },
  { category: "database", label: "drop table", regex: /\bdrop\s+table\b/i },
  { category: "database", label: "truncate", regex: /\btruncate\b/i },
  { category: "database", label: "delete database", regex: /\bdelete\s+database\b/i },
  { category: "database", label: "apagar banco", regex: /\bapagar\s+(?:o\s+)?banco\b/i },
  { category: "destroy", label: "destroy", regex: /\bdestroy\b/i },
  { category: "destroy", label: "terraform destroy", regex: /\bterraform\s+destroy\b/i },
  { category: "kubernetes", label: "kubectl delete", regex: /\bkubectl\s+delete\b/i },
  { category: "git", label: "reset --hard", regex: /\breset\s+--hard\b/i },
  { category: "git", label: "force push", regex: /\bforce[-\s]?push\b/i },
  { category: "git", label: "git push --force", regex: /\bgit\s+push\b[^.\n]*(?:--force\b|-f\b)/i },
  { category: "filesystem", label: "rm -rf", regex: /\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r/i },
  { category: "secrets", label: "revoke credentials", regex: /\brevoke\b[^.\n]*\bcredential/i },
  { category: "secrets", label: "revogar credenciais", regex: /\brevogar\b[^.\n]*\bcredenc/i },
  { category: "secrets", label: "rotate secrets", regex: /\brotate\b[^.\n]*\bsecret/i },
  { category: "secrets", label: "rotacionar secrets", regex: /\brotacionar\b[^.\n]*\b(?:secret|segredo|credenc)/i },
];

/**
 * Evaluate a message against the policy.
 *
 * @param message the instruction destined for the Cursor agent
 * @param allowDangerous when true, matches are reported but not blocked
 */
export function evaluatePolicy(message: string, allowDangerous: boolean): PolicyDecision {
  const matches: PolicyMatch[] = [];
  for (const rule of RULES) {
    if (rule.regex.test(message)) {
      matches.push({ pattern: rule.label, category: rule.category });
    }
  }

  if (matches.length === 0) {
    return { blocked: false, matches: [] };
  }

  if (allowDangerous) {
    return { blocked: false, matches };
  }

  const labels = [...new Set(matches.map((m) => m.pattern))].join(", ");
  return {
    blocked: true,
    matches,
    reason: `Message matches potentially dangerous patterns (${labels}). Re-send with allow_dangerous_actions=true only after a human has explicitly authorized it.`,
  };
}
