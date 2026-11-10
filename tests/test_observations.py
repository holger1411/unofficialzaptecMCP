from datetime import UTC, datetime

import pytest

from zaptec_mcp_server.zaptec.observations import (
    MODE_HINTS,
    OBSERVATIONS,
    OPERATING_MODES,
    Mode,
    Obs,
    StateMap,
    decode_features,
    decode_phases,
    field,
    parse_api_datetime,
    parse_ocmf,
)


def test_observation_table_sample() -> None:
    assert OBSERVATIONS[710] == "ChargerOperationMode"
    assert OBSERVATIONS[513] == "TotalChargePower"
    assert OBSERVATIONS[718] == "FinalStopActive"
    assert Obs.OPERATION_MODE == 710
    assert OPERATING_MODES[5] == "connected_finished"


def test_state_map_accessors() -> None:
    sm = StateMap(
        [
            {"StateId": 710, "ValueAsString": "3", "Timestamp": "2026-09-22T14:17:42.1"},
            {"StateId": 513, "ValueAsString": "17.062", "Timestamp": "2026-09-22T14:30:18.5"},
            {"StateId": 718, "ValueAsString": "0", "Timestamp": "2026-09-21T07:15:02"},
            {"StateId": 150, "ValueAsString": "Wifi", "Timestamp": None},
        ]
    )
    assert sm.get_int(710) == 3
    assert sm.get_float(513) == 17.062
    assert sm.get_bool(718) is False
    assert sm.get(150) == "Wifi"
    assert sm.get(999) is None
    assert sm.get_float(150) is None
    assert sm.timestamp(710) == "2026-09-22T14:17:42.1"
    assert sm.newest_timestamp() == "2026-09-22T14:30:18.5"
    assert sm.ids() == [150, 513, 710, 718]


def test_field_is_case_tolerant() -> None:
    assert field({"OperatingMode": 3}, "OperatingMode") == 3
    assert field({"operatingMode": 3}, "OperatingMode") == 3
    assert field({"operatingmode": 3}, "OperatingMode") == 3
    assert field({}, "OperatingMode", "x") == "x"


def test_parse_api_datetime_variants() -> None:
    assert parse_api_datetime("2026-09-20T11:11:06.77+00:00") == datetime(
        2026, 9, 20, 11, 11, 6, 770000, tzinfo=UTC
    )
    assert parse_api_datetime("2026-09-21T10:48:43.91") == datetime(
        2026, 9, 21, 10, 48, 43, 910000, tzinfo=UTC
    )
    assert parse_api_datetime("2026-09-21T10:48:43Z") == datetime(
        2026, 9, 21, 10, 48, 43, tzinfo=UTC
    )
    assert parse_api_datetime("2026-09-21T10:48:43.1234567") == datetime(
        2026, 9, 21, 10, 48, 43, 123456, tzinfo=UTC
    )
    assert parse_api_datetime(None) is None
    assert parse_api_datetime("garbage") is None


def test_decoders() -> None:
    assert decode_features(0) == []
    assert decode_features(131543) == [
        "Api_MessageSubscription",
        "Authentication_Internal",
        "PowerManagement_Apm",
        "PowerManagement_Schedule",
        "Connectivity_4G",
        "Authentication_Ocpp",
        "PowerManagement_Apm_Tariff_PowerLimit",
        "PowerManagement_Apm_SurplusMode",
    ]
    assert decode_features(32 | 65536) == [
        "PowerManagement_Apm_PowerLimit",
        "PowerManagement_Apm_Tic",
    ]
    assert decode_features(None) == []
    assert decode_phases(4) == ["L3"]
    assert decode_phases(7) == ["L1", "L2", "L3"]
    assert decode_phases(0) == []


def test_parse_ocmf() -> None:
    raw = 'OCMF|{"FV":"1.0","GI":"Zaptec Go 2","GS":"ZPR000001","GV":"3.1.0.8"}|{"SA":"x"}'
    assert parse_ocmf(raw)["GV"] == "3.1.0.8"
    assert parse_ocmf("nonsense") == {}
    assert parse_ocmf(None) == {}


def test_mode_constants_match_tables() -> None:
    assert OPERATING_MODES[Mode.DISCONNECTED] == "disconnected"
    assert OPERATING_MODES[Mode.REQUESTING] == "connected_requesting"
    assert OPERATING_MODES[Mode.CHARGING] == "connected_charging"
    assert OPERATING_MODES[Mode.FINISHED] == "connected_finished"
    assert set(MODE_HINTS) == set(OPERATING_MODES)


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity", "1e999"])
def test_state_map_non_finite_values_are_none(raw: str) -> None:
    sm = StateMap([{"StateId": 710, "ValueAsString": raw}])
    assert sm.get_float(710) is None
    assert sm.get_int(710) is None
    assert sm.get_bool(710) is None
    assert sm.get(710) == raw
