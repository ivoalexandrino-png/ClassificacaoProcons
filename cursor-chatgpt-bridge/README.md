# cursor-chatgpt-bridge

MCP server that bridges **ChatGPT** and **Cursor Agents** using the official `@cursor/sdk` and Cloud Agents API patterns.

ChatGPT supervises; Cursor executes code in your repository.

## Features

- MCP tools to list agents, read conversation history, inspect git changes, send follow-ups, and manage runs
- Official Cursor SDK integration (`Agent.create`, `Agent.resume`, `agent.send`, run cancel)
- SQLite persistence for projects, agents, runs, and messages
- Bearer token authentication on HTTP transport
- Policy layer blocking dangerous production/destructive instructions by default
- Streamable HTTP MCP endpoint for remote ChatGPT connections
- Optional STDIO transport for local clients

## Requirements

- Node.js **22.13+**
- `CURSOR_API_KEY` from [Cursor Dashboard → API Keys](https://cursor.com/dashboard/api)
- `CURSOR_BRIDGE_TOKEN` — your own secret for MCP HTTP auth

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
MCP_PATH=/mcp
CURSOR_BRIDGE_TOKEN=your-long-random-bridge-token
CURSOR_API_KEY=your-cursor-api-key
DATABASE_PATH=./data/bridge.db
CURSOR_RUN_TIMEOUT_MS=900000
LOG_LEVEL=info
TRANSPORT=http
CURSOR_DEFAULT_MODEL=composer-2.5
```

## Development

```bash
npm run dev
```

Health check:

```bash
curl http://localhost:3000/health
```

## Build

```bash
npm run build
npm start
```

## Tests

```bash
npm test
```

## Docker

```bash
docker build -t cursor-chatgpt-bridge .
docker run --rm -p 3000:3000 \
  -e CURSOR_BRIDGE_TOKEN=your-bridge-token \
  -e CURSOR_API_KEY=your-cursor-api-key \
  -v "$(pwd)/data:/app/data" \
  cursor-chatgpt-bridge
```

## Connecting ChatGPT to cursor-chatgpt-bridge

ChatGPT connects to **remote MCP servers** over HTTPS using **Streamable HTTP** (single endpoint, POST with JSON-RPC). This bridge exposes:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check (no auth) |
| `POST /mcp` | MCP Streamable HTTP endpoint (auth required) |

### 1. Expose the server over HTTPS

ChatGPT requires a **public HTTPS URL**. Options:

- Deploy to Cloud Run, Fly.io, Railway, or a VPS behind nginx/Caddy with TLS
- For local testing only: use a tunnel (e.g. `ngrok http 3000`) — do not leave production tokens on public tunnels

Example with ngrok:

```bash
npm run dev
ngrok http 3000
```

Your MCP URL becomes: `https://<subdomain>.ngrok-free.app/mcp`

### 2. Authentication

Every MCP request must include:

```http
Authorization: Bearer <CURSOR_BRIDGE_TOKEN>
```

Set the same value in `.env` as `CURSOR_BRIDGE_TOKEN`.

### 3. Add the MCP server in ChatGPT

As of current ChatGPT MCP documentation:

1. Open ChatGPT settings (web or desktop app with MCP support).
2. Go to **Apps** or **Connectors** / **MCP servers** (exact label varies by client version).
3. Add a **Streamable HTTP** (or remote HTTP) MCP server.
4. Set the server URL to your HTTPS endpoint, e.g. `https://your-host/mcp`.
5. Configure authentication:
   - **Bearer token** header: `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>`
6. Save and restart the connector if prompted.

For Codex/CLI-style clients using `config.toml`, equivalent configuration:

```toml
[mcp_servers.cursor_bridge]
url = "https://your-host/mcp"
bearer_token_env_var = "CURSOR_BRIDGE_TOKEN"
```

### 4. Verify tools are available

Ask ChatGPT:

```text
List my Cursor agents using cursor_list_agents.
```

Or call health from your machine:

```bash
curl -s http://localhost:3000/health | jq
```

Test MCP auth (should return 401 without token):

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:3000/mcp
```

With token (initialize-style POST; exact body depends on MCP client):

```bash
curl -s -X POST http://localhost:3000/mcp \
  -H "Authorization: Bearer $CURSOR_BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## MCP tools

| Tool | Description |
|------|-------------|
| `cursor_list_agents` | List agents known to the bridge |
| `cursor_get_agent` | Agent details by `agent_id` |
| `cursor_get_conversation` | Recent messages from bridge persistence |
| `cursor_send_followup` | Send follow-up to existing agent |
| `cursor_start_agent` | Start new local or cloud agent |
| `cursor_get_run` | Run status and result |
| `cursor_cancel_run` | Cancel run when API supports it |
| `cursor_get_changes` | Git diff for local agent working directory |
| `cursor_project_register` | Register project name → repo/path |
| `cursor_list_projects` | List registered projects |

## Example workflow

**Project:** `sunday`

User in ChatGPT:

```text
Veja como está o agente do projeto Sunday e continue.
```

ChatGPT calls:

1. `cursor_list_projects`
2. `cursor_list_agents`
3. `cursor_get_conversation`
4. `cursor_get_changes`
5. `cursor_send_followup`

**Review before continuing:**

```text
Revise o que o Cursor fez antes de deixar ele continuar.
```

ChatGPT calls `cursor_get_conversation` and `cursor_get_changes`, then `cursor_send_followup` if appropriate.

## Register a project

Use `cursor_project_register`:

```json
{
  "name": "sunday",
  "repository": "https://github.com/your-org/sunday",
  "working_directory": "/path/to/sunday",
  "default_branch": "main"
}
```

Then start or continue agents tied to that project via `cursor_start_agent` with `"project": "sunday"`.

## Security

- **Never** expose the bridge without `CURSOR_BRIDGE_TOKEN`
- **Never** commit `.env` or API keys
- Dangerous instructions (production deploy, `terraform destroy`, force push, etc.) are blocked unless `allow_dangerous_actions: true` is explicitly set on `cursor_send_followup`
- The bridge does not infer authorization — ChatGPT must pass the flag explicitly

## STDIO mode

For local MCP clients (Cursor, Claude Desktop with stdio):

```env
TRANSPORT=stdio
```

```bash
npm run build
node dist/index.js
```

Configure the client to spawn that command. HTTP Bearer auth is not used in stdio mode.

## Architecture

```text
ChatGPT → MCP (HTTP/stdio) → cursor-chatgpt-bridge → @cursor/sdk → Cursor Agent
                ↓
           SQLite (projects, agents, runs, messages)
```

## Error codes

| Code | Meaning |
|------|---------|
| `UNAUTHORIZED` | Missing/invalid bridge token |
| `PROJECT_NOT_FOUND` | Project name not registered |
| `AGENT_NOT_FOUND` | Agent ID not in bridge store |
| `RUN_NOT_FOUND` | Run ID not found |
| `AGENT_BUSY` | Concurrent run on same agent |
| `CURSOR_API_ERROR` | Cursor SDK/API failure |
| `RUN_TIMEOUT` | Run exceeded `CURSOR_RUN_TIMEOUT_MS` |
| `BLOCKED_BY_POLICY` | Dangerous instruction blocked |
| `INTERNAL_ERROR` | Unexpected server error |

## Limitations

- Cloud agent conversation history depends on bridge persistence (everything sent through the bridge is stored)
- `cursor_get_changes` works for **local** agents with a `working_directory`
- Local agents require the working directory to exist on the machine running the bridge
- Cloud agents require a connected GitHub repository URL
- `@cursor/sdk` requires Node 22.13+ and bills through your Cursor plan like IDE agents

## License

MIT
