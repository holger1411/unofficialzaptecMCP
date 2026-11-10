from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from zaptec_mcp_server.zaptec.formatters import (
    format_history,
    format_installation,
    format_status,
)

TZ = ZoneInfo("Europe/Berlin")


def test_format_status_shape(
    charger: dict[str, Any], charger_state: list[dict[str, Any]], installation: dict[str, Any]
) -> None:
    out = format_status(charger, charger_state, installation)
    assert out["charger"]["name"] == "Garage"
    assert out["charger"]["id"] == charger["Id"]
    assert out["charger"]["model"] == "Zaptec Go 2"
    assert out["charger"]["firmware"] == "3.1.0.8"
    assert out["charger"]["online"] is True
    assert out["operating_mode"] == {"code": 3, "name": "connected_charging", "hint": "charging"}
    ch = out["charging"]
    assert ch["power_kw"] == 0.017
    assert ch["session_energy_kwh"] == 11.284
    assert ch["charge_current_set_a"] == 19.992
    assert ch["active_phases"] == ["L1", "L2", "L3"]  # SetPhases id 4 = all phases (TN)
    assert ch["final_stop_active"] is False
    assert ch["current_a"] == {"l1": 0.477, "l2": 0.485, "l3": 0.483}
    assert ch["voltage_v"]["l1"] == 239.881
    assert ch["cable_rating_a"] == 20
    assert ch["charger_max_current_a"] == 32.0
    assert ch["charger_min_current_a"] == 6.0
    inst = out["installation"]
    assert inst["name"] == "Example Installation"
    assert inst["max_current_a"] == 32.0
    assert inst["available_current_a"] is None
    assert inst["available_current_mode"] == "manual"
    diag = out["diagnostics"]
    assert diag["temperature_internal_c"] == 41.457
    assert diag["signal_strength_dbm"] == -74.0
    assert diag["communication_mode"] == "Wifi"
    assert out["authorization_required"] is False
    assert out["observed_at"] == "2026-09-22T14:32:42+00:00"


def test_format_status_handles_sparse_state() -> None:
    out = format_status({"Id": "x", "Name": "n", "DeviceType": 1, "IsOnline": False}, [], {})
    assert out["operating_mode"]["code"] is None
    assert out["operating_mode"]["name"] == "unknown"
    assert out["charging"]["power_kw"] is None
    assert out["charger"]["model"] == "Zaptec Pro"
    assert out["charger"]["online"] is False


def test_format_status_falls_back_to_list_mode() -> None:
    out = format_status({"Id": "x", "OperatingMode": 5}, [], {})
    assert out["operating_mode"]["name"] == "connected_finished"


def test_format_installation(
    installation: dict[str, Any], hierarchy: dict[str, Any], chargers: list[dict[str, Any]]
) -> None:
    out = format_installation(installation, hierarchy, chargers)
    assert out["id"] == installation["Id"]
    assert out["name"] == "Example Installation"
    assert out["address"] == {
        "street": "Example Street 1",
        "zip_code": "12345",
        "city": "Exampletown",
    }
    assert out["timezone"] == "Europe/Berlin"
    assert out["max_current_a"] == 32.0
    assert out["available_current_a"] is None
    assert out["available_current_mode"] == "manual"
    assert out["network_type"] == "TN_3_phase"
    assert out["use_load_balancing"] is True
    assert out["authentication_required"] is False
    assert "PowerManagement_Apm_SurplusMode" in out["features_available"]
    assert out["features_enabled"] == []
    assert out["circuits"][0]["name"] == "Charge circuit"
    assert out["circuits"][0]["max_current_a"] == 32.0
    c = out["circuits"][0]["chargers"][0]
    assert c["name"] == "Garage"
    assert c["online"] is True
    assert c["operating_mode"] == "connected_charging"
    assert c["model"] == "Zaptec Go / Go 2"


def _range() -> tuple[datetime, datetime]:
    return datetime(2026, 9, 1, tzinfo=TZ), datetime(2026, 9, 22, 16, 0, tzinfo=TZ)


