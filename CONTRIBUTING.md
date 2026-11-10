# Contributing

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest && ruff check . && mypy
```

Python 3.11 or newer is required. `pytest` skips the live tests by default
(`-m "not integration"` is part of `addopts`).

Do not keep the virtualenv in a folder synced by iCloud Drive or OneDrive.

## Live tests

`pytest -m integration` runs read-only calls against the Zaptec cloud with
the credentials from `.env`. No write commands are exercised. A `-m` on the
command line replaces the default one, so this opts in.

## Capturing fixtures

Raw API responses contain your real ids, names and address. Keep them in a
git-ignored directory and delete it when you are done.

1. `python scripts/probe.py --dump local-tmp/raw` writes raw responses.
   `local-tmp/` is listed in `.gitignore`.
2. `python scripts/sanitize_fixture.py local-tmp/raw/chargers.json > tests/fixtures/chargers.json`
   (repeat per file, or adapt the loop in `scripts/probe.py`).
3. Grep the result for your real names, addresses, serials, ids, hostnames,
   emails, phone numbers and coordinates. Fixtures must never contain real
   identifiers; the sanitizer is a helper, not a guarantee.
4. `rm -rf local-tmp`

## Extension bundle

`manifest.json` must stay valid. After changing it, or the tool list, run
`npx @anthropic-ai/mcpb validate manifest.json`. `tests/test_manifest.py`
checks that the tool names and the version match the package.

## Pull requests

Keep changes small, add or adjust tests, and update `CHANGELOG.md`.
