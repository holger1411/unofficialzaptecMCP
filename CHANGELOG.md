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

### Changed
- Migrated to MCP Python SDK 2.x (`mcp>=2.2,<3`). The server now speaks MCP
  spec 2026-07-28 (stateless requests, `server/discover`) and still serves
  2025-11-25 handshake clients such as Claude Desktop.
- Arguments are validated against `inputSchema` by the server itself (SDK 2.x
  no longer does); invalid arguments return a tool execution error
  (`isError: true`, `error_type: InputValidationError`).
- Unknown tool names now return a JSON-RPC protocol error (`-32602`) instead of
  a tool execution error, as the spec requires.
- Tool definitions and dispatch moved from `__main__.py` to `tool_defs.py`.

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
