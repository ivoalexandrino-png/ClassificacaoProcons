# cursor-chatgpt-bridge

Authenticated remote MCP server that lets ChatGPT supervise Cursor Agents. ChatGPT calls tools; the bridge persists session metadata and delegates execution to the official Cursor TypeScript SDK.

## Installation

```bash
cd cursor-chatgpt-bridge
npm install
cp .env.example .env
```

Set a high-entropy `CURSOR_BRIDGE_TOKEN` and a Cursor API key in `.env`. The Cursor SDK resolves credentials in this order: explicit key, `CURSOR_API_KEY`, then an SDK browser-login credential. A headless server should use `CURSOR_API_KEY`.

## Run

```bash
npm run dev
npm run build
npm start
npm test
npm run lint
```

The server exposes:

- `GET /health` (unauthenticated): service/database health without secrets.
- `/mcp` (Bearer-token protected): Streamable HTTP MCP endpoint.

Example:

```bash
curl http://localhost:3000/health
curl -X POST http://localhost:3000/mcp \
  -H "Authorization: Bearer $CURSOR_BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'
```

## Docker

```bash
docker build -t cursor-chatgpt-bridge .
docker run --rm -p 3000:3000 --env-file .env -v "$(pwd)/data:/app/data" cursor-chatgpt-bridge
```

For local Cursor agents, mount every registered working directory into the container at the same absolute path (or run the bridge directly on the host). Cloud agents do not require a local checkout.

## Architecture

`src/mcp/tools.ts` maps public MCP tools to `BridgeService`. `src/cursor/client.ts` isolates `@cursor/sdk`; `src/storage/store.ts` stores projects, agents, runs, and messages in SQLite; `src/security` provides constant-time bearer authentication and a conservative prompt policy. The bridge prevents concurrent runs per agent.

The implementation uses `@cursor/sdk` `1.0.27`: `Agent.create`, `Agent.resume`, `agent.send`, `run.wait`, `Agent.get`, `Agent.getRun`, `Agent.cancelRun`, and `Agent.messages.list`. Local agents use `local.cwd`; cloud creation uses `cloud.repos`. Cursor recognizes cloud IDs by `bc-` prefix and persists cloud context server-side; local context persists in the Cursor SDK's workspace-scoped store. `run.cancel()`/`Agent.cancelRun()` is officially supported for local and cloud runs.

`cursor_get_conversation` always returns prompts and responses that passed through this bridge. The SDK additionally exposes stored messages for local agents, but this MVP does not merge that source because cloud message listing is not exposed by the SDK.

## MCP tools

- `cursor_list_agents`
- `cursor_get_agent`
- `cursor_get_conversation`
- `cursor_send_followup`
- `cursor_start_agent`
- `cursor_get_run`
- `cursor_cancel_run`
- `cursor_get_changes`
- `cursor_project_register`
- `cursor_list_projects`

Register a project first, then start or continue an agent. `cursor_start_agent` intentionally refuses a repository or working-directory mismatch with the registered project.

## Security

Every `/mcp` request needs `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>`. Tokens and API keys are not logged. The bridge blocks prompts containing high-risk production/destructive patterns by default, including `terraform destroy`, `kubectl delete`, destructive database commands, `git reset --hard`, force pushes, critical `rm -rf`, and credential/secrets operations. Set `allow_dangerous_actions: true` per follow-up only after an explicit human authorization.

Place this behind HTTPS and restrict inbound access. Do not expose it as an unauthenticated public endpoint.

## Connecting ChatGPT to cursor-chatgpt-bridge

ChatGPT connects to remote MCP servers; it does not connect to a server running only on `localhost`. Deploy this service behind an HTTPS reverse proxy and configure its public URL as:

```text
https://bridge.example.com/mcp
```

1. Deploy the container or Node process with `CURSOR_BRIDGE_TOKEN`, `CURSOR_API_KEY`, and persistent storage configured.
2. Terminate TLS at a reverse proxy/load balancer and restrict network access where possible.
3. In ChatGPT web, use the current workspace Developer mode / custom MCP app flow to add the remote MCP endpoint. For private hosts use ChatGPT Secure MCP Tunnel instead of publishing the port.
4. Configure the connector to send `Authorization: Bearer <CURSOR_BRIDGE_TOKEN>` (or place a compatible OAuth gateway in front of the bridge if workspace policy requires OAuth).
5. Test with `cursor_list_projects`. Register a project with `cursor_project_register`, then call `cursor_start_agent`.

Availability of custom MCP apps and write actions depends on the ChatGPT plan, workspace settings, role, and region. For Business and Enterprise/Edu, an admin enables Developer mode under Workspace Settings → Permissions & Roles → Connected Data Developer mode / Create custom MCP connectors. Verify the current controls in OpenAI's “Developer mode and MCP apps in ChatGPT” documentation before rollout.

## Example usage

For project `sunday`, ask ChatGPT: “Veja como está o agente do projeto Sunday e continue.”

ChatGPT should call:

```text
cursor_list_projects → cursor_list_agents → cursor_get_conversation →
cursor_get_changes → cursor_send_followup
```

For “Revise o que o Cursor fez antes de deixar ele continuar,” it should call `cursor_get_conversation` and `cursor_get_changes`; if review finds an issue, it sends a focused `cursor_send_followup`.

## Operational limitations

- The bridge requires a valid Cursor API key (or SDK login) and each local agent's working directory must be accessible to the bridge process.
- This service persists bridge traffic, not arbitrary messages sent to an agent outside the bridge.
- `cursor_get_changes` only reads local Git working trees. Cloud agents return an explicit unavailable reason because their VM is remote.
- A running SDK run remains locked after a caller-side timeout; its `run_id` stays queryable/cancellable.
