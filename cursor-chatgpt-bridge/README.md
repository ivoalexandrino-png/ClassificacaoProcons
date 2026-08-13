# cursor-chatgpt-bridge

MCP bridge between **ChatGPT** (supervisor) and **Cursor Agents** (executor), using the official Cursor TypeScript SDK (`@cursor/sdk`) and the official MCP SDK (Streamable HTTP).

```text
ChatGPT
   ↓
MCP remote (HTTPS + Bearer token)
   ↓
cursor-chatgpt-bridge
   ↓
@cursor/sdk (Agent.create / Agent.resume / send / wait / cancel)
   ↓
repository / code / tests
   ↓
structured result back to ChatGPT
```

## Requirements

- Node.js **>= 22.13**
- A Cursor API key from [Cursor Dashboard → API Keys](https://cursor.com/dashboard/api)
- A strong random bridge token (`CURSOR_BRIDGE_TOKEN`)

## Installation

```bash
cd cursor-chatgpt-bridge
npm install
```

## Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```env
PORT=3000
HOST=0.0.0.0
CURSOR_BRIDGE_TOKEN=replace-with-a-long-random-secret
CURSOR_API_KEY=cursor_...
DATABASE_PATH=./data/bridge.db
CURSOR_RUN_TIMEOUT_MS=900000
CURSOR_DEFAULT_MODEL=composer-2.5
ALLOWED_HOSTS=localhost,127.0.0.1,your-tunnel-hostname.example.com
LOG_LEVEL=info
```

Never commit `.env`. Secrets are never written to logs.

## Development

```bash
npm run dev
```

STDIO mode (local MCP clients such as Cursor/Claude Desktop):

```bash
npm run dev:stdio
```

## Build

```bash
npm run build
npm start
```

## Test / lint

```bash
npm test
npm run lint
```

## Docker

```bash
docker build -t cursor-chatgpt-bridge .
docker run --rm -p 3000:3000 \
  -e CURSOR_BRIDGE_TOKEN=replace-me \
  -e CURSOR_API_KEY=cursor_... \
  -e ALLOWED_HOSTS=localhost,127.0.0.1,your-public-host.example.com \
  -v "$PWD/data:/app/data" \
  cursor-chatgpt-bridge
```

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | no | Liveness / dependency status |
| `POST/GET/DELETE` | `/mcp` | Bearer | MCP Streamable HTTP endpoint |

Health example:

```bash
curl -s http://127.0.0.1:3000/health
```

```json
{
  "status": "ok",
  "service": "cursor-chatgpt-bridge",
  "cursor_sdk_configured": true,
  "database": "ok"
}
```

## MCP tools

| Tool | Role |
| --- | --- |
| `cursor_list_projects` | List registered projects |
| `cursor_project_register` | Register project name → repo/cwd |
| `cursor_list_agents` | List bridge-known agents/sessions |
| `cursor_get_agent` | Agent details + active run |
| `cursor_get_conversation` | Recent prompts/responses/events |
| `cursor_start_agent` | Create local/cloud agent + first prompt |
| `cursor_send_followup` | Resume agent and send follow-up |
| `cursor_get_run` | Run status/result |
| `cursor_cancel_run` | Cancel run via official SDK |
| `cursor_get_changes` | Local git status/diff (cloud: metadata) |

## Connecting ChatGPT to cursor-chatgpt-bridge

ChatGPT connects to **remote MCP servers over HTTPS** (Streamable HTTP / SSE). It does **not** launch local stdio processes.

Official ChatGPT path (Developer mode), as documented by OpenAI:

1. Use a **paid** ChatGPT plan that supports Developer mode (Plus/Pro/Business/Enterprise/Edu).
2. In ChatGPT (web): **Settings → Security and login → Developer mode** → enable.
3. Expose this bridge on a public **HTTPS** URL.
4. Create a developer-mode app/connector pointing at the MCP endpoint.
5. In a chat, open the **+** menu → **Developer mode** → select the app/connector.

### 1) Expose the MCP server over HTTPS

Run the bridge locally or in Docker, then put TLS in front of it.

Example with a tunnel (development):

```bash
npm run dev
# in another terminal
ngrok http 3000
```

Use the HTTPS origin, for example:

```text
https://<your-ngrok-subdomain>.ngrok-free.app
```

Production alternatives: Cloud Run / Fly.io / a VPS behind Caddy or nginx with TLS.

Update `ALLOWED_HOSTS` to include the public hostname (no scheme/port):

```env
ALLOWED_HOSTS=localhost,127.0.0.1,<your-ngrok-subdomain>.ngrok-free.app
```

### 2) MCP endpoint URL

Configure ChatGPT with:

```text
https://<public-host>/mcp
```

Transport: **Streamable HTTP** (also compatible with clients that still speak SSE-style streaming on POST).

### 3) Authentication

The bridge requires:

```http
Authorization: Bearer <CURSOR_BRIDGE_TOKEN>
```

When creating the ChatGPT developer-mode connector/app:

- Prefer authentication type **Token** / bearer-style custom auth when the UI offers it.
- Paste the same value as `CURSOR_BRIDGE_TOKEN`.

If your ChatGPT workspace only offers **OAuth** or **No authentication** for a given connector type:

- Do **not** disable bridge auth.
- Keep Bearer auth enabled on `/mcp`.
- Put a trusted reverse proxy / tunnel in front that injects `Authorization: Bearer …` for ChatGPT traffic, or use a connector path that can send the token header.
- `/health` remains unauthenticated for probes only.

### 4) Add the server in ChatGPT

1. Enable **Developer mode**.
2. Go to ChatGPT apps/plugins/connectors UI (the developer-mode app creator shown after Developer mode is on).
3. Create a new developer-mode app for your remote MCP server.
4. Set:
   - **Name**: `cursor-chatgpt-bridge`
   - **Connector URL / MCP URL**: `https://<public-host>/mcp`
   - **Authentication**: Token / Bearer with `CURSOR_BRIDGE_TOKEN`
5. Save. The app appears under drafts/apps and can be attached from the composer **Developer mode** tool picker.

Supported protocols per OpenAI docs: **SSE** and **streaming HTTP**.

### 5) Verify tools are available

In a Developer mode conversation with the app selected, ask:

```text
List the tools from cursor-chatgpt-bridge and call cursor_list_projects.
```

Or:

```text
Use cursor_list_agents to list my Cursor agents.
```

You should see tool calls such as `cursor_list_projects` / `cursor_list_agents`. Expand the tool payload in the UI to inspect JSON input/output.

## Example usage

### Continue the Sunday agent

```text
User (ChatGPT):
"Veja como está o agente do projeto Sunday e continue."

ChatGPT:
1. cursor_list_projects
2. cursor_list_agents
3. cursor_get_conversation
4. cursor_get_changes
5. cursor_send_followup
```

### Review before continuing

```text
User:
"Revise o que o Cursor fez antes de deixar ele continuar."

ChatGPT:
1. cursor_get_conversation
2. cursor_get_changes
3. If issues are found → cursor_send_followup with review instructions
```

### Register a project once

```json
{
  "name": "sunday",
  "repository": "https://github.com/your-org/sunday.git",
  "working_directory": "/absolute/path/to/sunday",
  "default_branch": "main"
}
```

Tool: `cursor_project_register`

Then start:

```json
{
  "project": "sunday",
  "message": "Inspect the repo and summarize open work",
  "mode": "local"
}
```

Tool: `cursor_start_agent`

Use `"mode": "cloud"` when you want Cursor-hosted VMs (`bc-…` agent ids). Local mode requires a valid `working_directory` on the machine running the bridge.

## Security model

- **Bearer auth** on `/mcp` (`CURSOR_BRIDGE_TOKEN`, timing-safe compare).
- **Policy layer** blocks prompts mentioning production deploys, destructive DB/git/k8s/terraform actions, credential revocation, etc., unless `allow_dangerous_actions=true`.
- The bridge never invents authorization.
- Secrets are redacted from structured logs.
- One in-flight follow-up per `agent_id` (returns `status: "busy"`).

## Cursor SDK notes

Package: `@cursor/sdk` (pinned to current stable line in `package.json`).

Used APIs:

- `Agent.create({ local | cloud })`
- `Agent.resume(agentId)`
- `agent.send(message)` → `Run`
- `run.wait()`, `run.stream()`, `run.cancel()`
- `Agent.get`, `Agent.list`, `Agent.getRun`, `Agent.cancelRun`
- `Agent.messages.list` (local conversation; bridge also persists its own history)

Runtime selection:

- `local: { cwd }` → local agent loop on the bridge host
- `cloud: { repos: [{ url, startingRef }] }` → Cursor-hosted cloud agent

## Architecture

```text
src/
  index.ts          CLI entry (HTTP or --stdio)
  server.ts         Express + Streamable HTTP + /health
  config.ts         env loading
  cursor/
    client.ts       CursorAgentProvider (SDK + mock)
    agents.ts       agent orchestration + git changes
    runs.ts         run status/cancel
  mcp/tools.ts      MCP tool registration
  storage/store.ts  SQLite persistence (node:sqlite)
  security/         bearer auth + dangerous-action policy
```

## Limitations

- ChatGPT requires a reachable HTTPS MCP URL; localhost alone is not enough without a tunnel.
- Cloud conversation transcripts are not fully exposed by `Agent.messages.list` (local-oriented). The bridge persists every prompt/response that flows through it.
- `cursor_get_changes` returns full git diffs for **local** agents; cloud agents get metadata guidance.
- Cancel is only reported as successful when the official SDK cancel API succeeds; the bridge never fakes cancellation.
- SDK APIs are in public beta and may evolve; the `CursorAgentProvider` abstraction isolates those changes.
