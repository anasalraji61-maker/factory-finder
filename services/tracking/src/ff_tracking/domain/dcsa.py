"""DCSA Track & Trace (v2.x) event JSON -> provider-neutral raw events for ``normalize_events``.

Shape handled (UNVERIFIED against a live carrier, fixture-driven): a bare list or ``{"events": [...]}`` of
``{eventID, eventType (SHIPMENT|TRANSPORT|EQUIPMENT), eventClassifierCode (PLN|EST|ACT), eventDateTime,
eventCreatedDateTime, transportEventTypeCode | equipmentEventTypeCode | shipmentEventTypeCode,
eventLocation{UNLocationCode, locationName}, transportCall{UNLocationCode, vessel{vesselIMONumber, vesselName},
carrierExportVoyageNumber|carrierImportVoyageNumber|carrierVoyageNumber}}``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_TYPE_KEY = {"TRANSPORT": "transportEventTypeCode", "EQUIPMENT": "equipmentEventTypeCode",
             "SHIPMENT": "shipmentEventTypeCode"}


def is_dcsa(payload: Mapping[str, Any]) -> bool:
    ev = payload.get("events")
    return "data" not in payload and isinstance(ev, list) and (not ev or "eventType" in ev[0] or "eventDateTime" in ev[0])


def dcsa_raw_events(payload: Mapping[str, Any] | list) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else payload["events"]
    out: list[dict[str, Any]] = []
    for e in items:
        if not isinstance(e, Mapping):
            raise TypeError("event is not an object")
        etype = str(e.get("eventType") or "").upper()
        code = e.get(_TYPE_KEY.get(etype, "")) or e.get("transportEventTypeCode") or e.get("equipmentEventTypeCode") \
            or e.get("shipmentEventTypeCode")
        tc = e.get("transportCall") or {}
        loc = e.get("eventLocation") or {}
        classifier = str(e.get("eventClassifierCode") or "").upper()
        voyage = tc.get("carrierExportVoyageNumber") or tc.get("carrierImportVoyageNumber") \
            or tc.get("carrierVoyageNumber") or tc.get("exportVoyageNumber")
        v = tc.get("vessel") or {}
        out.append({
            "code": code, "timestamp": e.get("eventDateTime"), "created": e.get("eventCreatedDateTime"),
            "classifier": classifier, "actual": (classifier == "ACT") if classifier else None,
            "event_id": e.get("eventID"),
            "hub": loc.get("UNLocationCode") or tc.get("UNLocationCode"), "name": loc.get("locationName"),
            "vessel": {"name": v.get("vesselName") or v.get("name"), "imo": v.get("vesselIMONumber"), "voyage": voyage}
            if v else None,
        })
    return out
