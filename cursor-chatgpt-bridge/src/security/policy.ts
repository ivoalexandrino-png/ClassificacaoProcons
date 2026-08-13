/**
 * Policy layer that adds a second line of defense on top of whatever the
 * Cursor Agent itself would refuse to do. It is a deliberately simple,
 * auditable keyword/pattern classifier — not a semantic safety model — that
 * blocks (by default) instructions that look like they target production
 * systems or perform irreversible/destructive actions.
 *
 * This is intentionally conservative: it only inspects the outgoing prompt
 * text, and it never claims that a user granted authorization. Authorization
 * to bypass it must be explicit (`allow_dangerous_actions: true`) on every
 * call — the bridge never remembers or infers a prior approval.
 */

export interface PolicyMatch {
  pattern: string;
  label: string;
}

export interface PolicyResult {
  blocked: boolean;
  matches: PolicyMatch[];
  reason?: string;
}

interface DangerousPattern {
  label: string;
  regex: RegExp;
}

/**
 * Each entry pairs a human-readable label with a regex. Patterns are
 * intentionally narrow (word-boundaried where useful) to reduce false
 * positives while still catching the terms requested in the spec.
 */
const DANGEROUS_PATTERNS: DangerousPattern[] = [
  { label: "produção/production", regex: /\b(produção|producao|production|\bprod\b)\b/i },
  { label: "deploy em produção", regex: /\bdeploy\b.{0,30}\b(prod(uction|ução|ucao)?)\b/i },
  { label: "drop database", regex: /\bdrop\s+(table|database|schema)\b/i },
  { label: "truncate", regex: /\btruncate\b/i },
  { label: "delete database", regex: /\bdelete\s+(the\s+)?database\b/i },
  { label: "apagar banco", regex: /\bapagar\s+(o\s+)?banco\b/i },
  { label: "destroy", regex: /\bdestroy\b/i },
  { label: "terraform destroy", regex: /\bterraform\s+destroy\b/i },
  { label: "kubectl delete", regex: /\bkubectl\s+delete\b/i },
  { label: "reset --hard", regex: /\breset\s+--hard\b/i },
  { label: "force push", regex: /\b(force\s+push|git\s+push\s+--force|push\s+-f\b)/i },
  { label: "rm -rf em diretório crítico", regex: /\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+.*(\/|~|\*)/i },
  { label: "revogar credenciais", regex: /\brevog(ar|ue|a)\s+credenc/i },
  { label: "rotacionar secrets", regex: /\brotacion(ar|e|a)\s+secrets?\b/i },
  { label: "revoke credentials", regex: /\brevoke\b.{0,20}\b(credential|token|key|access)/i },
  { label: "rotate secrets", regex: /\brotate\b.{0,20}\bsecrets?\b/i },
];

/**
 * Evaluate a follow-up/prompt message against the dangerous-action policy.
 *
 * @param message The text the caller wants to send to the Cursor Agent.
 * @param allowDangerousActions When true, matches are reported but not blocked.
 */
export function evaluateMessagePolicy(
  message: string,
  allowDangerousActions: boolean,
): PolicyResult {
  const matches: PolicyMatch[] = [];
  for (const { label, regex } of DANGEROUS_PATTERNS) {
    if (regex.test(message)) {
      matches.push({ pattern: regex.source, label });
    }
  }

  if (matches.length === 0) {
    return { blocked: false, matches };
  }

  if (allowDangerousActions) {
    return { blocked: false, matches };
  }

  const labels = matches.map((match) => match.label).join(", ");
  return {
    blocked: true,
    matches,
    reason: `Message matches potentially dangerous action pattern(s): ${labels}. Retry with allow_dangerous_actions=true only after explicit human authorization.`,
  };
}
