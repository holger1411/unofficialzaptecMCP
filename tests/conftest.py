import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def chargers() -> list[dict[str, Any]]:
    return list(load_fixture("chargers")["Data"])


@pytest.fixture
def charger(chargers: list[dict[str, Any]]) -> dict[str, Any]:
    return chargers[0]


@pytest.fixture
def charger_state() -> list[dict[str, Any]]:
    return list(load_fixture("charger_state"))


@pytest.fixture
def installation() -> dict[str, Any]:
    return dict(load_fixture("installation"))


@pytest.fixture
def hierarchy() -> dict[str, Any]:
    return dict(load_fixture("hierarchy"))


@pytest.fixture
def sessions_archived() -> list[dict[str, Any]]:
    return list(load_fixture("sessions_archived")["sessions"])
