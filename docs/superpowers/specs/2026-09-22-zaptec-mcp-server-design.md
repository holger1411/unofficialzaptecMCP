# Unofficial Zaptec MCP Server — Design

Date: 2026-09-22
Status: approved (chat), implementation pending

## 1. Goal

An open-source MCP (Model Context Protocol) server that exposes a Zaptec EV
wallbox (Zaptec Go / Go 2 / Pro) to Claude Desktop and other MCP clients over
stdio. Version 1 covers **read access plus safe control**: status,
installation, charge history with optional cost, pause / resume charging, and
setting the installation's available current with a rate guard.

Out of scope for v1: restart, firmware upgrade, deauthorize-and-stop,
authorization of sessions (undocumented `authorizecharge` endpoint), local
settings, Service Bus streaming, OCPP, multi-user reports.

Modeled on `holger1411/unofficialMCP4Vaillant` (structure, cache, logging,
tests, packaging) and `holger1411/polestar-mcp`.

## 2. Facts established during research (2026-09-22)

- Official OpenAPI spec: `https://api.zaptec.com/swagger/v1/swagger.json`,
  kept locally in the git-ignored `apidocs/ZaptecApi.json` (OpenAPI 3.0.4, base
  URL `https://api.zaptec.com`).
- **Auth**: OAuth2 password grant `POST /oauth/token`
  (`grant_type=password&username&password`, form-encoded). Response has
  `access_token`, `expires_in` (docs say 3600, observed 86400), `token_type`,
  `scope`. **No refresh token.** Token endpoint is limited to 1 request/s per
  IP, so the token must be cached.
- **Rate limits**: 10 requests/s per user, burst 15, excess -> HTTP 429 with
  `Retry-After`. Fair-use policy requires a descriptive `User-Agent:
  AppName/Version` on every request and forbids undocumented endpoints.
- **Response casing**: the live API returns **PascalCase** keys
  (`OperatingMode`, `IsOnline`, `Data`, `StateId`, `ValueAsString`) although the
  spec documents camelCase. The client must read PascalCase.
- **Charger state** (`GET /api/chargers/{id}/state`) is a list of
  `{ChargerId, StateId, StateName (empty), Timestamp, ValueAsString}`. Names
  must be resolved from a built-in table (`ObservationId` enum in the spec /
  `/api/constants` `Observations`).
- **Operating modes** (observation 710 / `OperatingMode`): 0 Unknown,
  1 Disconnected, 2 Connected_Requesting, 3 Connected_Charging,
  5 Connected_Finished.
- **Commands** (`POST /api/chargers/{id}/sendCommand/{commandId}`): 506
  StopChargingFinal (pause) accepted only in mode 3; 507 ResumeCharging
  accepted only in mode 5 with observation 718 `FinalStopActive` = 1. Rejected
  commands return HTTP 500 with `{"Code":528,"Details":"..."}`.
- **Available current** (`POST /api/installation/{id}/update`,
  `availableCurrent` or per-phase): vehicles adapt within 5 s; Zaptec asks not
  to change it more than once per 15 minutes; limited to installation
  `MaxCurrent`; `null` reverts to maximum.
- **History**: `GET /api/sessions/archived` (cursor-paginated, requires
  `From`, `To` and exactly one of `InstallationId` / `ChargerId`) returns
  completed sessions. Its response uses **camelCase** keys (`sessions`,
  `hasMore`, `cursor`, `startDateTime`, `energy`) unlike the other endpoints,
  so field access must be case-tolerant. `GET /api/chargehistory` is
  deprecated (sunset 2027-01-01) and is not used.
- **Power unit**: observation 513 `TotalChargePower` is in **watts** (live
  sample: 17 W while the vehicle idled at ~0.5 A); 553
  `TotalChargePowerSession` is in kWh.
- Installation detail (`GET /api/installation/{id}`) carries
  `TimeZoneIanaName` (e.g. `Europe/Berlin`); the list endpoint returns `null`
  for it.
- Test account: one Zaptec Go 2 (DeviceType 4 "Apollo"), one private
  installation, roles Owner+User, authorization not required, network type 4.
