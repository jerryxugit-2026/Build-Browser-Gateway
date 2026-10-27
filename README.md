# Build-Browser-Gateway

One MCP door to four browser engines.

`browser-gateway` is a Python MCP server that gives an AI agent a single unified
door to the web, and routes every request to the engine that does that job best:

| Intent | Engine | What it does |
|---|---|---|
| `dom_interaction` | **PinchTab** | navigate / click / fill / type; snap the accessibility tree, read text or html, eval JS |
| `data_extraction` | **bb-browser** | structured data through community site adapters (145 installed on my machine: google, bing, baidu, duckduckgo, arxiv search, and more) |
| `session_auth` | **Agent Reach** | read-only diagnostics only (`doctor` / `version` / `check-update`) — blocked by default |
| `custom_script` | **Playwright** | run a custom Python Playwright script — blocked by default |

There is also a flat tool per engine (`browser_pinchtab`, `browser_bb`,
`browser_reach`, `browser_playwright`) for callers that already know which hand
they need.

## Design rules the agent cannot talk its way around

- **Hard timeouts everywhere.** Every engine subprocess gets a hard timeout; a
  stuck page can no longer pin the whole MCP session forever.
- **Explicit truncation.** Output is capped by `max_chars` (default 10000) and
  list results by `limit` (default 5) — and the caller is always told what was
  cut. Silent truncation is worse than no truncation.
- **Fail-closed gates.** The two risky engines (custom scripts, anything that
  looks like authentication) are blocked unless two environment variables are
  deliberately set: `BROWSER_GATEWAY_ALLOW_CUSTOM_SCRIPT=1`,
  `BROWSER_GATEWAY_ALLOW_SESSION_AUTH=1`.
- **Silent-zero detection.** An adapter that returns "success" with zero results
  is flagged in the output, because an AI agent will otherwise read it as "the
  answer is that there is nothing there".

## Install

```bash
pip install .
# then point your MCP client at:
python -m browser_gateway_mcp.server
```

Engines are external binaries found on `PATH` (or via environment variables
below): `pinchtab`, `bb-browser`, `agent-reach`, and a Python interpreter with
`playwright` installed.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `BROWSER_GATEWAY_ALLOW_CUSTOM_SCRIPT` | unset (blocked) | allow the Playwright custom-script engine |
| `BROWSER_GATEWAY_ALLOW_SESSION_AUTH` | unset (blocked) | allow the Agent Reach engine |
| `BROWSER_GATEWAY_OUTPUT_DIR` | `~/.browser-gateway-mcp/output` | where screenshot/pdf outputs land |
| `BROWSER_GATEWAY_LOG_FILE` | unset (stderr only) | optional debug log file |
| `BROWSER_GATEWAY_PYTHON` | `python3` | interpreter used to run Playwright scripts |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright default | where Playwright browsers are installed |
| `PINCHTAB_BIN` / `BB_BROWSER_BIN` / `AGENT_REACH_BIN` | command names | engine binary paths |
| `BB_SITES_DIR` | `~/.bb-browser/bb-sites` | bb-browser adapter directory |

## Notes

- Every account, key and password in the published sources is a mock. Real
  credentials never leave the machine.
- The engines themselves are separate open-source tools; what this repository
  contains is the door, the routing and the safety rules.

## Licence

MIT
