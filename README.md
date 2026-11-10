# unofficialzaptecMCP

> [!WARNING]
> **Unofficial community project.** This is not a Zaptec product. It is not
> affiliated with, endorsed by, sponsored by or supported by Zaptec AS.
> Please do not contact Zaptec support about this software; open an issue
> here instead. The server talks to the public Zaptec cloud API with your own
> Zaptec account. Zaptec may change that API at any time. Three tools change
> the state of your installation. Use at your own risk.

An MCP (Model Context Protocol) server that connects a Zaptec EV charger
(Zaptec Go, Go 2, Pro) to AI assistants like Claude. Ask for the charging
status, energy and cost of the last month, pause or resume a session, or
lower the available current, all through natural conversation.

## Features

| Tool | Changes state | What it does |
|---|---|---|
| `zaptec_get_status` | no | Operating mode, charging power, session energy, per-phase current and voltage, cable rating, diagnostics, available current |
| `zaptec_get_installation` | no | Address, timezone, max current, available current and mode, load balancing, authentication, features, circuits and chargers |
| `zaptec_get_charge_history` | no | Completed sessions for `today`, `yesterday`, `week`, `month`, `year` or a custom range, with totals and optional cost |
| `zaptec_pause_charging` | **yes** | Pause the running session (Zaptec command 506). Refused with an explanation unless the charger is actually charging |
| `zaptec_resume_charging` | **yes** | Resume a paused session (command 507). Refused with an explanation unless the session is paused |
| `zaptec_set_available_current` | **yes** | Set the installation's available current in amps or reset it to the maximum. Guarded: at most one change per 15 minutes unless forced. `0` stops charging for the whole installation |

Not included on purpose: restarting the charger, firmware upgrades,
deauthorizing sessions, the undocumented `authorizecharge` call, local
settings and OCPP.

## Prerequisites

- A Zaptec account with **owner** rights on the charger (the same login as
  the Zaptec app).
- Python 3.11 or newer (tested on 3.11 – 3.14) for the development install. With `uvx` or the extension bundle, `uv` provides it.
- Claude Desktop or any other MCP-compatible client.

## Installation

Pick one of three routes.