- The `pin` value in the user's `.env` is the charger's physical PIN used for
  app activation and local Bluetooth setup. It is not used by the cloud API and
  is **not** read by this server.
- No Python or registry-listed Zaptec MCP server exists. `pyzaptec` (PyPI)
  and the Home Assistant integration are MIT reference implementations but
  unsuitable as dependencies (Python 3.14 only, pinned pydantic / Azure
  Service Bus).

## 3. Architecture

```
src/zaptec_mcp_server/
  __init__.py
  __main__.py          # MCP stdio entry: tool definitions + dispatch
  server.py            # ZaptecTools: tool implementations, caching, guards
  config.py            # ServerConfig.from_env()
  cache/manager.py     # TTL cache (copied from Vaillant server)
  utils/errors.py      # ZaptecError hierarchy
  utils/logging.py     # stderr logging + SecretRedactor
  zaptec/client.py     # ZaptecClient: httpx, token cache, retry, raw endpoints
  zaptec/observations.py  # observation-id table + typed accessors
  zaptec/formatters.py # pure functions: raw dicts -> tool payloads
  zaptec/timeranges.py # resolve_range (copied from Vaillant server)
tests/
  conftest.py, fixtures/*.json (sanitized live responses)
  test_client.py, test_formatters.py, test_server.py, test_config.py,
  test_timeranges.py, test_cache.py, test_errors.py, test_logging.py,
  test_integration.py (opt-in, marker `integration`)
scripts/probe.py       # manual live probe, writes sanitized fixtures
docs/superpowers/specs/  # this document
```

Dependencies: `mcp>=1.0,<2`, `httpx>=0.27`. Dev: pytest, pytest-asyncio,
pytest-cov, ruff, mypy. Python 3.10 – 3.14.

### 3.1 ZaptecClient (`zaptec/client.py`)

- One long-lived `httpx.AsyncClient` with `base_url`, `timeout=30`,
  headers `User-Agent: unofficial-zaptec-mcp/<version> (+<repo url>)` and
  `Accept: application/json`.
- **Token**: `_ensure_token()` returns a cached bearer token; re-logs in when
  the token is missing or within 60 s of `expires_at`
  (`now + expires_in`). An `asyncio.Lock` guards login so concurrent callers
  trigger one login. On HTTP 401 from any API call the client invalidates the
  token, logs in once, and retries the call once. A failed login raises
  `ZaptecAuthError` (bad credentials -> not retried).
- **Retry**: transient errors (timeouts, connection errors, 502/503/504, and
  429) retry up to 3 times with jittered exponential backoff (0.5 s, 1 s, 2 s),
  honoring `Retry-After` on 429. 500 is retried only for GET. After exhausting
  retries a 429 raises `ZaptecRateLimitError`, others `ZaptecConnectionError`.
  Non-transient 4xx raise `ZaptecApiError` (403 -> `ZaptecPermissionError`,
  404 -> `ZaptecNotFoundError`). Command rejections (500 with JSON `Code`) raise
  `ZaptecCommandRejectedError(code, details)` without retry.
- **Raw endpoints** (return parsed JSON as-is, PascalCase except the archive):
  `list_chargers()`, `get_charger(id)`, `get_charger_state(id)`,
  `list_installations()`, `get_installation(id)`, `get_hierarchy(id)`,
  `send_command(charger_id, command_id)`, `update_installation(id, body)`,
  `archived_sessions(start, end, charger_id=...)` (follows cursor pages up to
  a cap of 10 pages x 200).
- **Resolution**: `resolve_charger(charger_id=None)` returns the charger
  dict: explicit id > `ZAPTEC_DEFAULT_CHARGER_ID` > the only charger; with
  several chargers and no selection, raise `ZaptecError` listing names and
  ids. `resolve_installation(installation_id=None)` analogously, defaulting to
  the resolved charger's `InstallationId`. Charger and installation lists are
  cached in the client for 60 s.

### 3.2 Observations (`zaptec/observations.py`)

- `OBSERVATIONS: dict[int, str]` generated from the OpenAPI `ObservationId`
  enum (kept as a literal table, with a unit test that checks a sample).
