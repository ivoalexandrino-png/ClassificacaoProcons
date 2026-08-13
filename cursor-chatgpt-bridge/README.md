# cursor-chatgpt-bridge

MCP server that bridges **ChatGPT** and **Cursor Agents**, so you never have to copy messages between the two by hand.

```text
ChatGPT
   ↓  (remote MCP over HTTPS)
cursor-chatgpt-bridge
   ↓  (official @cursor/sdk)
Cursor Agent (cloud VM or local working directory)
   ↓
repository / code / tests
   ↓
result → bridge → ChatGPT
```

ChatGPT acts as **supervisor / architect / reviewer**; Cursor is the **executor**. The bridge adds persistence, authentication, a dangerous-action policy, per-agent locking and timeouts in between.

## How it talks to Cursor

The bridge uses the **official Cursor SDK** ([`@cursor/sdk`](https://cursor.com/docs/sdk/typescript)), which wraps the [Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints):

| Bridge operation | Cursor SDK API |
| --- | --- |
| Start agent | `Agent.create({ apiKey, cloud: { repos } })` or `Agent.create({ apiKey, local: { cwd } })` |
| Resume + follow-up (context preserved) | `Agent.resume(agentId, { apiKey })` → `agent.send(message)` |
| Wait for result | `run.wait()` → `{ status, result, git }` |
| List / inspect | `Agent.list()`, `Agent.get()`, `Agent.getRun()` |
| Cancel | `Agent.cancelRun(runId, ...)` |

Cloud agents get `bc-...` IDs and run on Cursor-managed VMs against a GitHub repo. Local agents (`agent-...` IDs) run **on the bridge host** against a local working directory — use them when the bridge runs on the machine that has the checkout.

Everything that passes through the bridge (prompts, responses, run status, timestamps) is persisted in SQLite, so `cursor_get_conversation` works even where the Cursor API does not expose full history.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `cursor_list_agents` | List agents/sessions known to the bridge (merged with the Cursor Cloud API) |
| `cursor_get_agent` | Agent details: project, repo, branch, status, active run, capabilities |
| `cursor_get_conversation` | Recent messages (`user` / `assistant` / `tool` / `system`) recorded by the bridge |
| `cursor_send_followup` | Resume an existing agent and send a follow-up (the important one) |
| `cursor_start_agent` | Start a new agent session (`cloud` or `local`) |
| `cursor_get_run` | Status/result of a run (refreshes from the Cursor API when still running) |
| `cursor_cancel_run` | Cancel an active run — returns `supported: false` when it can't, never simulates |
| `cursor_get_changes` | Review changes: `git status`/`diff` for local agents, pushed branches/PRs for cloud agents |
| `cursor_project_register` | Register a project (name → repo / working dir / default branch) |
| `cursor_list_projects` | List registered projects |

All errors are structured — never a stack trace:

```json
{ "error": { "code": "AGENT_NOT_FOUND", "message": "Cursor agent not found", "details": {} } }
```

Codes: `UNAUTHORIZED`, `PROJECT_NOT_FOUND`, `AGENT_NOT_FOUND`, `RUN_NOT_FOUND`, `AGENT_BUSY`, `CURSOR_API_ERROR`, `RUN_TIMEOUT`, `BLOCKED_BY_POLICY` (returned as `status: "blocked_by_policy"`), `INVALID_INPUT`, `NOT_CONFIGURED`, `INTERNAL_ERROR`.

## Installation

Requires **Node.js ≥ 22.13** (constraint of `@cursor/sdk`).

```bash
npm install
```

## Configuration

```bash
cp .env.example .env
```

| Variable | Required | Description |
| --- | --- | --- |
| `PORT` | no (3000) | HTTP port |
| `CURSOR_BRIDGE_TOKEN` | **yes** (HTTP mode) | Bearer token MCP clients must send. The server refuses to start over HTTP without it. Generate: `openssl rand -hex 32` |
| `CURSOR_API_KEY` | yes | Cursor user API key from [cursor.com/dashboard/api](https://cursor.com/dashboard/api) |
| `DATABASE_PATH` | no (`./data/bridge.db`) | SQLite file |
| `CURSOR_RUN_TIMEOUT_MS` | no (900000) | Max wait when `wait_for_completion=true`. On timeout the run is recorded as `timeout` (never success) and stays queryable via `cursor_get_run` |
| `LOG_LEVEL` | no (`info`) | `debug`/`info`/`warn`/`error` — structured JSON logs, secrets are never logged |
| `MAX_DIFF_CHARS` | no (30000) | Default diff cap for `cursor_get_changes` |

Export the variables (or use your process manager / `docker run --env-file`). The server reads plain environment variables; a `.env` loader is intentionally not bundled — in dev you can run `export $(grep -v '^#' .env | xargs)` or `node --env-file=.env dist/index.js`.

## Development

```bash
npm run dev          # tsx watch src/index.ts (HTTP on $PORT, endpoint /mcp)
```

## Build

```bash
npm run build
npm start            # HTTP transport (remote MCP for ChatGPT)
npm run start:stdio  # STDIO transport (local MCP clients: Cursor, Claude Desktop)
```

## Tests

```bash
npm test
npm run lint
```

The Cursor SDK is mocked in tests (in-memory provider); everything runs offline.

## Docker

```bash
docker build -t cursor-chatgpt-bridge .
docker run -d --name cursor-bridge \
  -p 3000:3000 \
  -e CURSOR_BRIDGE_TOKEN="$(openssl rand -hex 32)" \
  -e CURSOR_API_KEY="key_..." \
  -v cursor-bridge-data:/app/data \
  cursor-chatgpt-bridge
```

Health check: `curl http://localhost:3000/health` →

```json
{ "status": "ok", "service": "cursor-chatgpt-bridge", "cursor_sdk_configured": true, "database": "ok" }
```

## Connecting ChatGPT to cursor-chatgpt-bridge

ChatGPT connects to **remote MCP servers over HTTPS** (Streamable HTTP). Custom connectors require **Developer Mode**, available on ChatGPT Pro / Team / Enterprise / Edu.

### 1. Expose the bridge over HTTPS

ChatGPT will not call plain HTTP or localhost. Options:

- deploy to any host with TLS (Fly.io, Railway, Cloud Run, a VPS behind Caddy/nginx);
- or tunnel during development: `cloudflared tunnel --url http://localhost:3000` / `ngrok http 3000`.

The MCP endpoint is:

```text
https://<your-host>/mcp
```

### 2. Authentication

Every `/mcp` request must carry:

```text
Authorization: Bearer <CURSOR_BRIDGE_TOKEN>
```

In ChatGPT's connector dialog, pick the API-key / access-token authentication option and paste the value of `CURSOR_BRIDGE_TOKEN` (ChatGPT sends it as a Bearer token). Requests without it get `401 UNAUTHORIZED` — the bridge never runs unauthenticated over HTTP.

### 3. Add the connector in ChatGPT

1. ChatGPT → profile → **Settings** → **Connectors**.
2. Under **Advanced**, enable **Developer mode** (workspace admins must allow it on Team/Enterprise).
3. Click **Add custom connector** (Create).
4. Name: `Cursor Bridge`. URL: `https://<your-host>/mcp`.
5. Authentication: API key / access token → paste `CURSOR_BRIDGE_TOKEN`.
6. Accept the trust warning and save; wait for the tool scan to finish.

### 4. Verify

- The connector page should list the ten `cursor_*` tools after the scan.
- In a chat (with the connector enabled, e.g. via developer mode tool selection), ask: *"List my Cursor agents"* — ChatGPT should call `cursor_list_agents`.
- From a terminal you can verify the same thing ChatGPT does:

```bash
curl -s -X POST https://<your-host>/mcp \
  -H "Authorization: Bearer $CURSOR_BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Real usage examples

Register the project once (via ChatGPT or curl):

```text
"Registre o projeto sunday: repo https://github.com/org/sunday, branch main."
→ cursor_project_register
```

Daily flow:

```text
User: "Veja como está o agente do projeto Sunday e continue."

ChatGPT:
  cursor_list_projects        → finds "sunday"
  cursor_list_agents          → finds the agent linked to sunday
  cursor_get_conversation     → reads what happened
  cursor_get_changes          → reviews branch/diff/PR
  cursor_send_followup        → "continue: ..." (context preserved)
```

Review-first flow:

```text
User: "Revise o que o Cursor fez antes de deixar ele continuar."

ChatGPT:
  cursor_get_conversation
  cursor_get_changes
  → if a problem is found:
  cursor_send_followup ("fix X before continuing")
```

## Security model

- **Bearer auth** on every MCP request, compared in constant time. No token → no HTTP server.
- **Policy layer**: messages matching dangerous patterns (produção/production/prod, drop database, truncate, apagar banco, terraform destroy, kubectl delete, reset --hard, force push, rm -rf, revogar credenciais, rotacionar secrets, …) are answered with `status: "blocked_by_policy"` and `requires_explicit_authorization: true`. The caller must resend with `allow_dangerous_actions: true` after a human explicitly authorized it — the bridge never assumes authorization. This is a keyword barrier, not a complete defense; the structural boundary is that Cursor agents work on branches and never deploy silently.
- **Concurrency**: one active run per agent. A second follow-up returns `{ "status": "busy", "active_run_id": "..." }`.
- **Timeouts**: `CURSOR_RUN_TIMEOUT_MS` caps synchronous waits; timed-out runs are recorded as `timeout` (never success) and keep being tracked in the background.
- **Secrets**: tokens/API keys are read from env, never logged, never returned by any tool. `data/` and `.env` are git-ignored.

## Limitations

- The Cloud Agents API does not expose a full file diff for cloud agents; `cursor_get_changes` returns pushed branches/PR URLs for those (review the PR on GitHub). Full `git status`/`diff` is available for agents with a local `working_directory`.
- Conversation history is what passed through the bridge (plus run results fetched from the API). Sessions started outside the bridge appear via `cursor_list_agents`, but their earlier messages are not backfilled.
- `local` mode runs the agent on the bridge host and requires the repo checkout to exist there (and `@cursor/sdk`'s platform sandbox support).
- ChatGPT custom connectors require Developer Mode (paid plans) and an HTTPS-reachable server.
