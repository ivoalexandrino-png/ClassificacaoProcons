# cursor-chatgpt-bridge

A remote **MCP (Model Context Protocol) server** that bridges **ChatGPT** to **Cursor Agents** using the official [`@cursor/sdk`](https://www.npmjs.com/package/@cursor/sdk). It lets ChatGPT act as a supervisor/reviewer of a Cursor agent — listing sessions, reading the conversation, reviewing diffs, and sending follow-up prompts — **without copying messages by hand** between the two tools.

```text
ChatGPT → remote MCP → cursor-chatgpt-bridge → Cursor SDK / Cursor Agent → repo/code/tests → result → bridge → ChatGPT
```

The division of responsibility is deliberate:

```text
ChatGPT = supervisor / architect / reviewer
Cursor  = executor
```

---

## Architecture

- **Transport** — MCP over **Streamable HTTP** (for remote ChatGPT connectors) and optionally **stdio** (for local MCP clients). Bearer-token authenticated.
- **`src/cursor/`** — a thin `CursorAgentProvider` abstraction over `@cursor/sdk` (`client.ts`), run normalization/timeouts (`runs.ts`), and per-agent concurrency locking (`agents.ts`). Nothing else imports the SDK directly, so future SDK changes are isolated to one file.
- **`src/mcp/`** — Zod input schemas (`schemas.ts`) and the tool handlers + MCP registration (`tools.ts`). Handlers are pure functions of a `ToolContext`, so they are unit-tested without any transport.
- **`src/storage/`** — SQLite persistence (`store.ts`) for `projects`, `agents`, `runs`, and `messages`. Everything that flows through the bridge is recorded so ChatGPT can reconstruct a session.
- **`src/security/`** — bearer auth with constant-time compare (`auth.ts`) and a dangerous-action policy layer (`policy.ts`).
- **`src/git/`** — structured, size-bounded `git status`/`diff` for local agents.
- **`src/server.ts` / `src/index.ts`** — Express app (`/health`, `/mcp`), transport selection, structured logging, graceful shutdown.

### Cursor SDK usage

| Item | Detail |
| --- | --- |
| Package | `@cursor/sdk` (`^1.0.27`) |
| Runtime | Node.js **22.13+** (SDK requirement) |
| Auth | `CURSOR_API_KEY` (user or service-account key) |
| Create agent | `Agent.create({ apiKey, model, local: { cwd, store } })` or `{ cloud: { repos } }` |
| Resume agent | `Agent.resume(agentId, options)` — runtime auto-detected (`bc-` = cloud, else local) |
| Send follow-up | `agent.send(message, { model })` → `Run` |
| Read result | `run.wait()` → `{ status, result, error, git }` |
| Inspect | `Agent.get` / `Agent.list` / `Agent.getRun` / `Agent.listRuns` |
| Cancel | `run.cancel()` / `Agent.cancelRun(runId, options)` |
| Local persistence | `JsonlLocalAgentStore` so local agents survive restarts |

**Local vs cloud** is chosen by which key is passed to `Agent.create()`. "Local" means the agent loop and file access run in this process against a working directory; "cloud" runs in a Cursor-hosted VM with your repo cloned in. Both use the same `CURSOR_API_KEY`; all inference is hosted by Cursor either way.

---

## MCP tools

| Tool | Purpose |
| --- | --- |
| `cursor_list_agents` | List agents/sessions known to the bridge (optionally include cloud agents from the SDK). |
| `cursor_get_agent` | Details, status, active run, metadata, and capabilities for one agent. |
| `cursor_get_conversation` | Recent messages + runs so ChatGPT can catch up on a session. |
| `cursor_send_followup` | Resume an agent, send a follow-up, wait for the result, persist it, return structured output. |
| `cursor_start_agent` | Start a new agent (`local` or `cloud`) for a project/repository. |
| `cursor_get_run` | Status/response of a run by id (refreshed from the SDK when still active). |
| `cursor_cancel_run` | Cancel an active run when the API supports it (never simulated). |
| `cursor_get_changes` | Review changes: `git status`/`diff` for local agents; branch/PR for cloud. |
| `cursor_project_register` | Register a project so it can be resolved by name later. |
| `cursor_list_projects` | List registered projects. |

All tools return both a human-readable text block and `structuredContent` so ChatGPT can decide the next step programmatically. `cursor_send_followup` also accepts `wait_for_completion` (default `true`) and `allow_dangerous_actions` (default `false`).

---

## Security

- **Authentication** — every `/mcp` request must send `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>`. The token is compared in constant time. If no token is configured the server **fails closed** and rejects all MCP requests. Never expose the bridge publicly without a token.
- **Dangerous-action policy** — `cursor_send_followup` and `cursor_start_agent` screen the prompt for production/destructive patterns (`production`/`produção`, `deploy to production`, `drop database`, `truncate`, `terraform destroy`, `kubectl delete`, `reset --hard`, `git push --force`, `rm -rf`, secret rotation/revocation, etc.). A match returns `{ "status": "blocked_by_policy", "requires_explicit_authorization": true }`. To proceed, the caller must set `allow_dangerous_actions: true` — the bridge never fabricates that authorization. This is a pragmatic extra barrier, not a perfect filter.
- **Secret handling** — the structured logger redacts token/API-key/secret fields, and secrets are never logged or returned. `.env` is git-ignored; only `.env.example` is committed.
- **Concurrency** — one active run per agent. A second `cursor_send_followup` while a run is in flight returns `{ "status": "busy", "active_run_id": "..." }`.

---

## Installation

```bash
npm install
```

Requires Node.js 22.13+ (`node --version`).

## Configuration

```bash
cp .env.example .env
# then edit .env and set at least CURSOR_BRIDGE_TOKEN and CURSOR_API_KEY
```

Generate a strong token, e.g. `openssl rand -hex 32`.

## Development

```bash
npm run dev
```

Starts the HTTP transport with hot reload on `http://localhost:3000` (`/mcp` endpoint, `/health` for status).

## Build

```bash
npm run build
npm start
```

## Tests

```bash
npm test
```

## Lint / typecheck

```bash
npm run lint
npm run typecheck
```

## Docker

```bash
docker build -t cursor-chatgpt-bridge .

docker run --rm -p 3000:3000 \
  -e CURSOR_BRIDGE_TOKEN="$CURSOR_BRIDGE_TOKEN" \
  -e CURSOR_API_KEY="$CURSOR_API_KEY" \
  -v "$(pwd)/data:/app/data" \
  cursor-chatgpt-bridge
```

Check it: `curl -s http://localhost:3000/health`.

---

## Connecting ChatGPT to cursor-chatgpt-bridge

ChatGPT connects to **remote** MCP servers over **HTTPS** (Streamable HTTP / SSE) — it cannot reach a local stdio server directly. Custom connectors require a paid plan (Pro/Team/Enterprise/Edu) with **Developer mode** enabled.

1. **Expose the bridge over HTTPS.**
   - Deploy it to a host with a public HTTPS URL (Cloud Run, Fly.io, a VM behind a TLS reverse proxy, etc.), **or**
   - For local testing, tunnel it: `ngrok http 3000` and use the generated `https://…` URL.
   - The MCP endpoint is `POST https://<your-host>/mcp`.

2. **Enable Developer mode in ChatGPT.** Settings → **Security and login** (or Connectors → Advanced) → turn on **Developer mode**. Accept the warning that custom connectors run third-party code on your behalf.

3. **Add the custom connector.** In Settings → Connectors → **Add custom connector** (or the composer's **+ → Developer mode**), enter:
   - **Name:** `Cursor Bridge`
   - **Description:** `Supervise Cursor agents`
   - **URL:** `https://<your-host>/mcp`
   - **Authentication:** choose **Token / API key** and provide the value of `CURSOR_BRIDGE_TOKEN` as a **Bearer** token.

4. **Test the connection.** Start a Developer-mode conversation, select the connector, and ask: *"List my Cursor projects."* ChatGPT should call `cursor_list_projects`. If tools don't appear, verify the URL returns 200 for `/health`, that the server speaks MCP over HTTP (not a plain REST API), and that the bearer token matches.

> Because ChatGPT developer-mode tools can perform write actions, keep the token secret, only connect servers you trust, and rely on the dangerous-action policy plus per-tool confirmation.

---

## Example usage

**"See how the Sunday agent is doing and continue."**

```text
cursor_list_projects        → find "sunday" and its agent
cursor_list_agents          → locate the agent_id
cursor_get_conversation     → read what happened
cursor_get_changes          → review the diff
cursor_send_followup         → tell Cursor to continue
```

**"Review what Cursor did before letting it continue."**

```text
cursor_get_conversation
cursor_get_changes
# if a problem is found:
cursor_send_followup   (with corrective instructions)
```

First-time setup for a project:

```text
cursor_project_register { "name": "sunday", "repository": "https://github.com/acme/sunday", "working_directory": "/repos/sunday", "default_branch": "main" }
cursor_start_agent      { "project": "sunday", "message": "Add tests for the auth module", "mode": "local" }
```

---

## Error handling

Errors are returned as a consistent envelope (never a raw stack trace):

```json
{ "error": { "code": "AGENT_NOT_FOUND", "message": "Cursor agent not found", "details": {} } }
```

Codes: `UNAUTHORIZED`, `PROJECT_NOT_FOUND`, `AGENT_NOT_FOUND`, `RUN_NOT_FOUND`, `AGENT_BUSY`, `CURSOR_API_ERROR`, `RUN_TIMEOUT`, `BLOCKED_BY_POLICY`, `VALIDATION_ERROR`, `INTERNAL_ERROR`.

`busy`, `blocked_by_policy`, `timeout`, and unsupported-cancel are returned as **normal structured responses** (not errors) so ChatGPT can decide the next step.

---

## Limitations

- **Cloud diffs** aren't fetched by the bridge; for cloud agents `cursor_get_changes` reports the branch/PR references and points you to Cursor. Full `git diff` is available for **local** agents only.
- **Local mode** requires the repository to exist on the bridge host at `working_directory`, and Node's platform sandbox support (per the SDK).
- **Cancellation** depends on `@cursor/sdk`; when the SDK/API key is not configured, `cursor_cancel_run` reports `supported: false` rather than simulating a cancel.
- **Concurrency** is enforced in-process (per-agent lock). A horizontally-scaled deployment would need a shared lock; run a single instance for the MVP.
- Some agent-specific API actions require an **agent-scoped Cursor API key** created under Cloud Agents settings.
