# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
