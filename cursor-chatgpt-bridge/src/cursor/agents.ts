import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { BridgeError } from "../errors.js";

const execFileAsync = promisify(execFile);

async function git(
  workingDirectory: string,
  arguments_: string[],
  maxBuffer = 2_000_000,
): Promise<string> {
  try {
    const { stdout } = await execFileAsync("git", ["-C", workingDirectory, ...arguments_], {
      encoding: "utf8",
      maxBuffer,
      timeout: 15_000,
    });
    return stdout.trimEnd();
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Unknown git error";
    throw new BridgeError("INTERNAL_ERROR", "Unable to inspect repository changes", { reason });
  }
}

function parseStatus(status: string): Array<{ path: string; status: string }> {
  if (!status) return [];
  return status
    .split("\0")
    .filter(Boolean)
    .map((entry) => ({
      status: entry.slice(0, 2),
      path: entry.slice(3),
    }));
}

export async function inspectLocalChanges(
  workingDirectory: string,
  maxDiffCharacters: number,
): Promise<{
  branch: string;
  clean: boolean;
  files: Array<{ path: string; status: string }>;
  git_status: string;
  diff_stat: string;
  diff: string;
  diff_truncated: boolean;
  recent_commits: string[];
}> {
  const [branch, porcelain, humanStatus, diffStat, fullDiff, commits] = await Promise.all([
    git(workingDirectory, ["branch", "--show-current"]),
    git(workingDirectory, ["status", "--porcelain=v1", "-z"]),
    git(workingDirectory, ["status", "--short", "--branch"]),
    git(workingDirectory, ["diff", "--stat", "HEAD"]),
    git(workingDirectory, ["diff", "HEAD"], Math.max(2_000_000, maxDiffCharacters * 2)),
    git(workingDirectory, ["log", "-5", "--pretty=format:%h %s"]),
  ]);
  const isTruncated = fullDiff.length > maxDiffCharacters;
  return {
    branch,
    clean: porcelain.length === 0,
    files: parseStatus(porcelain),
    git_status: humanStatus,
    diff_stat: diffStat,
    diff: isTruncated ? `${fullDiff.slice(0, maxDiffCharacters)}\n…[truncated]` : fullDiff,
    diff_truncated: isTruncated,
    recent_commits: commits ? commits.split("\n") : [],
  };
}
