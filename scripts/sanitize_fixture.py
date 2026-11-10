"""Sanitize raw Zaptec API responses for use as test fixtures.

Usage: python scripts/sanitize_fixture.py raw.json > tests/fixtures/name.json

Replaces UUIDs (consistently across files when run in one process), device
ids, names, addresses, coordinates, signatures, the charger PIN, the IoT hub
hostname, the diagnostics string and the installation's support group with fake
values. Always eyeball the result before committing.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DEVICE_ID = re.compile(r"\b[A-Z]{3}\d{6,}\b")
_STRING_KEYS: dict[str, str | None] = {
    "Name": "Garage",
    "SerialNo": "Garage",
    "DeviceName": "Garage",
    "InstallationName": "Example Installation",
    "Address": "Example Street 1",
    "ZipCode": "12345",
    "City": "Exampletown",
    "Pin": "0000",
    "RoutingId": "routing-redacted",
    "SD": "signature-redacted",
    "ContactEmail": "owner@example.com",
    "Email": "owner@example.com",
    "FullName": "Example Owner",
    "TokenName": None,
}
_NUMERIC_KEYS: dict[str, float] = {"Latitude": 0.0, "Longitude": 0.0}
# Keys whose "Name" is not a person/charger name and should be kept.
_KEEP_NAME_UNDER = {"Circuits"}
# Charger state observations whose value is identifying (name, MAC, keys, ids).
_STATE_VALUE_OVERRIDES: dict[int, str] = {
    157: "iothub.example.invalid",
    158: "scope-redacted",
    802: "Garage",
    808: "0d 00h00m00s diagnostics-redacted",
    830: "",
    952: "00:00:00:00:00:00",
    981: "publickey-redacted",
}
# Installation support group: names the installer or reseller, so every field
# that identifies it is replaced. Applied after the generic key replacements.
_SUPPORT_GROUP_OVERRIDES: dict[str, str] = {
    "Name": "Example Support Group",
    "LookupKey": "EXAMPLE",
    "SupportUrl": "https://support.example.com",
    "SupportEmail": "support@example.com",
    "SupportPhone": "",
    "SupportDetails": "",
    "CreatedOn": "2026-01-01T00:00:00",
}


class Sanitizer:
    def __init__(self) -> None:
        self.uuids: dict[str, str] = {}

    def fake_uuid(self, real: str) -> str:
        if real not in self.uuids:
            n = len(self.uuids) + 1
            self.uuids[real] = f"{n:08d}-0000-4000-8000-{n:012d}"
        return self.uuids[real]

    def text(self, value: str) -> str:
        value = _UUID.sub(lambda m: self.fake_uuid(m.group(0)), value)
        value = _DEVICE_ID.sub("ZPR000001", value)
        if value.startswith("OCMF|"):
            parts = value.split("|")
            try:
                data = json.loads(parts[1])
                data["GS"] = "ZPR000001"
                value = "|".join(
                    [parts[0], json.dumps(data, separators=(",", ":")), '{"SA":"redacted"}']
                )
            except (ValueError, IndexError, TypeError):
                pass
        return value

    def walk(self, node: Any, key: str | None = None, parent: str | None = None) -> Any:
        if isinstance(node, dict):
            state_id = node.get("StateId")
            if isinstance(state_id, int) and state_id in _STATE_VALUE_OVERRIDES:
                node = {**node, "ValueAsString": _STATE_VALUE_OVERRIDES[state_id]}
            result = {k: self.walk(v, k, key) for k, v in node.items()}
            if key == "SupportGroup":
                result.update({k: v for k, v in _SUPPORT_GROUP_OVERRIDES.items() if k in result})
            return result
        if isinstance(node, list):
            return [self.walk(v, key, parent) for v in node]
        if key is not None:
            lookup = key[:1].upper() + key[1:]
            if lookup == "Name" and parent in _KEEP_NAME_UNDER:
                return node
            if lookup in _STRING_KEYS and isinstance(node, str):
                return _STRING_KEYS[lookup]
            if lookup in _NUMERIC_KEYS and isinstance(node, (int, float)):
                return _NUMERIC_KEYS[lookup]
        if isinstance(node, str):
            return self.text(node)
        return node


def main() -> None:
    sanitizer = Sanitizer()
    with open(sys.argv[1], encoding="utf-8") as fh:
        raw = json.load(fh)
    print(json.dumps(sanitizer.walk(raw), indent=1))


if __name__ == "__main__":
    main()