- `StateMap` wraps the state list: `get(id) -> str | None`,
  `get_float(id)`, `get_int(id)`, `timestamp(id)`.
- Constants for the IDs the formatters use: 120, 150, 201, 501–503, 507–509,
  510, 511, 513, 519, 520, 553, 554, 702, 708, 710, 711, 714, 718, 721, 762,
  763, 804, 809, 810, 820. Firmware version is parsed from the OCMF string in
  554 (`"GV"`) when present.
- `OPERATING_MODES = {0: "unknown", 1: "disconnected", 2: "connected_requesting",
  3: "connected_charging", 5: "connected_finished"}` with a human hint per mode
  (e.g. 2: "waiting for authorization or vehicle", 5: "paused or finished").

### 3.3 Formatters (`zaptec/formatters.py`)

Pure functions, no I/O, fully unit-tested against fixtures.

- `format_status(charger, state, installation)` ->
  ```
  {
    "charger": {"id", "name", "device_id", "model" (from DeviceType / product name),
                "firmware", "online": bool, "active": bool},
    "operating_mode": {"code": 3, "name": "connected_charging", "hint": "..."},
    "charging": {"power_kw", "session_energy_kwh", "charge_current_set_a",
                 "active_phases", "final_stop_active": bool,
                 "current_a": {"l1","l2","l3"}, "voltage_v": {"l1","l2","l3"},
                 "cable_type", "charger_max_current_a", "charger_min_current_a"},
    "installation": {"id", "name", "available_current_a", "max_current_a",
                     "available_current_mode"},
    "diagnostics": {"temperature_internal_c", "humidity_pct",
                    "signal_strength_dbm", "communication_mode", "warnings"},
    "authorization_required": bool,
    "observed_at": ISO timestamp of the newest observation used
  }
  ```
  `TotalChargePower` (513, watts) is reported as `power_kw` = value / 1000.
- `format_installation(installation, hierarchy, chargers)` -> address,
  timezone, `max_current_a`, `available_current_a` (+ per phase, mode name),
  `use_load_balancing`, `authentication_required`, `network_type` name,
  `features_enabled` names (bit flags decoded from the `Features` table),
  `circuits: [{name, max_current_a, chargers: [{id, name, device_id, model,
  online, operating_mode}]}]`.
- `format_history(sessions, *, price_per_kwh, currency, range meta)`
  -> `{"time_range", "start", "end", "timezone",
  "summary": {"session_count", "energy_kwh", "duration_hours",
  "cost" (only if price set), "price_per_kwh", "currency"},
  "sessions": [{id, start, end, duration_minutes, energy_kwh, cost?,
  charger_name, stopped_by_rfid, offline, aborted}]}`, voided sessions are
  skipped. Timestamps are converted to the installation's IANA timezone. At most 500 sessions are returned; `truncated: true` otherwise.
- `format_command_result(...)` and `format_current_update(...)` produce
  `{"ok": true, "command": "pause", "previous_state": {...}, "note": "..."}`.

### 3.4 Tools (`server.py` / `__main__.py`)

| Tool | Params | Behavior | Cache |
|---|---|---|---|
| `zaptec_get_status` | `charger_id?` | resolve charger, fetch state + installation, `format_status` | 15 s |
| `zaptec_get_installation` | `installation_id?` | installation detail + hierarchy + chargers | 5 min |
| `zaptec_get_charge_history` | `charger_id?`, `time_range` (today/yesterday/week/month/year/custom, default `month`), `start_date?`, `end_date?` | resolve range in installation timezone; query archived sessions for the charger; format with optional cost | 5 min |
| `zaptec_pause_charging` | `charger_id?` | fetch fresh state; require mode 3, else raise `ZaptecCommandRejectedError` with mode name and hint; send 506; invalidate status cache | none |
| `zaptec_resume_charging` | `charger_id?` | fetch fresh state; require mode 5 and 718 = 1, else explain (mode 5 + 718 = 0: vehicle stopped itself; mode 2: waiting for authorization / vehicle; mode 1: not connected); send 507; invalidate status cache | none |
| `zaptec_set_available_current` | `amps` (number or null = reset to max), `installation_id?`, `force?` (bool) | validate `0 <= amps <= MaxCurrent`; enforce min interval since the last update **made by this server process** (in-memory timestamp) unless `force`; POST `{"availableCurrent": amps}`; re-read installation; return previous/new values; invalidate caches | none |