def test_format_history_without_price(sessions_archived: list[dict[str, Any]]) -> None:
    start, end = _range()
    out = format_history(
        sessions_archived,
        tz=TZ,
        time_range="month",
        start=start,
        end=end,
        price_per_kwh=None,
        currency="EUR",
    )
    assert out["time_range"] == "month"
    assert out["start"] == "2026-09-01T00:00:00+02:00"
    assert out["timezone"] == "Europe/Berlin"
    s = out["summary"]
    assert s["session_count"] == 3
    assert s["energy_kwh"] == 27.575
    assert s["duration_hours"] == 6.75
    assert "cost" not in s
    first = out["sessions"][0]
    assert first["start"] == "2026-09-20T13:11:06+02:00"
    assert first["end"] == "2026-09-20T14:06:24+02:00"
    assert first["duration_minutes"] == 55
    assert first["energy_kwh"] == 9.205
    assert first["charger_name"] == "Garage"
    assert first["stopped_by_rfid"] is False
    assert first["offline"] is False
    assert first["aborted"] is False
    assert "cost" not in first
    assert out["truncated"] is False


def test_format_history_with_price_and_truncation(
    sessions_archived: list[dict[str, Any]],
) -> None:
    start, end = _range()
    out = format_history(
        sessions_archived,
        tz=TZ,
        time_range="month",
        start=start,
        end=end,
        price_per_kwh=0.30,
        currency="EUR",
        max_sessions=2,
    )
    assert out["summary"]["cost"] == 8.27
    assert out["summary"]["price_per_kwh"] == 0.30
    assert out["summary"]["currency"] == "EUR"
    assert out["sessions"][0]["cost"] == 2.76
    assert len(out["sessions"]) == 2
    assert out["truncated"] is True
    assert out["summary"]["session_count"] == 3  # summary covers all sessions


def test_format_history_skips_voided_and_sorts() -> None:
    sessions: list[dict[str, Any]] = [
        {
            "id": "b",
            "startDateTime": "2026-09-05T10:00:00Z",
            "endDateTime": "2026-09-05T11:00:00Z",
            "energy": 2.0,
        },
        {
            "id": "a",
            "startDateTime": "2026-09-04T10:00:00Z",
            "endDateTime": "2026-09-04T10:30:00Z",
            "energy": 1.0,
        },
        {
            "id": "v",
            "startDateTime": "2026-09-06T10:00:00Z",
            "endDateTime": "2026-09-06T11:00:00Z",
            "energy": 9.0,
            "voided": True,
        },
        {"id": "broken", "startDateTime": None, "energy": 5.0},
    ]
    start, end = _range()
    out = format_history(
        sessions,
        tz=TZ,
        time_range="custom",
        start=start,
        end=end,
        price_per_kwh=None,
        currency="EUR",
    )
    assert [s["id"] for s in out["sessions"]] == ["a", "b"]
    assert out["summary"]["energy_kwh"] == 3.0
    assert out["summary"]["duration_hours"] == 1.5


def _history(sessions: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    start, end = _range()
    return format_history(
        sessions,
        tz=TZ,
        time_range="month",
        start=start,
        end=end,
        price_per_kwh=None,
        currency="EUR",
        **kw,
    )


def test_format_history_not_truncated_has_empty_reasons(
    sessions_archived: list[dict[str, Any]],
) -> None:
    out = _history(sessions_archived)
    assert out["truncated"] is False
    assert out["truncated_by"] == []
    assert "truncation_note" not in out


def test_format_history_display_cap_is_reported(
    sessions_archived: list[dict[str, Any]],
) -> None:
    out = _history(sessions_archived, max_sessions=2)
    assert out["truncated"] is True
    assert out["truncated_by"] == ["display_limit"]
    assert "2 of 3" in out["truncation_note"]


def test_format_history_api_cap_is_reported(sessions_archived: list[dict[str, Any]]) -> None:
    out = _history(sessions_archived, api_truncated=True)
    assert out["truncated"] is True
    assert out["truncated_by"] == ["api_page_limit"]
    assert len(out["sessions"]) == 3
    assert "narrow" in out["truncation_note"]


def test_format_history_both_caps(sessions_archived: list[dict[str, Any]]) -> None:
    out = _history(sessions_archived, max_sessions=1, api_truncated=True)
    assert out["truncated_by"] == ["display_limit", "api_page_limit"]


def test_format_status_tolerates_overflowing_numbers() -> None:
    out = format_status({"Id": "x", "DeviceType": float("inf"), "OperatingMode": 1e400}, [], {})
    assert out["charger"]["model"] == "Unknown"
    assert out["operating_mode"]["name"] == "unknown"
