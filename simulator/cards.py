"""Build isolated synthetic v4 scenarios from the public alpha-delta inputs.

The organizer publishes alpha-delta public catalogues and calendars, but not weather
truth, event history, or observation requests. This module keeps those published inputs
and generates the missing environment locally. Fixed calibration cards use versioned
hidden profiles; seeded cards are a separate reproducible test mode. Neither is an
official organizer truth set or an official score.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

GENERATOR_VERSION = "alpha-delta-synthetic-calibration-v15-independent"
CARD_IDS = ("alpha", "beta", "gamma", "delta")
_PROFILE_LABELS = {"alpha": "Alpha-like", "beta": "Beta-like", "gamma": "Gamma-like", "delta": "Delta-like"}
_CARD_METADATA = {
    "alpha": {"title": "Alpha", "symbol": "α", "start_date": "2026-10-04", "end_date": "2026-11-10", "night_count": 38, "target_count": 10000, "fiber_count": 16},
    "beta": {"title": "Beta", "symbol": "β", "start_date": "2026-10-18", "end_date": "2026-11-24", "night_count": 38, "target_count": 9600, "fiber_count": 16},
    "gamma": {"title": "Gamma", "symbol": "γ", "start_date": "2026-10-09", "end_date": "2026-11-15", "night_count": 38, "target_count": 9900, "fiber_count": 16},
    "delta": {"title": "Delta", "symbol": "δ", "start_date": "2026-10-24", "end_date": "2026-11-30", "night_count": 38, "target_count": 9400, "fiber_count": 16},
}

# Seed distributions are independent of the frozen calibration environments.
_SEED_PROFILES: dict[str, dict] = {
    "alpha": {"rng_key": "candidate-alpha-010", "state_probabilities": (0.68, 0.22, 0.10), "seeing_shift": 0.155, "transparency_shift": -0.077, "sky_shift": -0.077, "efficiency_shift": -0.008, "closed_slot_extra": 0.08, "directional_events": (7, 10), "fault_events": (2, 3), "closure_events": (2, 3), "request_count": (4, 7), "request_size": (8, 12), "request_reward": (80.0, 140.0)},
    "beta": {"rng_key": "independent-beta-fit9", "state_probabilities": (0.64, 0.23, 0.13), "seeing_shift": 0.06, "transparency_shift": -0.04, "sky_shift": -0.04, "efficiency_shift": -0.01, "closed_slot_extra": 0.04, "directional_events": (7, 10), "fault_events": (2, 3), "closure_events": (2, 3), "request_count": (5, 8), "request_size": (8, 14), "request_reward": (80.0, 140.0)},
    "gamma": {"rng_key": "independent-gamma-fit9", "state_probabilities": (0.64, 0.24, 0.12), "seeing_shift": 0.08, "transparency_shift": -0.04, "sky_shift": -0.04, "efficiency_shift": -0.01, "closed_slot_extra": 0.035, "directional_events": (7, 10), "fault_events": (2, 3), "closure_events": (2, 3), "request_count": (4, 8), "request_size": (8, 14), "request_reward": (80.0, 140.0)},
    "delta": {"rng_key": "candidate-delta-002", "state_probabilities": (0.65, 0.24, 0.11), "seeing_shift": 0.035, "transparency_shift": -0.008, "sky_shift": -0.008, "efficiency_shift": -0.006, "closed_slot_extra": 0.012, "directional_events": (6, 9), "fault_events": (1, 2), "closure_events": (1, 2), "request_count": (4, 8), "request_size": (8, 14), "request_reward": (80.0, 140.0)},
}

CALIBRATION_VERSION = "calibration-v1"

# Retained for developer candidate scripts; the application never generates
# fixed cards from these profiles. Frozen truth files are their sole source.
_FIXED_PROFILES = {key: dict(value) for key, value in _SEED_PROFILES.items()}

# seeing, transparency, sky quality, efficiency ranges, and clear/open probability
_WEATHER_STATES = (
    ((0.78, 1.30), (0.78, 0.99), (0.76, 0.98), (0.88, 0.99), 0.992),
    ((1.10, 1.85), (0.48, 0.82), (0.46, 0.82), (0.78, 0.94), 0.955),
    ((1.55, 2.55), (0.20, 0.58), (0.20, 0.62), (0.62, 0.86), 0.82),
)
_EVENT_FIELDS = ["event_id", "event_type", "actual_start_utc", "actual_end_utc", "scope_type", "azimuth_start_deg", "azimuth_end_deg", "min_altitude_deg", "max_altitude_deg", "magnitude", "severity", "force_close", "zero_score", "seeing_multiplier", "transparency_multiplier", "sky_quality_multiplier", "instrument_efficiency_multiplier"]
_WEATHER_FIELDS = ["slot_id", "night_id", "timestamp_utc", "duration_seconds", "is_observable", "seeing_arcsec", "transparency", "sky_quality", "instrument_efficiency"]
_SLOT_FIELDS = ["slot_id", "night_id", "timestamp_utc", "duration_seconds"]
_EARTHQUAKE_FIELDS = ["event_id", "night_id", "magnitude", "degradation", "seeing_multiplier", "transparency_multiplier", "sky_quality_multiplier", "instrument_efficiency_multiplier"]
_STRESS_FIELDS = ["event_id", "event_type", "trigger_mode", "trigger_ref", "window_start_fraction", "window_end_fraction", "window_max_fraction", "alt_offset_rad", "az_offset_rad"]


def _resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def _public_root(public_root: Path | None = None) -> Path:
    root = Path(public_root) if public_root is not None else _resource_root() / "vendor" / "public-input"
    return root.expanduser().resolve()


def _profile_key(profile: str) -> str:
    value = str(profile or "").strip().lower()
    if value.endswith("-like"):
        value = value[:-5]
    if value not in CARD_IDS:
        raise ValueError("base profile must be alpha-like, beta-like, gamma-like, or delta-like")
    return value


def available_fixed_cards() -> list[dict]:
    result = []
    for card in CARD_IDS:
        frozen = _resource_root() / "simulator" / CALIBRATION_VERSION / card
        manifest = json.loads((frozen / "simulation_manifest.json").read_text(encoding="utf-8"))
        result.append({"card_id": card, "label": f"{_CARD_METADATA[card]['symbol']} {card} · 固定校准", "source": "synthetic-calibration", "base_profile": card, **_CARD_METADATA[card], "calibration_id": manifest["calibration_id"], "local_bare_agent_score": manifest["validation"]["total"], "baseline_counts": manifest["validation"]["counts"], "baseline_report_path": str(frozen / "baseline_score_report.json"), "environment_summary": environment_summary(frozen)})
    return result


def list_base_profiles() -> list[dict]:
    return [{"profile_id": f"{card}-like", "label": _PROFILE_LABELS[card], "public_card_id": card, "description": "Retains this public catalogue and calendar; synthesizes local hidden conditions.", **_CARD_METADATA[card]} for card in CARD_IDS]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, records: Iterable[Mapping]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rng(profile_key: str, rng_key: str, stream: str) -> random.Random:
    digest = hashlib.sha256(f"{GENERATOR_VERSION}|{profile_key}|{rng_key}|{stream}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def _slots(calendar_path: Path) -> list[dict[str, object]]:
    _, nights = _read_csv(calendar_path)
    slots: list[dict[str, object]] = []
    for night in nights:
        start = _parse_utc(night["observing_start_utc"])
        for index in range(int(night["slot_count"])):
            moment = start + timedelta(minutes=15 * index)
            slots.append({"slot_id": f"{night['night_id']}-S{index + 1:03d}", "night_id": night["night_id"], "timestamp_utc": _utc(moment), "duration_seconds": 900, "start": moment})
    if not slots:
        raise ValueError(f"public night calendar has no slots: {calendar_path}")
    return slots


def _weather_rows(slots: list[dict[str, object]], profile: Mapping, rng: random.Random) -> list[dict[str, str]]:
    probabilities = tuple(float(v) for v in profile["state_probabilities"])
    if len(probabilities) != 3 or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-6):
        raise ValueError("weather state probabilities must sum to one")
    cumulative = (probabilities[0], probabilities[0] + probabilities[1])
    night_state: dict[str, int] = {}
    for slot in slots:
        night = str(slot["night_id"])
        if night not in night_state:
            draw = rng.random()
            night_state[night] = 0 if draw < cumulative[0] else (1 if draw < cumulative[1] else 2)
    rows = []
    for slot in slots:
        state = night_state[str(slot["night_id"])]
        seeing_range, trans_range, sky_range, eff_range, open_prob = _WEATHER_STATES[state]
        seeing = _bounded(rng.uniform(*seeing_range) + float(profile["seeing_shift"]), 0.45, 3.0)
        trans = _bounded(rng.uniform(*trans_range) + float(profile["transparency_shift"]), 0.05, 1.0)
        sky = _bounded(rng.uniform(*sky_range) + float(profile["sky_shift"]), 0.05, 1.0)
        eff = _bounded(rng.uniform(*eff_range) + float(profile["efficiency_shift"]), 0.1, 1.0)
        observable = rng.random() < max(0.05, open_prob - float(profile["closed_slot_extra"]))
        rows.append({"slot_id": str(slot["slot_id"]), "night_id": str(slot["night_id"]), "timestamp_utc": str(slot["timestamp_utc"]), "duration_seconds": "900", "is_observable": str(observable).lower(), "seeing_arcsec": _fmt(seeing), "transparency": _fmt(trans), "sky_quality": _fmt(sky), "instrument_efficiency": _fmt(eff)})
    return rows


def _event_record(event_id: str, event_type: str, start: datetime, end: datetime, *, scope: str = "ALL", az0: float | None = None, az1: float | None = None, alt0: float | None = None, alt1: float | None = None, magnitude: str = "", severity: float = 1.0, close: bool = False, zero: bool = False, seeing: float = 1.0, trans: float = 1.0, sky: float = 1.0, eff: float = 1.0) -> dict[str, str]:
    opt = lambda value: "" if value is None else _fmt(value)
    return {"event_id": event_id, "event_type": event_type, "actual_start_utc": _utc(start), "actual_end_utc": _utc(end), "scope_type": scope, "azimuth_start_deg": opt(az0), "azimuth_end_deg": opt(az1), "min_altitude_deg": opt(alt0), "max_altitude_deg": opt(alt1), "magnitude": magnitude, "severity": _fmt(severity), "force_close": str(close).lower(), "zero_score": str(zero).lower(), "seeing_multiplier": _fmt(seeing), "transparency_multiplier": _fmt(trans), "sky_quality_multiplier": _fmt(sky), "instrument_efficiency_multiplier": _fmt(eff)}


def _build_events(slots: list[dict[str, object]], profile: Mapping, rng: random.Random) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    n = len(slots)

    def window(min_steps: int, max_steps: int) -> tuple[datetime, datetime]:
        index = rng.randrange(max(1, n - min_steps + 1))
        end_index = min(n, index + rng.randint(min_steps, max_steps))
        return slots[index]["start"], slots[end_index - 1]["start"] + timedelta(seconds=900)

    kinds = (("rainy", 0.70, 0.73, 0.75, 0.94), ("cloudy", 0.85, 0.78, 0.73, 0.96), ("smoggy", 0.92, 0.88, 0.70, 0.97), ("cold_wave", 1.10, 0.83, 0.78, 0.92), ("tornado", 0.88, 0.82, 0.80, 0.95))
    for index in range(rng.randint(*profile["directional_events"])):
        start, end = window(1, 5)
        event_type, see, trans, sky, eff = rng.choice(kinds)
        az0 = rng.uniform(0.0, 360.0)
        events.append(_event_record(f"SIM-EV-{index + 1:03d}", event_type, start, end, scope="HORIZON_SECTOR", az0=az0, az1=(az0 + rng.uniform(35.0, 125.0)) % 360.0, alt0=30.0, alt1=rng.uniform(55.0, 85.0), severity=rng.uniform(0.35, 0.85), seeing=see, trans=trans, sky=sky, eff=eff))
    for index in range(rng.randint(*profile["fault_events"])):
        start, end = window(1, 4)
        events.append(_event_record(f"SIM-FAULT-{index + 1:03d}", "instrument_fault", start, end, severity=rng.uniform(0.35, 0.72), eff=rng.uniform(0.30, 0.72)))
    for index in range(rng.randint(*profile["closure_events"])):
        start, end = window(1, 2)
        events.append(_event_record(f"SIM-CLOSE-{index + 1:03d}", "rocket_launch", start, end, severity=rng.uniform(0.6, 1.0), close=True))
    return sorted(events, key=lambda item: (item["actual_start_utc"], item["event_id"]))


def _build_bulletins(slots: list[dict[str, object]], weather: list[dict[str, str]], events: list[dict[str, str]], rng: random.Random) -> list[dict]:
    by_slot = {row["slot_id"]: row for row in weather}
    seen: set[str] = set()
    result = []
    for slot in slots:
        night = str(slot["night_id"])
        initial = night not in seen
        seen.add(night)
        moment = slot["start"]
        notices = []
        for event in events:
            if _parse_utc(event["actual_start_utc"]) <= moment < _parse_utc(event["actual_end_utc"]) and rng.random() >= 0.18:
                direction = rng.choice(("N", "NE", "E", "SE", "S", "SW", "W", "NW")) if event["scope_type"] == "HORIZON_SECTOR" else "ALL"
                notices.append({"event_kind": event["event_type"], "direction": direction})
        row = by_slot[str(slot["slot_id"])]
        poor = float(row["transparency"]) < 0.5 or float(row["sky_quality"]) < 0.5
        if poor and rng.random() < 0.7:
            notices.append({"event_kind": rng.choice(("overcast", "rain", "haze")), "direction": "ALL"})
        elif not poor and rng.random() < 0.025:
            notices.append({"event_kind": "overcast", "direction": rng.choice(("N", "S", "ALL"))})
        result.append({"record_type": "bulletin", "slot_id": str(slot["slot_id"]), "night_id": night, "issued_at_utc": str(slot["timestamp_utc"]), "initial": initial, "notices": notices})
    return result


def _build_forecasts(slots: list[dict[str, object]], events: list[dict[str, str]], rng: random.Random) -> list[dict]:
    if not slots:
        return []
    end_of_survey = slots[-1]["start"] + timedelta(seconds=900)
    result = []
    index = 0
    while index < len(slots):
        issued = slots[index]["start"]
        coverage_end = min(issued + timedelta(days=7), end_of_survey)
        notices = []
        for event in events:
            event_start = _parse_utc(event["actual_start_utc"])
            if issued <= event_start < coverage_end and rng.random() < 0.55:
                notices.append({"event_kind": event["event_type"], "direction": rng.choice(("ALL", "N", "SE", "S", "SW", "W")), "nights": [event_start.date().isoformat()]})
        if rng.random() < 0.18:
            false_night = min(issued + timedelta(days=rng.randint(1, 6)), end_of_survey - timedelta(minutes=15))
            notices.append({"event_kind": "rain", "direction": "ALL", "nights": [false_night.date().isoformat()]})
        result.append({"record_type": "forecast", "issued_at_utc": _utc(issued), "coverage_start_utc": _utc(issued), "coverage_end_utc": _utc(coverage_end), "notices": notices})
        while index < len(slots) and slots[index]["start"] < coverage_end:
            index += 1
    return result


def _build_requests(slots: list[dict[str, object]], targets_path: Path, score_path: Path, profile: Mapping, rng: random.Random) -> list[dict]:
    _, targets = _read_csv(targets_path)
    if not targets:
        return []
    score = json.loads(score_path.read_text(encoding="utf-8"))
    threshold = float(score.get("observation_requests", {}).get("completion_factor_threshold", 0.5))
    low, high = profile["request_count"]
    count = min(rng.randint(int(low), int(high)), max(1, len(slots) // 20))
    last = slots[-1]["start"] + timedelta(seconds=900)
    target_ids = [str(row["target_id"]) for row in targets]
    result = []
    for index in range(count):
        slot_index = min(len(slots) - 2, max(0, int((index + 1) * len(slots) / (count + 1))))
        issued = slots[slot_index]["start"]
        deadline = min(issued + timedelta(days=rng.randint(1, 3)), last)
        if deadline <= issued:
            continue
        size = min(rng.randint(int(profile["request_size"][0]), int(profile["request_size"][1])), len(target_ids))
        selected = rng.sample(target_ids, size)
        reward_low, reward_high = profile["request_reward"]
        result.append({"schema_version": "v4-observation-request-v1", "record_type": "observation_request", "request_id": f"SIM-RQ-{index + 1:03d}", "issued_at_utc": _utc(issued), "deadline_utc": _utc(deadline), "target_ids": selected, "minimum_completed": max(1, math.ceil(size * rng.uniform(0.45, 0.75))), "completion_factor_threshold": threshold, "completion_reward": round(rng.uniform(float(reward_low), float(reward_high)), 2), "reason": "synthetic time-critical follow-up"})
    return result


def _build_earthquake_effects(events: list[dict[str, str]], slots: list[dict[str, object]]) -> list[dict[str, str]]:
    result = []
    for event in events:
        if event["event_type"] != "earthquake":
            continue
        moment = _parse_utc(event["actual_start_utc"])
        slot = next((item for item in slots if item["start"] <= moment < item["start"] + timedelta(seconds=900)), None)
        result.append({"event_id": event["event_id"], "night_id": str(slot["night_id"]) if slot else "", "magnitude": event["magnitude"] or "5.0", "degradation": "0.000000", "seeing_multiplier": "1.000000", "transparency_multiplier": "1.000000", "sky_quality_multiplier": "1.000000", "instrument_efficiency_multiplier": "1.000000"})
    return result


def _add_earthquake_for_stress(slots: list[dict[str, object]], events: list[dict[str, str]], rng: random.Random) -> str:
    index = rng.randrange(max(0, int(len(slots) * 0.35)), max(1, int(len(slots) * 0.72)))
    start = slots[index]["start"]
    event_id = "SIM-EARTHQUAKE-001"
    events.append(_event_record(event_id, "earthquake", start, start + timedelta(minutes=15), severity=rng.uniform(5.0, 6.4), magnitude=_fmt(rng.uniform(5.0, 6.4))))
    events.sort(key=lambda item: (item["actual_start_utc"], item["event_id"]))
    return event_id


def _build_stress_events(earthquake_id: str, rng: random.Random) -> list[dict[str, str]]:
    return [
        {"event_id": "SIM-STRESS-DATA-LOSS", "event_type": "data_loss", "trigger_mode": "after_earthquake", "trigger_ref": earthquake_id, "window_start_fraction": _fmt(rng.uniform(0.36, 0.43)), "window_end_fraction": _fmt(rng.uniform(0.44, 0.51)), "window_max_fraction": _fmt(rng.uniform(0.03, 0.06)), "alt_offset_rad": "", "az_offset_rad": ""},
        {"event_id": "SIM-STRESS-POINTING", "event_type": "pointing_offset", "trigger_mode": "at_survey_start", "trigger_ref": "", "window_start_fraction": "", "window_end_fraction": "", "window_max_fraction": "", "alt_offset_rad": _fmt(rng.uniform(-0.0009, 0.0009)), "az_offset_rad": _fmt(rng.uniform(-0.0009, 0.0009))},
    ]


def _validate_public_card(source: Path, card_id: str) -> None:
    required = (source / "config" / "v4_scenario.json", source / "config" / "v4_fiber_config.json", source / "config" / "v4_score_config.json", source / "public" / "targets.csv", source / "public" / "footprint.csv", source / "public" / "v4_night_calendar.csv")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"public {card_id} input is incomplete: {', '.join(missing)}")


def _prepare_card(card_id: str, profile_key: str, rng_key: str, workspace_root: Path, *, public_root: Path | None, environment_type: str, seed: int | None, candidate_profile: Mapping | None = None) -> Path:
    source = _public_root(public_root) / profile_key
    _validate_public_card(source, profile_key)
    output_root = Path(workspace_root).expanduser().resolve()
    destination = output_root / "generated-cards" / card_id
    if destination.exists():
        raise FileExistsError(f"generated card already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    try:
        scenario_path = destination / "config" / "v4_scenario.json"
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        scenario["name"] = f"synthetic-{card_id}"
        scenario["task_card"] = {**scenario.get("task_card", {}), "card_id": card_id, "scenario_slug": f"synthetic-{card_id}", "phase": "local-simulator", "environment_type": environment_type, "base_profile": f"{profile_key}-like"}
        if seed is not None:
            scenario["task_card"]["seed"] = int(seed)
        scenario_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        slots = _slots(destination / "public" / "v4_night_calendar.csv")
        profile = candidate_profile if candidate_profile is not None else (_SEED_PROFILES[profile_key] if seed is not None else _FIXED_PROFILES[profile_key])
        weather = _weather_rows(slots, profile, _rng(profile_key, rng_key, "weather"))
        events = _build_events(slots, profile, _rng(profile_key, rng_key, "events"))
        stress_config = scenario.get("stress", {})
        if stress_config.get("enabled") and environment_type == "seed-generated-synthetic":
            earthquake_id = _add_earthquake_for_stress(slots, events, _rng(profile_key, rng_key, "earthquake"))
            stress_rows = _build_stress_events(earthquake_id, _rng(profile_key, rng_key, "stress"))
            _write_csv(destination / "truth" / "v4_stress_events.csv", _STRESS_FIELDS, stress_rows)
        elif stress_config.get("stress_events_csv"):
            _write_csv(destination / "truth" / "v4_stress_events.csv", _STRESS_FIELDS, [])
        if environment_type == "fixed-synthetic-calibration":
            scenario["stress"] = {**stress_config, "enabled": False}
            scenario_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_csv(destination / "truth" / "v4_slots.csv", _SLOT_FIELDS, slots)
        _write_csv(destination / "truth" / "v4_weather_truth.csv", _WEATHER_FIELDS, weather)
        _write_csv(destination / "truth" / "v4_events.csv", _EVENT_FIELDS, events)
        _write_csv(destination / "truth" / "v4_earthquake_effects.csv", _EARTHQUAKE_FIELDS, _build_earthquake_effects(events, slots))
        _write_jsonl(destination / "public" / "v4_bulletins.jsonl", _build_bulletins(slots, weather, events, _rng(profile_key, rng_key, "bulletins")))
        _write_jsonl(destination / "public" / "v4_forecasts.jsonl", _build_forecasts(slots, events, _rng(profile_key, rng_key, "forecasts")))
        requests = _build_requests(slots, destination / "public" / "targets.csv", destination / "config" / "v4_score_config.json", profile, _rng(profile_key, rng_key, "requests"))
        _write_jsonl(destination / "truth" / "v4_observation_requests.jsonl", requests)
        manifest = {"schema_version": "synthetic-v4-card-v1", "generator_version": GENERATOR_VERSION, "card_id": card_id, "environment_type": environment_type, "base_profile": f"{profile_key}-like", "created_from": "public alpha-delta input bundle", "official_truth": False, "public_catalog_and_calendar_preserved": True}
        if seed is not None:
            manifest["seed"] = int(seed)
        (destination / "simulation_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (destination / "card.md").write_text("# Local synthetic scenario\n\n" + f"- Card ID: {card_id}\n- Base public profile: {profile_key}-like\n- Environment: {environment_type}\n" + "- Weather, events, forecasts, bulletins, and requests are locally synthesized.\n- This card does not contain organizer truth; its score is not an official result.\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def environment_summary(card_path: Path) -> dict:
    """Summarize local truth for the report UI, never for the Agent protocol."""
    _, weather = _read_csv(card_path / "truth" / "v4_weather_truth.csv")
    _, events = _read_csv(card_path / "truth" / "v4_events.csv")
    counts: dict[str, int] = {}
    for event in events:
        kind = event["event_type"]
        counts[kind] = counts.get(kind, 0) + 1
    requests = (card_path / "truth" / "v4_observation_requests.jsonl").read_text(encoding="utf-8").splitlines()
    return {
        "slots": len(weather),
        "open_slots": sum(row["is_observable"].lower() == "true" for row in weather),
        "mean_seeing_arcsec": round(sum(float(row["seeing_arcsec"]) for row in weather) / len(weather), 4),
        "mean_transparency": round(sum(float(row["transparency"]) for row in weather) / len(weather), 4),
        "mean_sky_quality": round(sum(float(row["sky_quality"]) for row in weather) / len(weather), 4),
        "mean_instrument_efficiency": round(sum(float(row["instrument_efficiency"]) for row in weather) / len(weather), 4),
        "events_by_type": counts,
        "request_count": sum(bool(line.strip()) for line in requests),
    }


def prepare_fixed_card(card_id: str, workspace_root: Path, public_root: Path | None = None) -> Path:
    """Load the verified frozen environment; never resample a calibration card."""
    key = _profile_key(card_id)
    if key != str(card_id).strip().lower():
        raise ValueError("fixed calibration card id must be alpha, beta, gamma, or delta")
    frozen = _resource_root() / "simulator" / CALIBRATION_VERSION / key
    manifest = json.loads((frozen / "simulation_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("calibration_id") != f"{key}-calibration-v1" or manifest.get("official_truth") is not False:
        raise ValueError(f"invalid frozen calibration manifest: {key}")
    hashes = manifest.get("sha256", {})
    required = {"config/v4_scenario.json", "config/v4_fiber_config.json", "config/v4_score_config.json", "truth/v4_slots.csv", "truth/v4_weather_truth.csv", "truth/v4_events.csv", "truth/v4_observation_requests.jsonl", "public/targets.csv", "public/footprint.csv", "public/v4_night_calendar.csv", "public/v4_bulletins.jsonl", "public/v4_forecasts.jsonl"}
    if not required.issubset(hashes):
        raise ValueError(f"frozen calibration hashes are incomplete: {key}")
    destination = Path(workspace_root).expanduser().resolve() / "generated-cards" / f"{key}-calibration"
    if destination.exists():
        raise FileExistsError(destination)
    source = _public_root(public_root) / key
    _validate_public_card(source, key)
    shutil.copytree(source, destination)
    try:
        for relative, expected in hashes.items():
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts or path.parts[0] not in {"config", "public", "truth"}:
                raise ValueError("invalid calibration file path")
            overlay = frozen / path
            output = destination / path
            if overlay.is_file():
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(overlay, output)
            if not output.is_file() or hashlib.sha256(output.read_bytes()).hexdigest() != expected:
                raise ValueError(f"frozen calibration hash mismatch: {key}/{relative}")
        shutil.copyfile(frozen / "simulation_manifest.json", destination / "simulation_manifest.json")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def prepare_seed_card(base_profile: str, seed: int, workspace_root: Path, public_root: Path | None = None) -> Path:
    """Create a reproducible seed-generated synthetic environment separate from calibration."""
    key = _profile_key(base_profile)
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    seed_value = int(seed)
    card_id = f"synthetic-{key}-like-seed-{seed_value}"
    return _prepare_card(card_id=card_id, profile_key=key, rng_key=f"seed-{seed_value}", workspace_root=workspace_root, public_root=public_root, environment_type="seed-generated-synthetic", seed=seed_value)
