# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Tool `title`s and annotations (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`) so clients can tell read tools from
  state-changing ones.
- `outputSchema` for every tool; results carry `structuredContent` alongside
  the JSON text block.
- Stricter input schemas: `format: date` for history dates, `start_date` and
  `end_date` required when `time_range` is `custom`, `amps` minimum 0.
- `tools/list` cache hint (`ttlMs` 1 h, `cacheScope` public) and the package
  version in `serverInfo`.
- `py.typed` marker; the package ships its type information.
- `tests/test_manifest.py` keeps `manifest.json` in sync with the package.

### Changed
- Configuration errors (missing credentials, bad number, bad URL, invalid
  `ZAPTEC_LOG_LEVEL`) print one line to stderr and exit with code 2.
- `zaptec_get_status` fetches the charger state and the installation
  concurrently.
- `zaptec_get_charge_history`: custom ranges need `end_date >= start_date`
  and may span at most 366 days.
- `zaptec_set_available_current`: `0` is documented as stopping charging for
  the whole installation.
- Python 3.11 or newer is required (3.10 reached end of life); no upper
  version cap. Tested on 3.11 – 3.14.
- `pyproject.toml`: SPDX `license = "MIT"` with `license-files`, setuptools
  77 or newer, author name "Holger Könemann" (also in `LICENSE`).
- `pytest` skips integration tests by default (`-m "not integration"` in
  `addopts`); `pytest -m integration` still opts in.
- CI: Python 3.10 dropped from the matrix, read-only `permissions`,
  concurrency group that cancels superseded runs, coverage via `pytest-cov`,
  a `pip-audit` job, and actions pinned to commit SHAs.
- `manifest.json` is now a valid MCPB manifest (`manifest_version` 0.4,
  `server.type` `uv`) with `user_config` entries; the password is marked
  `sensitive`. `.mcpbignore` keeps credentials and tests out of the bundle.
- README: `uvx` install route, `ZAPTEC_API_BASE_URL` and `ZAPTEC_ENV_FILE`,
  credential storage note, extension bundle instructions. The config snippet
  now uses `uvx` and `ZAPTEC_ENV_FILE`.
- The design spec now says "implemented" and points to this changelog; the
  implementation plan transcript was removed from `docs/`.
- Migrated to MCP Python SDK 2.x (`mcp>=2.2,<3`). The server now speaks MCP
  spec 2026-07-28 (stateless requests, `server/discover`) and still serves
  2025-11-25 handshake clients such as Claude Desktop.
- Arguments are validated against `inputSchema` by the server itself (SDK 2.x
  no longer does); invalid arguments return a tool execution error
  (`isError: true`, `error_type: InputValidationError`).
- Unknown tool names now return a JSON-RPC protocol error (`-32602`) instead of
  a tool execution error, as the spec requires.
- Tool definitions and dispatch moved from `__main__.py` to `tool_defs.py`.

### Fixed
- Re-login after a 401 happens once, even with concurrent requests.
- `zaptec_set_available_current`: the 15-minute guard is race-free; the call
  is refused when the installation reports no numeric maximum; non-finite
  values are rejected.
- Response cache: single-flight per key, expired entries are pruned, size is
  bounded.
- `zaptec_get_charge_history`: `truncated` is also set when the pagination
  cap (2000 sessions) is hit; the new `truncated_by` field names the limit.
- The password is no longer whitespace-stripped.

### Security
- Charger and installation ids must be canonical UUIDs; anything else is
  rejected before a URL is built. Closes a path-injection hole where an id
  such as `../chargers/x/state` reached other endpoints.
- `ZAPTEC_API_BASE_URL` must be `https://`; plain `http://` is accepted only
  for `localhost`, `127.0.0.1` and `::1`.
- Exception tracebacks now pass through the log redactor.
- A warning is logged if the env file is readable by group or others.
- `SECURITY.md` documents credential storage, untrusted API data, id
  validation and the https rule.
- Sanitized fixtures and `scripts/sanitize_fixture.py` now also neutralise the
  installation support group, the IoT hub hostname and the diagnostics string.
- `CONTRIBUTING.md` no longer tells contributors to dump raw responses to
  `/tmp`; they go to the git-ignored `local-tmp/` and are deleted afterwards.

## [0.1.0] - 2026-09-22

### Added
- Six MCP tools: `zaptec_get_status`, `zaptec_get_installation`,
  `zaptec_get_charge_history` (optional cost via `ZAPTEC_PRICE_PER_KWH`),
  `zaptec_pause_charging`, `zaptec_resume_charging`,
  `zaptec_set_available_current`.
- `ZaptecClient` with cached password-grant token, single-flight re-login on
  401, retry with backoff for timeouts / 5xx / 429, and a descriptive
  `User-Agent` as required by Zaptec's fair-use policy.
- Client-side guards: pause/resume check the live operating mode first;
  available-current changes are validated against the installation maximum
  and spaced by at least 15 minutes unless forced.
- Per-tool TTL cache, stderr logging with secret redaction, sanitized live
  fixtures and an opt-in live integration test suite.
