# Contributing

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest && ruff check . && mypy
```

## Live tests

`pytest -m integration` runs read-only calls against the Zaptec cloud with
the credentials from `.env`. No write commands are exercised.

## Capturing fixtures

1. `python scripts/probe.py --dump /tmp/zaptec-raw` writes raw responses.
2. `python scripts/sanitize_fixture.py /tmp/zaptec-raw/chargers.json > tests/fixtures/chargers.json`
   (repeat per file, or adapt the loop in `scripts/probe.py`).
3. Grep the result for your real names, addresses, serials and ids. Fixtures
   must never contain real identifiers; the sanitizer is a helper, not a
   guarantee.

## Pull requests

Keep changes small, add or adjust tests, and update `CHANGELOG.md`.
