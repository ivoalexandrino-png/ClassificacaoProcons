import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const GIT_TIMEOUT_MS = 15_000;
const GIT_MAX_BUFFER = 32 * 1024 * 1024;

export interface LocalChanges {
  branch: string;
  clean: boolean;
  files: Array<{ path: string; status: string }>;
  diff_stat: string;
  diff: string;
  diff_truncated: boolean;
  recent_commits: string[];
}

async function git(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", args, {
    cwd,
    timeout: GIT_TIMEOUT_MS,
    maxBuffer: GIT_MAX_BUFFER,
  });
  return stdout.trimEnd();
}

export function truncateText(text: string, maxChars: number): { text: string; truncated: boolean } {
  if (text.length <= maxChars) return { text, truncated: false };
  const omitted = text.length - maxChars;
  return {
    text: `${text.slice(0, maxChars)}\n... [truncated ${omitted} chars]`,
    truncated: true,
  };
}

function parsePorcelain(output: string): Array<{ path: string; status: string }> {
  if (!output) return [];
  return output.split("\n").map((line) => ({
    status: line.slice(0, 2).trim() || "??",
    path: line.slice(3).trim(),
  }));
}

/** Collect git working-tree state for a local agent's working directory. */
export async function collectLocalChanges(
  workingDirectory: string,
  maxDiffChars: number,
): Promise<LocalChanges> {
  const [branch, status, diffStat, rawDiff, log] = await Promise.all([
    git(workingDirectory, ["rev-parse", "--abbrev-ref", "HEAD"]),
    git(workingDirectory, ["status", "--porcelain"]),
    git(workingDirectory, ["diff", "--stat", "HEAD"]).catch(() =>
      git(workingDirectory, ["diff", "--stat"]),
    ),
    git(workingDirectory, ["diff", "HEAD"]).catch(() => git(workingDirectory, ["diff"])),
    git(workingDirectory, ["log", "--oneline", "-n", "10"]).catch(() => ""),
  ]);

  const files = parsePorcelain(status);
  const { text: diff, truncated } = truncateText(rawDiff, maxDiffChars);

  return {
    branch,
    clean: files.length === 0,
    files,
    diff_stat: diffStat,
    diff,
    diff_truncated: truncated,
    recent_commits: log ? log.split("\n") : [],
  };
}
