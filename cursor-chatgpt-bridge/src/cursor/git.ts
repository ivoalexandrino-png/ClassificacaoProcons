import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export interface LocalGitChanges {
  branch: string | null;
  clean: boolean;
  files: string[];
  diff_stat: string;
  diff: string;
  diff_truncated: boolean;
  recent_commits: string[];
  error?: string;
}

async function git(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", args, {
    cwd,
    maxBuffer: 32 * 1024 * 1024,
  });
  return stdout;
}

/**
 * Best-effort `git status`/`git diff` summary for a local working directory.
 * Never throws for "not a git repo" or similar — reports it in `error`
 * instead, since this is read-only introspection for a chat client.
 */
export async function getLocalGitChanges(
  cwd: string,
  maxDiffChars: number,
): Promise<LocalGitChanges> {
  try {
    const [branchRaw, statusRaw, diffStatRaw, diffRaw, logRaw] = await Promise.all([
      git(cwd, ["rev-parse", "--abbrev-ref", "HEAD"]).catch(() => ""),
      git(cwd, ["status", "--porcelain"]).catch(() => ""),
      git(cwd, ["diff", "--stat", "HEAD"]).catch(() => ""),
      git(cwd, ["diff", "HEAD"]).catch(() => ""),
      git(cwd, ["log", "-n", "5", "--oneline"]).catch(() => ""),
    ]);

    const files = statusRaw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

    const truncated = diffRaw.length > maxDiffChars;
    const diff = truncated ? `${diffRaw.slice(0, maxDiffChars)}\n... [truncated]` : diffRaw;

    return {
      branch: branchRaw.trim() || null,
      clean: files.length === 0,
      files,
      diff_stat: diffStatRaw.trim(),
      diff,
      diff_truncated: truncated,
      recent_commits: logRaw
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      branch: null,
      clean: true,
      files: [],
      diff_stat: "",
      diff: "",
      diff_truncated: false,
      recent_commits: [],
      error: `Unable to read git state for "${cwd}": ${message}`,
    };
  }
}
