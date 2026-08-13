# cursor-chatgpt-bridge

A remote **MCP server** that lets ChatGPT act as a supervisor for **Cursor Agents** (local or Cursor-hosted cloud agents), without anyone copy-pasting messages between the two products.

```text
ChatGPT
   │  MCP (Streamable HTTP, Bearer auth)
   ▼
cursor-chatgpt-bridge
   │  @cursor/sdk (official Cursor SDK)
   ▼
Cursor Agent (local process or Cursor-hosted VM)
   │
   ▼
repository / code / tests
```

The bridge persists everything it sees (projects, agents, runs, messages) in SQLite, so `cursor_get_conversation` and `cursor_get_agent` work even after the bridge process restarts, and even for parts of a conversation the underlying SDK doesn't expose historically.

## Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Development](#development)
- [Build](#build)
- [Tests](#tests)
- [Docker](#docker)
- [Architecture](#architecture)
- [Cursor SDK notes](#cursor-sdk-notes)
- [MCP tools](#mcp-tools)
- [Security](#security)
- [Connecting ChatGPT to cursor-chatgpt-bridge](#connecting-chatgpt-to-cursor-chatgpt-bridge)
- [Example flows](#example-flows)
- [Error codes](#error-codes)
- [Limitations](#limitations)

## Installation

```bash
npm install
```

Requires **Node.js 22.13+** (the same minimum as `@cursor/sdk`).

## Configuration

```bash
cp .env.example .env
```

Then edit `.env`:

| Variable | Required | Description |
| --- | --- | --- |
| `PORT` | no (default `3000`) | HTTP port for the MCP server + `/health`. |
| `CURSOR_BRIDGE_TOKEN` | **yes** | Bearer token clients must send as `Authorization: Bearer <token>`. Without it, `/mcp` refuses every request (see [Security](#security)). |
| `CURSOR_API_KEY` | yes, to actually drive Cursor | User or service-account API key from [Cursor Dashboard → API Keys](https://cursor.com/dashboard/api). Without it, every tool that calls Cursor returns a `CURSOR_API_ERROR`; the bridge still starts and serves `/health` and the read-only bookkeeping tools. |
| `DATABASE_PATH` | no (default `./data/bridge.db`) | SQLite file for projects/agents/runs/messages. |
| `CURSOR_RUN_TIMEOUT_MS` | no (default `900000` = 15 min) | How long `cursor_send_followup(wait_for_completion=true)` waits before reporting `status: "timeout"`. The run keeps executing on Cursor's side; poll `cursor_get_run` afterwards. |
| `LOG_LEVEL` | no (default `info`) | `debug` \| `info` \| `warn` \| `error`. |

Generate a strong bearer token, for example:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

## Development

```bash
npm run dev
```

Starts the HTTP server with `tsx watch` (auto-reload on save), listening on `PORT` (default `3000`).

To run the MCP server over **stdio** instead (useful for local testing with an MCP-capable IDE/CLI, not for ChatGPT — see [MCP](#mcp-transport)):

```bash
npm run dev:stdio
```

## Build

```bash
npm run build
npm start
```

`npm run build` compiles `src/` to `dist/` with `tsc`. `npm start` runs the compiled server (HTTP transport). `npm run start:stdio` runs the compiled server over stdio.

## Tests

```bash
npm test
```

Runs the Vitest suite (`tests/*.test.ts`): persistence, security (auth + policy), concurrency locking, and MCP tool behavior — all mocked against a fake `CursorAgentProvider`, no network or real Cursor API key needed.

```bash
npm run lint       # ESLint (flat config, typescript-eslint)
npm run typecheck  # tsc --noEmit
```

## Docker

```bash
docker build -t cursor-chatgpt-bridge .
docker run -p 3000:3000 --env-file .env -v "$(pwd)/data:/app/data" cursor-chatgpt-bridge
```

The image is a two-stage build (`node:22-bookworm-slim`): compiles TypeScript in the builder stage, then ships only `dist/` + production dependencies. `better-sqlite3` uses its prebuilt native binary for `linux-x64`/glibc, so no compiler toolchain is needed in the runtime image. Mount `/app/data` as a volume to persist the SQLite database across container restarts.

## Architecture

```text
src/
├── index.ts          entry point: picks HTTP or --stdio transport
├── server.ts          Express app: /health, /mcp (Streamable HTTP, session-per-connection)
├── logger.ts           structured JSON logger (always stderr; see "MCP transport" below)
├── config.ts            env var loading/validation
│
├── cursor/
│   ├── types.ts        CursorAgentProvider — the provider-agnostic seam (see below)
│   ├── client.ts        CursorSdkAgentProvider — the ONLY file that imports @cursor/sdk
│   ├── agents.ts        AgentService — projects + agents bookkeeping (SQLite + provider)
│   ├── runs.ts          RunService — follow-ups, locking, timeouts, cancel, changes
│   └── git.ts           local `git status`/`git diff` for cursor_get_changes (mode=local)
│
├── mcp/
│   ├── schemas.ts       Zod input shapes for every MCP tool
│   ├── tools.ts         registerCursorTools(): wires the 10 cursor_* tools onto an McpServer
│   └── errors.ts        BridgeError + the standardized error envelope
│
├── storage/
│   ├── types.ts         row types (projects/agents/runs/messages)
│   └── store.ts         BridgeStore — SQLite persistence (better-sqlite3)
│
└── security/
    ├── auth.ts          Bearer token middleware (timing-safe compare)
    └── policy.ts         dangerous-action keyword/pattern policy
```

**Why the `CursorAgentProvider` seam?** `src/cursor/client.ts` is the only file that imports `@cursor/sdk`. Everything else (the MCP tools, `AgentService`, `RunService`) talks to the `CursorAgentProvider` interface in `src/cursor/types.ts`. If a future SDK major version renames or reshapes `Agent.create`/`Agent.resume`/etc., only `client.ts` needs to change. Tests inject a `MockCursorAgentProvider` (`tests/helpers/mockProvider.ts`) so the whole bridge is testable offline.

### MCP transport

The bridge supports **both** transports the MCP TypeScript SDK ships:

- **Streamable HTTP** (`POST`/`GET`/`DELETE /mcp`) — the one ChatGPT needs. Session-scoped: each MCP `initialize` gets its own `McpServer` + `StreamableHTTPServerTransport`, tracked by the `Mcp-Session-Id` response header, per the [MCP Streamable HTTP spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
- **stdio** (`--stdio` flag) — for local testing with MCP-capable tools that spawn a child process. Not usable by ChatGPT (it only speaks to remote HTTPS servers).

Because both transports share one entry point and one logger, the logger **always writes to `stderr`**, even for `info`/`debug` levels. In stdio mode, MCP requires `stdout` to carry nothing but JSON-RPC frames — interleaving log lines into it would corrupt the protocol stream.

## Cursor SDK notes

This bridge uses **`@cursor/sdk`** (the official TypeScript SDK, public beta as of this writing — `npm install @cursor/sdk`, [docs](https://cursor.com/docs/sdk/typescript)), not the REST API directly, and not any community/unofficial package.

| Concept in this bridge | `@cursor/sdk` API used |
| --- | --- |
| Create a new agent | `Agent.create({ apiKey, local: { cwd } })` (mode=local) or `Agent.create({ apiKey, cloud: { repos: [...] } })` (mode=cloud) |
| Resume an existing agent | `Agent.resume(agentId, { apiKey, local: { cwd } })` — runtime is auto-detected from the ID prefix (`bc-` = cloud, otherwise local) |
| Send a follow-up | `agent.send(message)` → returns a `Run` handle |
| Read a run without a live handle | `Agent.getRun(runId, { runtime: "cloud", agentId, apiKey })` or `{ runtime: "local", cwd }` |
| Wait for completion | `run.wait()` (raced against `CURSOR_RUN_TIMEOUT_MS` in `client.ts`, since the SDK itself has no built-in timeout) |
| Cancel | `Agent.cancelRun(runId, options)`, after checking `run.supports("cancel")` |
| Persistence across process restarts | Cloud: server-side. Local: on-disk SQLite/JSONL checkpoint store maintained by the SDK itself (separate from this bridge's own SQLite database, which stores the bridge's own bookkeeping/conversation log) |
| Authentication | `CURSOR_API_KEY` (user API key or service-account API key) passed to every `Agent.create`/`Agent.resume`/`Agent.getRun` call |

**Local vs. cloud, precisely:** "local" means the agent loop and filesystem access run inside this bridge's own Node process, against `working_directory` on the bridge's host. "Cloud" means Cursor runs the agent in an isolated, Cursor-hosted VM with the given `repository` cloned in. In both cases inference runs on Cursor's hosted models — "local" is about *where the agent loop and files live*, not where the LLM runs.

Errors from the SDK (`AgentBusyError`, `AgentNotFoundError`, `AuthenticationError`, `RateLimitError`, `UnsupportedRunOperationError`, `ConfigurationError`, `IntegrationNotConnectedError`, ...) are mapped to this bridge's own error codes in `src/cursor/client.ts` — see [Error codes](#error-codes).

## MCP tools

| Tool | Purpose |
| --- | --- |
| `cursor_list_agents` | List agents/sessions known to the bridge. |
| `cursor_get_agent` | Full detail on one agent: project, repo, branch, working directory, status, active run, capabilities. |
| `cursor_get_conversation` | Recent messages/events for an agent (`user`/`assistant`/`tool`/`system`), from the bridge's own persisted log. |
| `cursor_send_followup` | **The main tool.** Resumes an agent, sends a follow-up, optionally waits for completion, runs the dangerous-action policy check first. |
| `cursor_start_agent` | Start a brand-new agent (local or cloud) with an initial prompt. |
| `cursor_get_run` | Status/result/error for one run. |
| `cursor_cancel_run` | Cancel a run if the runtime supports it — never simulated. |
| `cursor_get_changes` | For local agents: `git status`/`diff --stat`/diff (truncated to `max_diff_chars`), branch, recent commits. For cloud agents: pushed branches/PR links (the SDK doesn't expose file-level diffs for cloud runs — see [Limitations](#limitations)). |
| `cursor_project_register` | Register/update a named project (repository, working_directory, default_branch) so agents can be found by project name later. |
| `cursor_list_projects` | List registered projects. |

Every tool returns both `content: [{ type: "text", text: "<json>" }]` (for models that only read text) and `structuredContent` (the same payload as a real JSON object, for clients that use it) — errors use the same shape wrapped as `{ error: { code, message, details? } }` with `isError: true`.

## Security

- **Authentication.** `/mcp` requires `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>` on every request (`src/security/auth.ts`). Comparison uses `crypto.timingSafeEqual`. If `CURSOR_BRIDGE_TOKEN` is unset, the server still starts (so `/health` works) but `/mcp` returns `503` on every request — it never falls back to "no auth". `/health` itself is unauthenticated and only reports booleans (`cursor_sdk_configured`, `database`), never secrets.
- **Secrets are never logged.** The logger (`src/logger.ts`) redacts any field named `token`, `apiKey`, `authorization`, `secret`, `password` (case-insensitively, recursively) before writing a line, and the bearer-token middleware never logs the header value on either success or failure.
- **Dangerous-action policy** (`src/security/policy.ts`). `cursor_send_followup` runs every outgoing message through a keyword/pattern classifier before it reaches Cursor. By default (`allow_dangerous_actions: false`), a message matching patterns like `produção`/`production`, `deploy em produção`, `drop database`, `truncate`, `destroy`, `terraform destroy`, `kubectl delete`, `reset --hard`, `force push`/`git push --force`, `rm -rf` against a root-ish path, `revogar credenciais`, `rotacionar secrets` is **blocked** and returns `{ status: "blocked_by_policy", reason, requires_explicit_authorization: true }` — Cursor never even sees the message. Setting `allow_dangerous_actions: true` lets it through; the bridge never infers or remembers a prior authorization, and every call must set the flag explicitly. This is a deliberately simple, auditable second line of defense — not a semantic safety model, and not a substitute for real infra safeguards (branch protection, prod access controls, etc.).
- **Concurrency lock.** At most one active run per agent. A second `cursor_send_followup` while one is in flight returns `{ status: "busy", active_run_id }` immediately (checked both in-process and against the bridge's own SQLite `runs` table, so it survives a single-process restart's worth of bookkeeping).
- **Cancellation is never simulated.** `cursor_cancel_run` calls the real SDK cancel path; if the runtime reports it isn't supported, the bridge returns `{ supported: false, reason }` — it never claims success it can't back up.

## Connecting ChatGPT to cursor-chatgpt-bridge

As of the current ChatGPT MCP support (Developer Mode / "Apps & Connectors"), ChatGPT connects to **remote** MCP servers over **HTTPS** using the **Streamable HTTP** transport — it does not speak stdio. That is exactly what `/mcp` on this server implements.

1. **Expose the bridge over HTTPS.** ChatGPT requires a public HTTPS URL — plain HTTP is not accepted. Run the bridge behind a reverse proxy/load balancer that terminates TLS (nginx, Caddy, a cloud provider's HTTPS load balancer), or use a tunnel for testing (e.g. `cloudflared tunnel` or `ngrok http 3000`). Set `CURSOR_BRIDGE_TOKEN` before exposing it — never run this server on the public internet without it.
2. **Endpoint.** The MCP endpoint is `https://<your-domain>/mcp`. `GET /health` is available at `https://<your-domain>/health` for a quick liveness check (no auth required).
3. **Authenticate.** In ChatGPT, when adding the connector you'll be asked for an authentication method. Pick the option that lets you supply a static credential (labeled "Token"/"API key" depending on your ChatGPT version) and paste your `CURSOR_BRIDGE_TOKEN` value. ChatGPT then sends it as `Authorization: Bearer <token>` on every request, which is exactly what `src/security/auth.ts` expects.
   - **If your ChatGPT build only offers OAuth for custom connectors** (OpenAI has been moving toward requiring OAuth 2.1 + Dynamic Client Registration for some connector surfaces), a static bearer token cannot be entered directly in that flow. In that case, either (a) look for an explicit "no auth" / "API key in header" option in your ChatGPT version — availability of the Token option has varied across rollouts — or (b) put a small OAuth-terminating proxy in front of `/mcp` that authenticates the OAuth flow, then forwards `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>` upstream. This bridge intentionally keeps its own auth to a single well-understood mechanism (bearer token) per the spec that drove this project; see [Limitations](#limitations).
4. **Add the server.** In ChatGPT: **Settings → Apps & Connectors → Advanced settings → Developer mode** (enable it — Developer Mode requires a paid ChatGPT plan), then **Create connector** (or "Add custom connector"), fill in a name, the connector URL (`https://<your-domain>/mcp`), and the authentication method from step 3.
5. **Test it.** After saving, ChatGPT calls the MCP `initialize` + `tools/list` handshake immediately to populate the connector's tool list; if that succeeds you'll see the 10 `cursor_*` tools listed in the connector details. In a chat, enable the connector's tools (the same toggle used for other tools like web browsing) and ask something like *"List my Cursor agents"* — ChatGPT should call `cursor_list_agents`.

Because MCP connector UI names and steps in ChatGPT change over time, always cross-check against OpenAI's current documentation for "Developer Mode" / "Apps & Connectors" if a step above doesn't match what you see.

## Example flows

```text
Project: sunday

User (in ChatGPT): "Veja como está o agente do projeto Sunday e continue."

ChatGPT calls:
  cursor_list_projects
        ↓
  cursor_list_agents            (finds the agent tied to project "sunday")
        ↓
  cursor_get_conversation       (catches up on what already happened)
        ↓
  cursor_get_changes            (reviews branch/diff/status)
        ↓
  cursor_send_followup          (continues the work, wait_for_completion=true)
```

```text
User: "Revise o que o Cursor fez antes de deixar ele continuar."

ChatGPT calls:
  cursor_get_conversation
  cursor_get_changes

If something looks wrong, ChatGPT calls:
  cursor_send_followup   (with corrective instructions instead of "continue")
```

To make the first example work, register the project once (ChatGPT can do this too, via `cursor_project_register`):

```jsonc
// cursor_project_register
{
  "name": "sunday",
  "repository": "https://github.com/acme/sunday",
  "working_directory": "/repos/sunday", // only used for mode=local agents
  "default_branch": "main"
}
```

## Error codes

Every failure returns `{ "error": { "code": "...", "message": "...", "details"?: {...} } }`, never a bare stack trace:

| Code | Meaning |
| --- | --- |
| `UNAUTHORIZED` | Missing/invalid bearer token. |
| `PROJECT_NOT_FOUND` | `project` name not registered via `cursor_project_register`. |
| `AGENT_NOT_FOUND` | `agent_id` not known to the bridge. |
| `RUN_NOT_FOUND` | `run_id` not known to the bridge. |
| `AGENT_BUSY` | The SDK itself reported an active run mid-request (secondary guard behind the bridge's own lock). |
| `CURSOR_API_ERROR` | `@cursor/sdk` call failed (auth, rate limit, config, unsupported operation, missing `CURSOR_API_KEY`, etc.) — `details` carries what the SDK reported. |
| `RUN_TIMEOUT` | Reserved for future use; today a client-side wait timeout is reported as `status: "timeout"` in the tool result rather than this error code, since it is not a failure — the run may still be active. |
| `BLOCKED_BY_POLICY` | Reserved error code; `cursor_send_followup` currently reports policy blocks as a structured *result* (`status: "blocked_by_policy"`), not a thrown error, so ChatGPT can react to it without treating it as a hard failure. |
| `VALIDATION_ERROR` | Bridge-level input validation (e.g. `mode=local` without a `working_directory`). Schema-level validation errors (wrong types, missing required fields) are reported by the MCP SDK itself as a tool error before reaching the bridge. |
| `INTERNAL_ERROR` | Anything unexpected. |

## Limitations

- **`@cursor/sdk` is in public beta** (per Cursor's own docs); method names/shapes may change before general availability. The `CursorAgentProvider` seam (`src/cursor/types.ts`) exists specifically to contain the blast radius of such a change to `src/cursor/client.ts`.
- **This environment has no `CURSOR_API_KEY` and no network path to `api.cursor.com`.** Every SDK-touching code path was validated by (a) reading the official API/SDK docs and package types byte-for-byte against the code, (b) unit/integration tests against a `MockCursorAgentProvider` that implements the exact same interface, and (c) a full manual HTTP walkthrough of `/health`, `/mcp` auth, `initialize`, `tools/list`, and `tools/call` against the real server binary. It was **not** validated against a live Cursor account. Run `cursor-agent`'s own `/sdk` skill or a quick script against your real `CURSOR_API_KEY` before depending on this in production.
- **Cloud agents don't expose a file-level diff through the SDK.** `cursor_get_changes` for `mode=cloud` returns pushed branches and PR links (from `Run.git`), not an actual diff — the SDK doesn't proxy `git diff` out of the cloud VM. For a full diff on a cloud agent's work, open its branch/PR in your Git host, or run that agent in `mode=local` instead.
- **`cursor_cancel_run` depends on the SDK's own `run.supports("cancel")`.** In practice, finished runs and some runtimes report `supported: false` — this is surfaced verbatim, never worked around.
- **The dangerous-action policy is a keyword/pattern classifier**, not a semantic understanding of intent. It will have both false positives (blocking a legitimate mention of the word "production" in a code comment) and false negatives (a destructive instruction phrased in a way the patterns don't match). Treat it as a speed bump, not a guarantee.
- **The bridge only knows about agents it started or that were explicitly registered.** `cursor_list_agents`/`cursor_get_agent` read the bridge's own SQLite database, not every agent in your Cursor account. Pre-existing Cursor agents you started outside the bridge won't show up unless you resume them through it (a natural follow-up: an "import" tool backed by `Agent.get()`/`Agent.list({ runtime: "cloud" })`, deliberately left out of this MVP per the spec's own "known to the bridge" wording).
- **ChatGPT's MCP connector auth options can vary by rollout.** See the callout under [Connecting ChatGPT](#connecting-chatgpt-to-cursor-chatgpt-bridge) if your ChatGPT build doesn't offer a static-token option for custom connectors.
- **`@connectrpc/connect-node` (a transitive dependency of `@cursor/sdk`) pulls in an `undici` version with known advisories** (`npm audit` reports 2 moderate + 1 high, all inside `@cursor/sdk`'s own dependency tree, not this project's code). There is no fix available upstream yet (`fixAvailable: false`); track Cursor's SDK releases for an update.
