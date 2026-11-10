"""Observation-id table, enum decoders and small parsing helpers."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

# Generated from the ObservationId enum in the official Zaptec OpenAPI spec
# (https://api.zaptec.com/swagger/v1/swagger.json).
OBSERVATIONS: dict[int, str] = {
    0: "Unknown",
    1: "OfflineMode",
    100: "Capabilities",
    110: "ProductName",
    111: "ArenaId",
    120: "AuthenticationRequired",
    130: "PaymentActive",
    131: "PaymentCurrency",
    132: "PaymentSessionUnitPrice",
    133: "PaymentEnergyUnitPrice",
    134: "PaymentTimeUnitPrice",
    150: "CommunicationMode",
    151: "PermanentCableLock",
    152: "ProductCode",
    153: "HmiBrightness",
    154: "LockCableWhenConnected",
    155: "SoftStartDisabled",
    156: "FirmwareApiHost",
    157: "DpsAssignedIotHub",
    158: "DpsScopeId",
    159: "IoTHubOverride",
    170: "MIDBlinkEnabled",
    180: "ProductionTesterEnabled",
    181: "ProductionTestStationOverride",
    201: "TemperatureInternal5",
    202: "TemperatureInternal6",
    203: "TemperatureInternalLimit",
    205: "TemperaturePowerBoard",
    241: "TemperatureInternalMaxLimit",
    270: "Humidity",
    280: "TamperCover",
    501: "VoltagePhase1",
    502: "VoltagePhase2",
    503: "VoltagePhase3",
    507: "CurrentPhase1",
    508: "CurrentPhase2",
    509: "CurrentPhase3",
    510: "ChargerMaxCurrent",
    511: "ChargerMinCurrent",
    512: "ActivePhases",
    513: "TotalChargePower",
    515: "RcdCurrent",
    517: "Internal12vCurrent",
    518: "PowerFactor",
    519: "SetPhases",
    520: "MaxPhases",
    522: "ChargerOfflinePhase",
    523: "ChargerOfflineCurrent",
    527: "DetectedMaxPhases",
    528: "DetectedMaxCurrent",
    529: "DetectedCurrentLimitReason",
    540: "RcdCalibration",
    541: "RcdCalibrationNoise",
    542: "ManualRcdTest",
    553: "TotalChargePowerSession",
    554: "SignedMeterValue",
    555: "SignedMeterValueInterval",
    560: "SessionEnergyCountExportActive",
    561: "SessionEnergyCountExportReactive",
    562: "SessionEnergyCountImportActive",
    563: "SessionEnergyCountImportReactive",
    570: "SoftStartTime",
    701: "ChargeDuration",
    702: "ChargeMode",
    703: "ChargePilotLevelInstant",
    704: "ChargePilotLevelAverage",
    706: "PilotVsProximityTime",
    708: "ChargeCurrentSet",
    710: "ChargerOperationMode",
    711: "IsEnabled",
    712: "IsStandAlone",
    713: "ChargerCurrentUserUuidDeprecated",
    714: "CableType",
    715: "NetworkType",
    716: "DetectedCar",
    717: "GridTestResult",
    718: "FinalStopActive",
    719: "AuthorizationTimeout",
    720: "TariffText",
    721: "SessionIdentifier",
    722: "ChargerCurrentUserUuid",
    723: "CompletedSession",
    724: "PlugAndChargeAuthorizeRequest",
    725: "RejectedUserUuid",
    750: "NewChargeCard",
    751: "AuthenticationListVersion",
    752: "EnabledNfcTechnologies",
    753: "LteRoamingDisabled",
    760: "Location",
    761: "TimeZone",
    762: "TimeSchedule",
    763: "NextScheduleEvent",
    764: "MaxStartDelay",
    800: "InstallationId",
    801: "RoutingId",
    803: "Notifications",
    804: "Warnings",
    805: "DiagnosticsMode",
    807: "InternalDiagnosticsLog",
    808: "DiagnosticsString",
    809: "CommunicationSignalStrength",
    810: "CloudConnectionStatus",
    811: "McuResetSource",
    812: "McuRxErrors",
    813: "McuToVariscitePacketErrors",
    814: "VarisciteToMcuPacketErrors",
    816: "MIDFaultFlags",
    817: "RelayWeldedFlags",
    820: "UptimeVariscite",
    821: "UptimeMCU",
    823: "CertificateVersion",
    830: "SecurityLog",
    850: "CarSessionLog",
    851: "CommunicationModeConfigurationInconsistency",
    852: "RawPilotMonitor",
    853: "IT3PhaseDiagnosticsLog",
    854: "PilotTestResults",
    855: "UnconditionalNfcDetectionIndication",
    856: "EnableLteDetailedSignalStrength",
    857: "EnableLocalNetworkMaintenance",
    860: "SessionController",
    861: "OcppNativeUrl",
    862: "OcppNativeCbId",
    865: "OcppNativeSecurityProfile",
    866: "OcppNativeConnected",
    867: "OcppTunnelCall",
    868: "OcppNativeZaptecLoadBalancingEnabled",
    869: "OcppNativeOnePhaseChargingPhase",
    899: "EmcTestCounter",
    900: "ProductionTestResults",
    901: "PostProductionTestResults",
    908: "SmartMainboardSoftwareApplicationVersion",
    909: "SmartMainboardSoftwareBootloaderVersion",
    911: "SmartComputerSoftwareApplicationVersion",
    912: "SmartComputerSoftwareBootloaderVersion",
    913: "SmartComputerHardwareVersion",
    914: "MIDLegallyRelevantSoftwareIdentifier",
    920: "PlcPibVersionGrid",
    921: "PlcPibVersionEV",
    930: "AppliedImageUpdates",
    931: "FailedImageUpdates",
    950: "MacMain",
    951: "MacPlcModuleGrid",
    952: "MacWiFi",
    953: "MacPlcModuleEv",
    960: "LteImsi",
    961: "LteMsisdn",
    962: "LteIccid",
    963: "LteImei",
    964: "LteVersion",
    965: "LteDetailedSignalStrength",
    970: "ProductionTestStationNumber",
    980: "MIDCalibration",
    981: "MIDPublicKey",
    982: "MIDCalibrationID",
    3: "IsOcppConnected",
    2: "IsOnline",
}


class Obs:
    """Observation ids used by the formatters."""

    AUTHENTICATION_REQUIRED = 120
    COMMUNICATION_MODE = 150
    PERMANENT_CABLE_LOCK = 151
    TEMPERATURE_INTERNAL = 201
    HUMIDITY = 270
    VOLTAGE_L1 = 501
    VOLTAGE_L2 = 502
    VOLTAGE_L3 = 503
    CURRENT_L1 = 507
    CURRENT_L2 = 508
    CURRENT_L3 = 509
    CHARGER_MAX_CURRENT = 510
    CHARGER_MIN_CURRENT = 511
    TOTAL_CHARGE_POWER = 513
    SET_PHASES = 519
    MAX_PHASES = 520
    SESSION_ENERGY = 553
    SIGNED_METER_VALUE = 554
    CHARGE_MODE = 702
    CHARGE_CURRENT_SET = 708
    OPERATION_MODE = 710
    IS_ENABLED = 711
    CABLE_TYPE = 714
    FINAL_STOP_ACTIVE = 718
    SESSION_IDENTIFIER = 721
    NEXT_SCHEDULE_EVENT = 763
    WARNINGS = 804
    SIGNAL_STRENGTH = 809
    CLOUD_CONNECTION = 810
    UPTIME = 820


class Mode:
    """ChargerOperationMode (observation 710) codes."""

    UNKNOWN = 0
    DISCONNECTED = 1
    REQUESTING = 2
    CHARGING = 3
    FINISHED = 5


OPERATING_MODES: dict[int, str] = {
    Mode.UNKNOWN: "unknown",
    Mode.DISCONNECTED: "disconnected",
    Mode.REQUESTING: "connected_requesting",
    Mode.CHARGING: "connected_charging",
    Mode.FINISHED: "connected_finished",
}
MODE_HINTS: dict[int, str] = {
    Mode.UNKNOWN: "state unknown (charger offline or no data yet)",
    Mode.DISCONNECTED: "no vehicle connected",
    Mode.REQUESTING: (
        "vehicle connected, waiting for authorization or for the vehicle to request power"
    ),
    Mode.CHARGING: "charging",
    Mode.FINISHED: (
        "connected but not charging: paused by user/app, finished, or vehicle stopped drawing"
    ),
}
DEVICE_TYPES: dict[int, str] = {
    0: "Unknown",
    1: "Zaptec Pro",
    2: "Zaptec Portable",
    3: "Zaptec Home APM",
    4: "Zaptec Go / Go 2",
    5: "Other APM",
    6: "Generic APM",
    7: "HAN APM",
    8: "TIC APM",
}
NETWORK_TYPES: dict[int, str] = {
    0: "unknown",
    1: "IT_1_phase",
    2: "IT_3_phase",
    3: "TN_1_phase",
    4: "TN_3_phase",
}
AVAILABLE_CURRENT_MODES: dict[int, str] = {0: "manual", 1: "schedule", 2: "auto"}
FEATURES: dict[int, str] = {
    1: "Api_MessageSubscription",
    2: "Authentication_Internal",
    4: "PowerManagement_Apm",
    8: "PowerManagement_EcoMode",
    16: "PowerManagement_Schedule",
    32: "PowerManagement_Apm_PowerLimit",
    64: "Connectivity_4G",
    128: "Authentication_Ocpp",
    256: "PowerManagement_Apm_Tariff_PowerLimit",
    512: "Authentication_OcppNative",
    65536: "PowerManagement_Apm_Tic",
    131072: "PowerManagement_Apm_SurplusMode",
}
_PHASE_BITS = {1: "L1", 2: "L2", 4: "L3"}
# Observation 519 (SetPhases) holds an id from the PhaseIdMap constant of
# /api/constants, not a bit mask: id -> Phases flags (1 = L1, 2 = L2, 4 = L3).
# Ids 1-4 are TN networks, 5-9 IT networks.
_PHASE_ID_FLAGS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 4, 6: 2, 8: 1, 9: 7}


def decode_features(bits: int | None) -> list[str]:
    if not bits:
        return []
    return [name for bit, name in FEATURES.items() if bits & bit]


def decode_phases(bits: int | None) -> list[str]:
    """Phases flags (bit mask) -> phase names."""
    if not bits:
        return []
    return [name for bit, name in _PHASE_BITS.items() if bits & bit]


def decode_phase_id(phase_id: int | None) -> list[str]:
    """SetPhases id -> phase names; unknown ids give an empty list."""
    if phase_id is None:
        return []
    return decode_phases(_PHASE_ID_FLAGS.get(phase_id))


def field(d: Mapping[str, Any], name: str, default: Any = None) -> Any:
    """Case-tolerant key lookup: exact, camelCase, then case-insensitive."""
    if name in d:
        return d[name]
    camel = name[:1].lower() + name[1:]
    if camel in d:
        return d[camel]
    lowered = name.lower()
    for key, value in d.items():
        if key.lower() == lowered:
            return value
    return default


_FRACTION = re.compile(r"(\.\d+)")


def parse_api_datetime(value: str | None) -> datetime | None:
    """Parse Zaptec timestamps (naive = UTC, any fraction length, Z or offset)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")

    def _pad(m: re.Match[str]) -> str:
        digits = m.group(1)[1:][:6]
        return "." + digits.ljust(6, "0")

    text = _FRACTION.sub(_pad, text, count=1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def parse_ocmf(value: str | None) -> dict[str, Any]:
    """Return the data block of an OCMF|{...}|{...} signed meter value, or {}."""
    if not value or not value.startswith("OCMF|"):
        return {}
    parts = value.split("|")
    if len(parts) < 2:
        return {}
    try:
        data = json.loads(parts[1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class StateMap:
    """Index a /api/chargers/{id}/state list by observation id."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._by_id: dict[int, dict[str, Any]] = {}
        for entry in entries:
            sid = field(entry, "StateId")
            if isinstance(sid, int):
                self._by_id[sid] = entry

    def ids(self) -> list[int]:
        return sorted(self._by_id)

    def get(self, sid: int) -> str | None:
        entry = self._by_id.get(sid)
        if entry is None:
            return None
        value = field(entry, "ValueAsString")
        return None if value is None else str(value)

    def get_float(self, sid: int) -> float | None:
        raw = self.get(sid)
        if raw is None:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        # "nan"/"inf" parse as floats but are not usable readings (and not valid JSON).
        return value if math.isfinite(value) else None

    def get_int(self, sid: int) -> int | None:
        value = self.get_float(sid)
        return None if value is None else int(value)

    def get_bool(self, sid: int) -> bool | None:
        value = self.get_int(sid)
        return None if value is None else value != 0

    def timestamp(self, sid: int) -> str | None:
        entry = self._by_id.get(sid)
        if entry is None:
            return None
        ts = field(entry, "Timestamp")
        return None if ts is None else str(ts)

    def newest_timestamp(self) -> str | None:
        stamps = [field(e, "Timestamp") for e in self._by_id.values()]
        valid = [s for s in stamps if isinstance(s, str)]
        return max(valid) if valid else None
