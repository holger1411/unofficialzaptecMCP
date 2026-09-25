# unofficialzaptecMCP

> [!WARNING]
> **Unofficial community project.** This is not a Zaptec product. It is not
> affiliated with, endorsed by, sponsored by or supported by Zaptec AS.
> Please do not contact Zaptec support about this software; open an issue
> here instead.

An **unofficial** MCP (Model Context Protocol) server that connects a Zaptec
EV charger (Zaptec Go, Go 2, Pro) to AI assistants like Claude. Ask for the
charging status, energy and cost of the last month, pause or resume a
session, or lower the available current, all through natural conversation.

**This project is not affiliated with, endorsed by, or sponsored by Zaptec
AS.** "Zaptec" is a trademark of Zaptec AS; it is used here only to describe
what the server connects to.

> **Disclaimer:** The server talks to the public Zaptec cloud API
> (`api.zaptec.com`) with your own Zaptec account. Only documented endpoints
> are used, but Zaptec may change the API at any time. Three tools change the
> state of your installation. Use at your own risk.

## Features

| Tool | Changes state | What it does |
|---|---|---|
| `zaptec_get_status` | no | Operating mode, charging power, session energy, per-phase current and voltage, cable rating, diagnostics, available current |
| `zaptec_get_installation` | no | Address, timezone, max current, available current and mode, load balancing, authentication, features, circuits and chargers |
| `zaptec_get_charge_history` | no | Completed sessions for `today`, `yesterday`, `week`, `month`, `year` or a custom range, with totals and optional cost |
| `zaptec_pause_charging` | **yes** | Pause the running session (Zaptec command 506). Refused with an explanation unless the charger is actually charging |
| `zaptec_resume_charging` | **yes** | Resume a paused session (command 507). Refused with an explanation unless the session is paused |
| `zaptec_set_available_current` | **yes** | Set the installation's available current in amps or reset it to the maximum. Guarded: at most one change per 15 minutes unless forced |

Not included on purpose: restarting the charger, firmware upgrades,
deauthorizing sessions, the undocumented `authorizecharge` call, local
settings and OCPP.

## Prerequisites

- A Zaptec account with **owner** rights on the charger (the same login as
  the Zaptec app).
- Python 3.10 – 3.14.
- Claude Desktop or any other MCP-compatible client.

## Installation

```bash
git clone https://github.com/holger1411/unofficialzaptecMCP.git
cd unofficialzaptecMCP
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

```bash
cp .env.example .env
# edit .env and set ZAPTEC_USERNAME and ZAPTEC_PASSWORD
```

| Variable | Default | Description |
|---|---|---|
| `ZAPTEC_USERNAME` | _required_ | Zaptec account email |
| `ZAPTEC_PASSWORD` | _required_ | Zaptec account password |
| `ZAPTEC_PRICE_PER_KWH` | _unset_ | Electricity price; when set, `zaptec_get_charge_history` adds cost fields |
| `ZAPTEC_CURRENCY` | `EUR` | Currency label for the cost fields |
| `ZAPTEC_DEFAULT_CHARGER_ID` | _unset_ | Only needed when the account can see more than one charger |
| `ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL` | `900` | Seconds between two available-current changes; `0` disables the guard |
| `ZAPTEC_CACHE_ENABLED` | `true` | Disable for debugging |
| `ZAPTEC_LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |

The charger PIN printed on the device is **not** needed. It is only used by
the Zaptec app for activation and local Bluetooth setup.

### Claude Desktop

Add to your `claude_desktop_config.json` (see
`claude_desktop_config_snippet.json` for a template):

```json
{
  "mcpServers": {
    "unofficial-zaptec-mcp": {
      "command": "/absolute/path/to/unofficialzaptecMCP/.venv/bin/python",
      "args": ["-m", "zaptec_mcp_server"],
      "env": {
        "ZAPTEC_USERNAME": "your-email@example.com",
        "ZAPTEC_PASSWORD": "your-password",
        "ZAPTEC_PRICE_PER_KWH": "0.30"
      }
    }
  }
}
```

Restart Claude Desktop afterwards. Example prompts: "Is my car charging?",
"How much did charging cost in September?", "Pause charging", "Limit the
wallbox to 10 amps until I say otherwise".

## Behaviour and limits

- **Authentication:** OAuth2 password grant against `api.zaptec.com`. The
  token is cached until shortly before it expires and refreshed once on a
  401. Zaptec allows one token request per second per IP, so the server
  never logs in per request.
- **Rate limits:** Zaptec allows 10 requests per second per user. Every
  request carries a descriptive `User-Agent` as required by Zaptec's
  fair-use policy. Transient errors (timeouts, 5xx, 429) are retried three
  times with backoff, honouring `Retry-After`.
- **Caching:** status 15 s, installation 5 min, history 5 min. Control tools
  are never cached and invalidate the status cache. Failures are never
  cached.
- **Guards:** pause and resume check the live charger state first and refuse
  with a plain-language reason when the command would be rejected.
  `zaptec_set_available_current` validates against the installation maximum
  and enforces the 15-minute spacing Zaptec recommends (per server process).
- **History** uses `/api/sessions/archived`, converted to the installation's
  timezone. Cost is `energy_kwh × ZAPTEC_PRICE_PER_KWH`, nothing more.
- **Logging** goes to stderr through a redactor that scrubs credentials,
  bearer tokens, UUIDs and device serials.

## Security

See [`SECURITY.md`](SECURITY.md). Never commit `.env`. Report security
issues via GitHub Private Vulnerability Reporting, not as public issues.

## Development

```bash
pip install -e '.[dev]'
pytest                    # unit tests, offline
ruff check .
mypy
pytest -m integration     # live read-only tests, needs .env
python scripts/probe.py   # prints the live status; --dump DIR writes raw responses
```

Fixtures under `tests/fixtures/` are sanitized live responses. Capture new
ones with `scripts/probe.py --dump` and run them through
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

[MIT](LICENSE). The license covers this project's code only. "Zaptec" and
related names and logos are trademarks of Zaptec AS; they are used here only
to describe compatibility. The software is provided "as is", without
warranty of any kind. You use it at your own risk, including any effect on
your charger, installation or electricity bill.
