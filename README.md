# posthog-mcp

MCP server for [PostHog](https://posthog.com) product analytics (feature
flags, insights, events, persons, cohorts, annotations), built to connect
PostHog to the MSPbots Agent platform.

- Transport: MCP Streamable HTTP (`POST /mcp`), stateless, no session
  affinity, no local persistent state.
- Stack: Python 3.12, [FastMCP](https://gofastmcp.com), `httpx`,
  `pydantic-settings`.
- License: Apache-2.0.

---

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

Every `/mcp` request must carry these headers. Credentials are read only
from headers, never from environment variables, config files, or disk.

| Header | Required | Meaning | Where to get it |
|---|---|---|---|
| `X-PostHog-Api-Key` | Yes | PostHog Personal API Key, sent upstream as `Authorization: Bearer <key>` | PostHog → Settings → Personal API keys |
| `X-PostHog-Project-Id` | Yes | Numeric PostHog Project ID. Substituted into every `/api/projects/{project_id}/...` call; never accepted as a tool argument, so one credential set can only ever address its own project | PostHog → Project Settings → Project ID |
| `X-PostHog-Host` | No (default `https://us.posthog.com`) | API host for EU Cloud (`https://eu.posthog.com`) or a self-hosted instance | — |

Missing `X-PostHog-Api-Key` or `X-PostHog-Project-Id` returns HTTP 401 with a
body naming the missing header(s).

## Tools (9, all read-only)

| Tool | What it does |
|---|---|
| `posthog_list_feature_flags` | List feature flags, with optional key/search/active/archived filters |
| `posthog_get_feature_flag` | Get one feature flag's full definition, including rollout filters |
| `posthog_list_insights` | List saved insights (metadata only, no chart data) |
| `posthog_get_insight` | Get one insight's metadata; `include_result=true` also fetches its chart data (truncated if large) |
| `posthog_list_events` | Search raw events by name, distinct_id, person_id, or time range |
| `posthog_list_persons` | Search persons by email, name, or distinct id fragment |
| `posthog_get_person` | Get one person's profile |
| `posthog_list_cohorts` | List cohorts, optionally filtered by name or static/dynamic type |
| `posthog_list_annotations` | List annotations (timestamped notes on charts) |

No write/delete tools in v1 (see `docs/tickets/PRD-21316.md` for the scope
rationale and later-iteration candidates).

## Running locally

```bash
uv sync
uv run python -m posthog_mcp            # listens on 0.0.0.0:8080
curl http://localhost:8080/health       # {"status": "ok"}
```

Test against a real PostHog account:

```bash
curl -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'X-PostHog-Api-Key: <your personal API key>' \
  -H 'X-PostHog-Project-Id: <your numeric project id>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Tests

```bash
uv run pytest
```

`tests/test_middleware.py` covers missing-header handling and per-request
credential isolation (concurrent requests never cross tenants).
`tests/test_tools.py` covers the `tools/list` snapshot and each tool's happy
path / empty-result / error-mapping behavior against a mocked PostHog API.

## Docker

```bash
docker build --platform linux/amd64 -t posthog-mcp:dev .
docker run --rm -p 8080:8080 posthog-mcp:dev
```