**1. Without installing (uvx).** Needs [uv](https://docs.astral.sh/uv/).
The client starts the server directly from GitHub:

```bash
uvx --from git+https://github.com/holger1411/unofficialzaptecMCP unofficial-zaptec-mcp
```

**2. Claude Desktop extension bundle.** See
[Claude Desktop extension](#claude-desktop-extension-bundle) below.

**3. Clone and virtualenv (development).**

```bash
git clone https://github.com/holger1411/unofficialzaptecMCP.git
cd unofficialzaptecMCP
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Do not keep the virtualenv in a folder synced by iCloud Drive or OneDrive.
Evicted files make the server start very slowly, and clients may time out.

## Configuration

Settings are read from environment variables and from an env file. Create
the file from the template and restrict its permissions:

```bash
cp .env.example .env
chmod 600 .env
# edit .env and set ZAPTEC_USERNAME and ZAPTEC_PASSWORD
```

Variables that are already set in the environment win over the file.

| Variable | Default | Description |
|---|---|---|
| `ZAPTEC_USERNAME` | _required_ | Zaptec account email |
| `ZAPTEC_PASSWORD` | _required_ | Zaptec account password |
| `ZAPTEC_PRICE_PER_KWH` | _unset_ | Electricity price; when set, `zaptec_get_charge_history` adds cost fields |
| `ZAPTEC_CURRENCY` | `EUR` | Currency label for the cost fields |
| `ZAPTEC_DEFAULT_CHARGER_ID` | _unset_ | Only needed when the account can see more than one charger |
| `ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL` | `900` | Seconds between two available-current changes; `0` disables the guard |
| `ZAPTEC_CACHE_ENABLED` | `true` | Disable for debugging |
| `ZAPTEC_LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `ZAPTEC_API_BASE_URL` | `https://api.zaptec.com` | API base URL. Must be `https://`; plain `http://` is accepted only for `localhost`, `127.0.0.1` and `::1` (for test servers) |
| `ZAPTEC_ENV_FILE` | _unset_ | Explicit path to the env file. If unset, `./.env` in the working directory is used. A warning is logged if the file is readable by group or others |

A missing credential, a malformed number, an invalid base URL or an invalid
`ZAPTEC_LOG_LEVEL` makes the server print one line to stderr and exit with
code 2. The password is used exactly as written; surrounding whitespace is
not stripped. In an env file, put a password that starts or ends with a
space in quotes.

The charger PIN printed on the device is **not** needed. It is only used by
the Zaptec app for activation and local Bluetooth setup.

### Claude Desktop

Add to your `claude_desktop_config.json` (see
`claude_desktop_config_snippet.json` for a template). This example starts the
server with `uvx` and keeps the credentials in a private env file:

```json
{
  "mcpServers": {
    "unofficial-zaptec-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/holger1411/unofficialzaptecMCP",
        "unofficial-zaptec-mcp"
      ],
      "env": {
        "ZAPTEC_ENV_FILE": "/absolute/path/to/zaptec.env"
      }
    }
  }
}
```

Claude Desktop does not always find `uvx` on its `PATH`. If the server does
not start, use the absolute path from `which uvx` as `command`. For the
clone route, use `"command": ".../unofficialzaptecMCP/.venv/bin/python"` with
`"args": ["-m", "zaptec_mcp_server"]`.

**Credentials in the config file are stored in plain text.** You can put
`ZAPTEC_USERNAME` and `ZAPTEC_PASSWORD` into the `env` block, but then anyone
who can read `claude_desktop_config.json` can read your password. Prefer a
separate env file with `chmod 600` and point `ZAPTEC_ENV_FILE` at it, as
above. The extension bundle below stores the password in the operating
system keychain instead.

Restart Claude Desktop afterwards. Example prompts: "Is my car charging?",
"How much did charging cost in September?", "Pause charging", "Limit the
wallbox to 10 amps until I say otherwise".

### Claude Desktop extension bundle

`manifest.json` describes the server as an
[MCPB](https://github.com/anthropics/mcpb) extension (`server.type` is
`uv`). Claude Desktop asks for the Zaptec email and password when you install
it, and keeps the password in the operating system keychain. The bundle
needs [uv](https://docs.astral.sh/uv/) on the machine; uv installs the
dependencies on first start.

```bash
npx @anthropic-ai/mcpb validate manifest.json
npx @anthropic-ai/mcpb pack . unofficial-zaptec-mcp.mcpb
```

Open the resulting `.mcpb` file with Claude Desktop to install it. `.mcpbignore`
keeps `.env`, tests and local state out of the bundle. The bundle asks only
for the two credentials. Optional settings such as `ZAPTEC_PRICE_PER_KWH`
need one of the other routes. The packing and the `uv` launch were tested; an
install through the Claude Desktop UI was not.

## Behaviour and limits

- **Authentication:** OAuth2 password grant against `api.zaptec.com`. The
  token is cached until shortly before it expires. After a 401 the server
  logs in again once, even when several requests fail at the same time.
  Zaptec allows one token request per second per IP, so the server
  never logs in per request.
- **Rate limits:** Zaptec allows 10 requests per second per user. Every
  request carries a descriptive `User-Agent` as required by Zaptec's
  fair-use policy. Transient errors (timeouts, 5xx, 429) are retried three
  times with backoff, honouring `Retry-After`.
- **Caching:** status 15 s, installation 5 min, history 5 min. Concurrent
  identical requests share one API call. Expired entries are pruned and the
  cache has a fixed maximum size. Control tools are never cached and
  invalidate the status cache. Failures are never cached.
  `zaptec_get_status` fetches the charger state and the installation
  concurrently.
- **Ids:** charger and installation ids must be canonical UUIDs. Anything
  else is rejected before a URL is built, so an id cannot redirect a request
  to another endpoint.
- **Guards:** pause and resume check the live charger state first and refuse
  with a plain-language reason when the command would be rejected.
  `zaptec_set_available_current` validates against the installation maximum,
  rejects non-finite values, and refuses the call when the installation
  reports no numeric maximum. It enforces the 15-minute spacing Zaptec
  recommends (per server process, safe against concurrent calls). `0` stops
  charging for the whole installation; use it deliberately.
- **History** uses `/api/sessions/archived`, converted to the installation's
  timezone. Cost is `energy_kwh × ZAPTEC_PRICE_PER_KWH`, nothing more. At
  most 2000 sessions are fetched and at most 500 are listed; `truncated` is
  `true` when either limit cuts the result, and `truncated_by` names which
  (`api_page_limit` means the totals are incomplete, `display_limit` only
  the list). A custom range needs
  `end_date >= start_date` and may span at most 366 days.
- **Logging** goes to stderr through a redactor that scrubs credentials,
  bearer tokens, UUIDs and device serials. Exception tracebacks pass through
  the same redactor.
- **Data from the API** (charger and installation names, addresses) reaches
  the model as text. Treat it as untrusted; see [`SECURITY.md`](SECURITY.md).

## Security

See [`SECURITY.md`](SECURITY.md). Never commit `.env`. Report security
issues via GitHub Private Vulnerability Reporting, not as public issues.

## Development

```bash
pip install -e '.[dev]'
pytest                    # unit tests, offline; live tests are skipped by default
ruff check .
mypy
pytest -m integration     # live read-only tests, needs credentials
python scripts/probe.py   # prints the live status; --dump DIR writes raw responses
```

Fixtures under `tests/fixtures/` are sanitized live responses. Capture new
ones with `scripts/probe.py --dump local-tmp/raw` and run them through
`scripts/sanitize_fixture.py` before committing; see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Credits

- **Zaptec** for the public API and its documentation at
  [docs.zaptec.com](https://docs.zaptec.com). The OpenAPI spec is available
  at [api.zaptec.com/swagger/v1/swagger.json](https://api.zaptec.com/swagger/v1/swagger.json);
  it is not redistributed in this repository.
- [custom-components/zaptec](https://github.com/custom-components/zaptec) and
  [pyzaptec](https://pypi.org/project/pyzaptec/) (MIT), whose observation and
  command handling served as reference.
- [Model Context Protocol](https://modelcontextprotocol.io).
- [holger1411/unofficialMCP4Vaillant](https://github.com/holger1411/unofficialMCP4Vaillant)
  and [holger1411/polestar-mcp](https://github.com/holger1411/polestar-mcp),
  the pattern references for the client, cache and test layout.

## License

[MIT](LICENSE). The license covers this project's code only. This project is
not affiliated with, endorsed by or sponsored by Zaptec AS. "Zaptec" and
related names and logos are trademarks of Zaptec AS; they are used here only
to describe what the server connects to. The software is provided "as is", without
warranty of any kind. You use it at your own risk, including any effect on
your charger, installation or electricity bill.
