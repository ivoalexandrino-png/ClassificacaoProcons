# cursor-chatgpt-bridge

Authenticated MCP bridge that lets ChatGPT supervise durable Cursor Agent sessions without
copying prompts and results manually.

```text
ChatGPT → remote MCP → bridge → official Cursor SDK → repository
        ← structured tools ← SQLite ← run result / conversation / git
```

## What is implemented

- Stateless Streamable HTTP MCP endpoint at `/mcp`, plus optional stdio transport.
- Static bearer authentication on every HTTP MCP request.
- Official Cursor TypeScript SDK for local and cloud agents.
- Durable SQLite storage for projects, agents, runs, and messages.
- Per-agent concurrency lock: a second prompt returns `AGENT_BUSY`.
- Dangerous-action policy with explicit `allow_dangerous_actions` override.
- Bounded local git inspection and structured errors.
- Health endpoint at `GET /health`.

## Requirements

- Node.js 22.13 or newer (required by `@cursor/sdk`).
- A Cursor user or service-account API key. Team Admin API keys are not supported by the SDK.
- For cloud agents, the repository must be connected to Cursor and accessible to the API-key
  owner.
- For local agents, the configured working directory must exist on the bridge host.

## Installation

```bash
git clone <repository-url>
cd ClassificacaoProcons/cursor-chatgpt-bridge
npm install
cp .env.example .env
```

Generate a bridge token with at least 32 random bytes:

```bash
openssl rand -hex 32
```

