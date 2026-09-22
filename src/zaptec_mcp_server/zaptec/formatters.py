"""Pure formatters: raw API dicts -> tool payloads. No I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .observations import (
    AVAILABLE_CURRENT_MODES,
    DEVICE_TYPES,
    MODE_HINTS,
    NETWORK_TYPES,
    OPERATING_MODES,
    Obs,
    StateMap,
    decode_features,
    decode_phases,
    field,
    parse_api_datetime,
    parse_ocmf,
)


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def summarize_mode(sm: StateMap, fallback_code: int | None = None) -> dict[str, Any]:
    """Operating mode as {code, name, hint}; falls back to the charger list value."""
    code = sm.get_int(Obs.OPERATION_MODE)
    if code is None:
        code = fallback_code
    if code is None:
        return {"code": None, "name": "unknown", "hint": MODE_HINTS[0]}
    return {
        "code": code,
        "name": OPERATING_MODES.get(code, "unknown"),
        "hint": MODE_HINTS.get(code, MODE_HINTS[0]),
    }


def _device_model(charger: dict[str, Any]) -> str:
    return DEVICE_TYPES.get(_int_or_none(field(charger, "DeviceType")) or 0, "Unknown")


def _model_name(charger: dict[str, Any], ocmf: dict[str, Any]) -> str:
    product = ocmf.get("GI")
    if isinstance(product, str) and product:
        return product
    return _device_model(charger)


def _current_mode(obj: dict[str, Any]) -> str:
    code = _int_or_none(field(obj, "AvailableCurrentMode")) or 0
    return AVAILABLE_CURRENT_MODES.get(code, "manual")


def format_status(
    charger: dict[str, Any], state: list[dict[str, Any]], installation: dict[str, Any]
) -> dict[str, Any]:
    sm = StateMap(state)
    ocmf = parse_ocmf(sm.get(Obs.SIGNED_METER_VALUE))
    mode = summarize_mode(sm, _int_or_none(field(charger, "OperatingMode")))
    power_w = sm.get_float(Obs.TOTAL_CHARGE_POWER)
    return {
        "charger": {
            "id": field(charger, "Id"),
            "name": field(charger, "Name"),
            "device_id": field(charger, "DeviceId"),
            "model": _model_name(charger, ocmf),
            "firmware": ocmf.get("GV"),
            "online": bool(field(charger, "IsOnline", False)),
            "active": bool(field(charger, "Active", False)),
        },
        "operating_mode": mode,
        "charging": {
            "power_kw": _r(None if power_w is None else power_w / 1000.0),
            "session_energy_kwh": _r(sm.get_float(Obs.SESSION_ENERGY)),
            "charge_current_set_a": _r(sm.get_float(Obs.CHARGE_CURRENT_SET)),
            "active_phases": decode_phases(sm.get_int(Obs.ACTIVE_PHASES)),
            "final_stop_active": sm.get_bool(Obs.FINAL_STOP_ACTIVE),
            "current_a": {
                "l1": _r(sm.get_float(Obs.CURRENT_L1)),
                "l2": _r(sm.get_float(Obs.CURRENT_L2)),
                "l3": _r(sm.get_float(Obs.CURRENT_L3)),
            },
            "voltage_v": {
                "l1": _r(sm.get_float(Obs.VOLTAGE_L1)),
                "l2": _r(sm.get_float(Obs.VOLTAGE_L2)),
                "l3": _r(sm.get_float(Obs.VOLTAGE_L3)),
            },
            "cable_rating_a": sm.get_int(Obs.CABLE_TYPE),
            "charger_max_current_a": sm.get_float(Obs.CHARGER_MAX_CURRENT),
            "charger_min_current_a": sm.get_float(Obs.CHARGER_MIN_CURRENT),
        },
        "installation": {
            "id": field(installation, "Id"),
            "name": field(installation, "Name") or field(charger, "InstallationName"),
            "available_current_a": field(installation, "AvailableCurrent"),
            "max_current_a": field(installation, "MaxCurrent"),
            "available_current_mode": _current_mode(installation),
        },
        "diagnostics": {
            "temperature_internal_c": _r(sm.get_float(Obs.TEMPERATURE_INTERNAL)),
            "humidity_pct": _r(sm.get_float(Obs.HUMIDITY)),
            "signal_strength_dbm": sm.get_float(Obs.SIGNAL_STRENGTH),
            "communication_mode": sm.get(Obs.COMMUNICATION_MODE),
            "warnings": sm.get(Obs.WARNINGS),
        },
        "authorization_required": bool(field(charger, "IsAuthorizationRequired", False)),
        "observed_at": sm.newest_timestamp(),
    }


def _charger_summary(charger: dict[str, Any]) -> dict[str, Any]:
    mode = _int_or_none(field(charger, "OperatingMode"))
    return {
        "id": field(charger, "Id"),
        "name": field(charger, "Name"),
        "device_id": field(charger, "DeviceId"),
        "model": _device_model(charger),
        "online": field(charger, "IsOnline"),
        "operating_mode": OPERATING_MODES.get(mode, "unknown") if mode is not None else "unknown",
    }


def format_installation(
    installation: dict[str, Any], hierarchy: dict[str, Any], chargers: list[dict[str, Any]]
) -> dict[str, Any]:
    by_id = {field(c, "Id"): c for c in chargers}
    circuits = []
    for circuit in field(hierarchy, "Circuits") or []:
        members = []
        for entry in field(circuit, "Chargers") or []:
            full = by_id.get(field(entry, "Id"), entry)
            members.append(_charger_summary(full))
        circuits.append(
            {
                "id": field(circuit, "Id"),
                "name": field(circuit, "Name"),
                "max_current_a": field(circuit, "MaxCurrent"),
                "active": field(circuit, "Active"),
                "chargers": members,
            }
        )
    network = _int_or_none(field(installation, "NetworkType")) or 0
    return {
        "id": field(installation, "Id"),
        "name": field(installation, "Name"),
        "address": {
            "street": field(installation, "Address"),
            "zip_code": field(installation, "ZipCode"),
            "city": field(installation, "City"),
        },
        "timezone": field(installation, "TimeZoneIanaName"),
        "max_current_a": field(installation, "MaxCurrent"),
        "available_current_a": field(installation, "AvailableCurrent"),
        "available_current_phases_a": {
            "l1": field(installation, "AvailableCurrentPhase1"),
            "l2": field(installation, "AvailableCurrentPhase2"),
            "l3": field(installation, "AvailableCurrentPhase3"),
        },
        "available_current_mode": _current_mode(installation),
        "network_type": NETWORK_TYPES.get(network, "unknown"),
        "use_load_balancing": field(installation, "UseLoadBalancing"),
        "authentication_required": bool(field(installation, "IsRequiredAuthentication", False)),
        "features_available": decode_features(
            _int_or_none(field(installation, "AvailableFeatures"))
        ),
        "features_enabled": decode_features(_int_or_none(field(installation, "EnabledFeatures"))),
        "circuits": circuits,
    }


def _session_row(s: dict[str, Any], tz: ZoneInfo, price: float | None) -> dict[str, Any] | None:
    start = parse_api_datetime(field(s, "StartDateTime"))
    end = parse_api_datetime(field(s, "EndDateTime"))
    if start is None:
        return None
    energy = float(field(s, "Energy") or 0.0)
    duration_min = None if end is None else round((end - start).total_seconds() / 60)
    row: dict[str, Any] = {
        "id": field(s, "Id"),
        "start": start.astimezone(tz).isoformat(timespec="seconds"),
        "end": None if end is None else end.astimezone(tz).isoformat(timespec="seconds"),
        "duration_minutes": duration_min,
        "energy_kwh": round(energy, 3),
        "charger_name": field(s, "DeviceName"),
        "stopped_by_rfid": bool(field(s, "StoppedByRfid", False)),
        "offline": bool(field(s, "Offline", False)),
        "aborted": bool(field(s, "Aborted", False)),
    }
    if price is not None:
        row["cost"] = round(energy * price, 2)
    return row


def format_history(
    sessions: list[dict[str, Any]],
    *,
    tz: ZoneInfo,
    time_range: str,
    start: datetime,
    end: datetime,
    price_per_kwh: float | None,
    currency: str,
    max_sessions: int = 500,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for s in sessions:
        if field(s, "Voided", False):
            continue
        row = _session_row(s, tz, price_per_kwh)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: str(r["start"]))
    energy = sum(float(r["energy_kwh"]) for r in rows)
    minutes = sum(int(r["duration_minutes"] or 0) for r in rows)
    summary: dict[str, Any] = {
        "session_count": len(rows),
        "energy_kwh": round(energy, 3),
        "duration_hours": round(minutes / 60.0, 3),
    }
    if price_per_kwh is not None:
        summary["cost"] = round(energy * price_per_kwh, 2)
        summary["price_per_kwh"] = price_per_kwh
        summary["currency"] = currency
    return {
        "time_range": time_range,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "timezone": str(tz.key),
        "summary": summary,
        "sessions": rows[:max_sessions],
        "truncated": len(rows) > max_sessions,
    }
