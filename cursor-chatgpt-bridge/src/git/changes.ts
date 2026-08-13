import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export interface GitFileChange {
  status: string;
  path: string;
}

export interface GitChanges {
  available: true;
  branch: string | null;
  clean: boolean;
  files: GitFileChange[];
  status: string;
  diff_stat: string;
  diff: string;
  diff_truncated: boolean;
  recent_commits: string[];
}

export interface GitUnavailable {
  available: false;
  reason: string;
}

const DEFAULT_MAX_DIFF_CHARS = 30_000;

async function git(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", args, {
    cwd,
    maxBuffer: 64 * 1024 * 1024,
  });
  return stdout;
}

/**
 * Collect a structured, size-bounded view of the working tree changes for a
 * local agent's working directory.
 */
export async function collectGitChanges(
  workingDirectory: string,
  maxDiffChars: number = DEFAULT_MAX_DIFF_CHARS,
): Promise<GitChanges | GitUnavailable> {
  try {
    await git(workingDirectory, ["rev-parse", "--is-inside-work-tree"]);
  } catch {
    return { available: false, reason: "Not a git repository or git is unavailable" };
  }

  const branch = (await safeGit(workingDirectory, ["rev-parse", "--abbrev-ref", "HEAD"]))?.trim() ?? null;
  const statusPorcelain = (await safeGit(workingDirectory, ["status", "--porcelain"])) ?? "";
  const files = parsePorcelain(statusPorcelain);
  const diffStat = (await safeGit(workingDirectory, ["diff", "--stat"])) ?? "";
  const rawDiff = (await safeGit(workingDirectory, ["diff"])) ?? "";
  const commitsRaw = (await safeGit(workingDirectory, ["log", "-5", "--pretty=format:%h %s"])) ?? "";

  const diffTruncated = rawDiff.length > maxDiffChars;
  const diff = diffTruncated
    ? `${rawDiff.slice(0, maxDiffChars)}\n... [truncated: ${rawDiff.length - maxDiffChars} more characters]`
    : rawDiff;

  return {
    available: true,
    branch,
    clean: files.length === 0,
    files,
    status: statusPorcelain.trim(),
    diff_stat: diffStat.trim(),
    diff,
    diff_truncated: diffTruncated,
    recent_commits: commitsRaw.split("\n").filter((line) => line.trim().length > 0),
  };
}

async function safeGit(cwd: string, args: string[]): Promise<string | null> {
  try {
    return await git(cwd, args);
  } catch {
    return null;
  }
}

function parsePorcelain(output: string): GitFileChange[] {
  return output
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => ({
      status: line.slice(0, 2).trim(),
      path: line.slice(3).trim(),
    }));
}