Put that value in `CURSOR_BRIDGE_TOKEN`. Put a Cursor key from
[Cursor Dashboard → API Keys](https://cursor.com/dashboard/api) in `CURSOR_API_KEY`.
Never commit `.env`.

## Configuration

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `PORT` | no | `3000` | HTTP listen port |
| `HOST` | no | `0.0.0.0` | HTTP listen address |
| `CURSOR_BRIDGE_TOKEN` | yes | — | Static bearer token, minimum 32 characters |
| `CURSOR_API_KEY` | yes for unattended use | — | Cursor user or service-account key |
| `CURSOR_MODEL` | no | `composer-2.5` | Model passed to the Cursor SDK |
| `DATABASE_PATH` | no | `./data/bridge.db` | SQLite database |
| `CURSOR_RUN_TIMEOUT_MS` | no | `900000` | Synchronous MCP wait timeout |
| `MAX_DIFF_CHARS` | no | `30000` | Default maximum returned diff size |
| `LOG_LEVEL` | no | `info` | `debug`, `info`, `warn`, or `error` |

The process does not log either token. Cursor credentials are passed only to the official SDK.

## Development, test, and build

```bash
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
npm start
```

The remote MCP URL is:

```text
http://localhost:3000/mcp
```

Use HTTPS outside localhost. `GET /health` intentionally needs no token and exposes only health
booleans:

```bash
curl http://localhost:3000/health
```

For a local MCP host that launches child processes, stdio is also available:

```bash
npm run build
npm run start:stdio
```

Stdio has no HTTP authentication boundary and should only be used by a trusted local MCP host.

## Docker

```bash
docker build -t cursor-chatgpt-bridge .
docker run --rm -p 3000:3000 \
  --env-file .env \
  -v cursor-bridge-data:/app/data \
  cursor-chatgpt-bridge
```

For local Cursor agents, also mount each registered repository at the exact
`working_directory` stored in the bridge. Cloud mode does not need a repository volume.

## MCP tools

| Tool | Purpose |
|---|---|
| `cursor_list_agents` | List bridge-known Cursor sessions |
| `cursor_get_agent` | Read project, runtime, status, active run, metadata, and capabilities |
| `cursor_get_conversation` | Read persisted user/assistant/tool/system messages |
| `cursor_send_followup` | Resume the same Cursor agent and send a context-preserving follow-up |
| `cursor_start_agent` | Create a local or cloud Cursor agent, then submit the initial prompt |
| `cursor_get_run` | Read and, when possible, refresh a run |
| `cursor_cancel_run` | Call real SDK cancellation; never simulate cancellation |
| `cursor_get_changes` | Return bounded local git status, files, diff stat, diff, and commits |
| `cursor_project_register` | Register an immutable project mapping |
| `cursor_list_projects` | List registered projects |

Projects must be registered before `cursor_start_agent`. The start request's repository and
working directory must exactly match the registered project, which prevents a model from silently
redirecting a known project to another checkout. A project name cannot be rebound after
registration; register a new name for a deliberate migration.

## Cursor SDK behavior

This project uses `@cursor/sdk` 1.0.27:

- `Agent.create({ local: { cwd } })` creates a local durable agent.
- `Agent.create({ cloud: { repos } })` creates a cloud durable agent.
- `agent.agentId` is persisted immediately (`agent-*` local, `bc-*` cloud).
- `Agent.resume(agentId, options)` reattaches after a process restart.
- `agent.send(message)` creates one run and preserves the agent's prior conversation state.
- `run.wait()` returns final status/result; `run.conversation()` supplies available tool events.
- `Agent.getRun()` refreshes persisted run state.
- `run.cancel()` performs real local or cloud cancellation when `run.supports("cancel")` is true.

Local agents execute filesystem and tool work on the bridge host. Model inference still goes
through Cursor. Cloud agents execute in a Cursor environment. The bridge stores prompts, final
responses, and the assistant, thinking, tool, and shell steps exposed by `run.conversation()`.
The SDK currently exposes full stored user/assistant message listing only for local agents;
bridge-local persistence therefore remains the portable conversation source.

## Security and policy

Every `/mcp` request must include:

```http
Authorization: Bearer <CURSOR_BRIDGE_TOKEN>
```

Comparison is constant-time when token lengths match. Missing and incorrect tokens return
`401` with a standard error body. Keep the bridge behind HTTPS, a firewall, and rate limiting.

The policy blocks likely production/destructive instructions by default, including production
actions, database drop/truncate/delete, `terraform destroy`, `kubectl delete`,
`git reset --hard`, force push, critical `rm -rf`, and credential revocation/rotation. A caller
must set `allow_dangerous_actions: true` on that exact tool call to pass a matched instruction.
The bridge never infers authorization from conversation text.

This is defense in depth, not a complete command sandbox. Cursor's own review/sandbox controls,
repository protections, least-privilege credentials, and human approval remain necessary.

## Timeouts and concurrency

Only one run may be active per agent. The bridge checks both its in-process lock and persisted
run state. It returns `AGENT_BUSY` with `active_run_id` instead of queueing.

When synchronous waiting reaches `CURSOR_RUN_TIMEOUT_MS`, the bridge records `timeout` and returns
the run ID. It does not claim success and does not cancel the Cursor run. Call `cursor_get_run`
later to refresh terminal state, or `cursor_cancel_run` to request real cancellation.

## Connecting ChatGPT to cursor-chatgpt-bridge

ChatGPT requires a remote HTTPS MCP server; Streamable HTTP is the recommended transport. The
current official authenticated-app flow is OAuth 2.1, not an arbitrary permanent bearer token.
Consequently, do not expose this server without auth and do not pretend that the static bridge
token is a complete ChatGPT OAuth flow.

Use one of these supported deployment shapes:

1. Deploy the bridge privately and place an OAuth 2.1-capable gateway/authorization server in
   front of it.
2. Configure that gateway for authorization-code flow with PKCE, protected-resource metadata,
   token validation, refresh-token support (`offline_access`), and HTTPS.
3. Have the gateway authenticate ChatGPT, then replace the upstream authorization header with
   `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>`.
4. Expose the gateway route ending in `/mcp`, for example
   `https://cursor-bridge.example.com/mcp`.

For local/private development, ChatGPT supports a Secure MCP Tunnel instead of public exposure.
The tunnel or its upstream gateway must still supply the bridge bearer token.

In ChatGPT Business or Enterprise/Edu:

1. Ask a workspace admin to enable developer mode under
   `Workspace Settings → Permissions & Roles → Connected Data Developer mode / Create custom MCP connectors`.
2. Open `Settings → Apps`, choose `Create`, and provide the HTTPS `/mcp` endpoint and required
   metadata.
3. Select OAuth authentication and complete authorization through the gateway/IdP.
4. Choose `Scan Tools`; verify that all ten `cursor_*` tools are discovered.
5. In a new chat, enable the app and ask: “Liste meus agentes do Cursor.”

The exact availability of developer mode depends on the ChatGPT plan and workspace RBAC. Follow
the current official guides:

- [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461)
- [OpenAI Apps SDK authentication](https://developers.openai.com/apps-sdk/build/auth)
- [Build an MCP server](https://developers.openai.com/apps-sdk/build/mcp-server)

API clients that permit custom MCP headers can connect directly to the bridge's HTTPS `/mcp`
endpoint with the static bearer token, without the OAuth gateway.

## Example workflow

Register `sunday` once:

```json
{
  "name": "sunday",
  "repository": "https://github.com/example/sunday",
  "working_directory": "/workspace/sunday",
  "default_branch": "main"
}
```

User:

> Veja como está o agente do projeto Sunday e continue.

ChatGPT tool sequence:

```text
cursor_list_projects
→ cursor_list_agents
→ cursor_get_conversation
→ cursor_get_changes
→ cursor_send_followup
```

User:

> Revise o que o Cursor fez antes de deixar ele continuar.

ChatGPT calls `cursor_get_conversation` and `cursor_get_changes`, then calls
`cursor_send_followup` only if another implementation step is appropriate.

## Structured errors

Tool errors use:

```json
{
  "error": {
    "code": "AGENT_NOT_FOUND",
    "message": "Cursor agent not found",
    "details": {}
  }
}
```

Stable error-envelope codes include `UNAUTHORIZED`, `PROJECT_NOT_FOUND`, `AGENT_NOT_FOUND`,
`RUN_NOT_FOUND`, `AGENT_BUSY`, `CURSOR_API_ERROR`, `BLOCKED_BY_POLICY`, `INVALID_INPUT`, and
`INTERNAL_ERROR`. Long-running calls report timeout as run status `timeout`, preserving the run ID.

## Current limitations

- Native ChatGPT authenticated apps require OAuth 2.1. This MVP intentionally implements the
  requested static bearer resource-server boundary, so direct ChatGPT connection requires an
  OAuth gateway or Secure MCP Tunnel configuration that injects the bridge token.
- SQLite and in-process locking target a single bridge replica. Horizontal deployment needs a
  shared database and distributed lock.
- Cursor run dispatch and SQLite cannot share one atomic transaction. If the process dies after
  Cursor accepts a prompt but before local persistence commits, that run must be reconciled from
  Cursor manually.
- Full git diff inspection is local-only. Cloud results expose Cursor's returned branch/PR
  metadata when available.
- Untracked files appear in `files`/`git_status`, but their contents are not included in
  `git diff HEAD`.
- The dangerous-action policy is heuristic and must not replace least privilege or human review.