Tool descriptions state clearly which tools change state, and that current
changes should be rare. All tool payloads are JSON text content. Errors are
raised as `RuntimeError(json.dumps({"error_type", "message", ...}))` like
the Vaillant server so the client shows a structured message.

### 3.5 Config (`config.py`)

| Variable | Default | Notes |
|---|---|---|
| `ZAPTEC_USERNAME` | required | Zaptec portal / app login |
| `ZAPTEC_PASSWORD` | required | |
| `ZAPTEC_PRICE_PER_KWH` | unset | float; enables cost fields |
| `ZAPTEC_CURRENCY` | `EUR` | label only |
| `ZAPTEC_DEFAULT_CHARGER_ID` | unset | needed only with several chargers |
| `ZAPTEC_MIN_CURRENT_UPDATE_INTERVAL` | `900` | seconds; `0` disables the guard |
| `ZAPTEC_CACHE_ENABLED` | `true` | |
| `ZAPTEC_LOG_LEVEL` | `INFO` | |
| `ZAPTEC_API_BASE_URL` | `https://api.zaptec.com` | for tests |

Values are read from the process environment; a `.env` file in the working
directory is loaded if present (simple parser, no extra dependency), matching
how the user's existing `.env` is laid out (`username`, `password` lowercase
keys are **not** accepted; the README documents the `ZAPTEC_` names and the
`.env.example`).

### 3.6 Logging and secrets

stderr only (stdout is the MCP transport). `SecretRedactor` filter scrubs the
password, tokens (`Bearer …`, `access_token`), UUIDs, device ids (`GPN…`
serials), and the charger PIN if it ever appears in a logged response.
Response bodies are never logged above DEBUG, and at DEBUG they pass through
the redactor.

### 3.7 Error handling summary

`ZaptecError` (base, carries `payload` dict) → `ZaptecAuthError`,
`ZaptecPermissionError`, `ZaptecNotFoundError`, `ZaptecConnectionError`,
`ZaptecRateLimitError(retry_after)`, `ZaptecApiError(status, body)`,
`ZaptecCommandRejectedError(code, details, state)`,
`ZaptecGuardError` (client-side precondition or rate guard failed; includes
`seconds_until_allowed` for the current guard).

## 4. Testing

- Unit tests with `httpx.MockTransport` for the client: token caching and
  expiry, single-flight login, 401 re-auth once, retry/backoff (with patched
  sleep), 429 `Retry-After`, command rejection parsing, cursor pagination.
- Formatter tests against sanitized fixtures captured from the live account
  (`tests/fixtures/charger_list.json`, `charger_state_go2.json`,
  `installation.json`, `hierarchy.json`, `sessions_archived.json`).
- Server tests: tool dispatch, caching TTLs, guard logic (mode checks, interval
  guard, `force`), error-to-payload mapping, charger resolution with 0/1/n
  chargers.
- Config, time-range, cache, logging tests copied and adapted from the
  Vaillant project.
- Integration tests (`-m integration`, need `.env`): login, status, history;
  no write commands.
- CI: GitHub Actions matrix 3.10–3.14 running `ruff check`, `mypy`, `pytest -m
  "not integration"`.

## 5. Deliverables

`pyproject.toml` (name `unofficial-zaptec-mcp`, package `zaptec_mcp_server`,
console script `unofficial-zaptec-mcp`), `README.md` (features, disclaimer
"not affiliated with Zaptec", install, config table, Claude Desktop snippet,
tool table, architecture, security), `LICENSE` (MIT), `.env.example`,
`claude_desktop_config_snippet.json`, `manifest.json`, `CHANGELOG.md`,
`SECURITY.md`, `CONTRIBUTING.md`, `.github/workflows/ci.yml`,
`.github/dependabot.yml`, `scripts/probe.py`, `scripts/sanitize_fixture.py`.
