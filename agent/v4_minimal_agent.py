"""A tiny deterministic v4 participant used by the local parity smoke."""

from __future__ import annotations

import json
import sys
from datetime import datetime


PROTOCOL = "participant-agent-protocol-v4"
targets = {}
site = {}
fiber = {}
observed = set()
nights = []


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1].replace("T", " "))


def jd(instant: datetime) -> float:
    return 2451545.0 + (instant - datetime(2000, 1, 1, 12, 0, 0)).total_seconds() / 86400.0


def lst_deg(instant: datetime) -> float:
    days = jd(instant) - 2451545.0
    centuries = days / 36525.0
    gmst = 280.46061837 + 360.98564736629 * days + 0.000387933 * centuries * centuries - centuries**3 / 38710000.0
    return (gmst + float(site["longitude_deg"])) % 360.0


def radec_to_altaz(ra_deg: float, dec_deg: float, instant: datetime) -> tuple[float, float]:
    import math

    radians = math.pi / 180.0
    latitude = float(site["latitude_deg"]) * radians
    dec = dec_deg * radians
    hour_angle = ((lst_deg(instant) - ra_deg + 180.0) % 360.0 - 180.0) * radians
    sin_alt = math.sin(dec) * math.sin(latitude) + math.cos(dec) * math.cos(latitude) * math.cos(hour_angle)
    alt = math.asin(max(-1.0, min(1.0, sin_alt))) / radians
    az = math.degrees(math.atan2(-math.sin(hour_angle) * math.cos(dec), math.sin(dec) * math.cos(latitude) - math.cos(dec) * math.sin(latitude) * math.cos(hour_angle))) % 360.0
    return alt, az


def pointing_for_target(target: dict, instant: datetime) -> dict[str, float]:
    import math

    n = int(fiber["field"]["n_fibers"])
    side = int(math.isqrt(n))
    cell_side = math.sqrt(float(fiber["field"]["fiber_area_deg2"]))
    fiber_index = 0
    row, column = divmod(fiber_index, side)
    center = (side - 1) / 2.0
    east = (column - center) * (cell_side + float(fiber["field"].get("gap_deg", 0.0)))
    north = (center - row) * (cell_side + float(fiber["field"].get("gap_deg", 0.0)))
    dec = float(target["dec_deg"])
    ra = (float(target["ra_deg"]) - east / max(1e-6, math.cos(math.radians(dec)))) % 360.0
    dec -= north
    alt, az = radec_to_altaz(ra, dec, instant)
    return {"alt_deg": round(alt, 8), "az_deg": round(az, 8)}


def observing_now(instant: datetime) -> bool:
    return any(
        utc(night["observing_start_utc"]) <= instant < utc(night["observing_end_utc"])
        for night in nights
    )


def response(sequence: int, action: dict) -> None:
    value = {
        "protocol_version": PROTOCOL,
        "message_type": "decision_response",
        "decision_sequence": sequence,
        **action,
    }
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for raw in sys.stdin:
    message = json.loads(raw)
    message_type = message.get("message_type")
    payload = message.get("payload", {})
    if message_type == "initialize":
        targets = {row["target_id"]: row for row in payload["targets"]}
        site = payload["site"]
        fiber = payload["fiber_config"]
        nights = payload.get("calendar", {}).get("nights", [])
        continue
    if message_type == "finish":
        break
    if message_type != "decision_request":
        continue
    sequence = int(message["decision_sequence"])
    for hit in payload.get("last_result", {}).get("hits", []):
        observed.add(hit["target_id"])
    now = utc(payload["now_utc"])
    visible = []
    if observing_now(now):
        for target_id, target in targets.items():
            if target_id in observed:
                continue
            alt, _ = radec_to_altaz(float(target["ra_deg"]), float(target["dec_deg"]), now)
            if alt >= 31.0:
                visible.append((target_id, target))
    if visible:
        target_id, target = visible[0]
        response(sequence, {
            "action": "observe",
            "pointing": pointing_for_target(target, now),
            "assignments": {"0": target_id},
            "duration_seconds": 60,
            "program": "BACKUP",
        })
        continue
    until = None
    for night in nights:
        start = utc(night["observing_start_utc"])
        if start > now:
            until = night["observing_start_utc"]
            break
    if until:
        response(sequence, {"action": "wait", "until_utc": until})
    else:
        response(sequence, {"action": "finish"})
