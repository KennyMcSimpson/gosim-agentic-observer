"""Lecture-informed, deterministic scheduling heuristics.

The official public scorer remains the source of truth for score calculation.
This module only ranks the already-legal candidates handed to the agent. It
turns the lecture's operational lessons into a transparent planning policy:
account for setup/readout overhead, prefer high-altitude observations, and
match target mix to current observing quality without bypassing scorer rules.
"""

from __future__ import annotations

from datetime import datetime
import math
from typing import Mapping, Sequence


POLICY_VERSION = "lecture-aware-v1"
DEFAULT_PLANNING_CONTRACT = {
    "pointing_overhead_seconds": 30.0,
    "readout_overhead_seconds": 15.0,
    "slew_seconds_per_degree": 0.0,
}


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _planning_contract(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    scoring_contract = snapshot.get("scoring_contract")
    if isinstance(scoring_contract, Mapping):
        contract = scoring_contract.get("planning_contract")
        if isinstance(contract, Mapping):
            return contract
    return DEFAULT_PLANNING_CONTRACT


def estimate_overhead_seconds(
    candidate: Mapping[str, object], snapshot: Mapping[str, object]
) -> float:
    """Estimate non-exposure time for planning only.

    The public v3 scorer does not charge this estimate as a new score term. It
    prevents the selector from treating a long exposure as free of pointing
    and readout costs while keeping replay compatibility with the official
    scorer.
    """
    contract = _planning_contract(snapshot)
    pointing = _number(
        contract.get("pointing_overhead_seconds"),
        DEFAULT_PLANNING_CONTRACT["pointing_overhead_seconds"],
    )
    readout = _number(
        contract.get("readout_overhead_seconds"),
        DEFAULT_PLANNING_CONTRACT["readout_overhead_seconds"],
    )
    slew_rate = _number(
        contract.get("slew_seconds_per_degree"),
        DEFAULT_PLANNING_CONTRACT["slew_seconds_per_degree"],
    )
    slew_distance = max(0.0, _number(candidate.get("slew_distance_deg")))
    return max(0.0, pointing) + max(0.0, readout) + max(0.0, slew_rate) * slew_distance


def _target_condition_factor(
    candidate: Mapping[str, object], combined_quality: float
) -> float:
    """Small, bounded preference for target classes suited to current quality."""
    counts = candidate.get("target_class_counts", {})
    if not isinstance(counts, Mapping):
        return 1.0
    dark_targets = sum(
        max(0, int(_number(counts.get(name)))) for name in ("ELG", "LRG", "QSO")
    )
    bright_targets = sum(
        max(0, int(_number(counts.get(name)))) for name in ("BGS", "STAR")
    )
    total = dark_targets + bright_targets
    if total <= 0:
        return 1.0
    preferred = dark_targets if combined_quality >= 0.65 else bright_targets
    return 1.0 + min(0.04, 0.04 * preferred / total)


def planning_score(candidate: Mapping[str, object], snapshot: Mapping[str, object]) -> float:
    """Return a deterministic planning score; this is not an official score."""
    total_gain = _number(candidate.get("estimated_total_gain"))
    exposure = max(1.0, _number(candidate.get("nominal_exptime_seconds"), 1.0))
    overhead = max(0.0, _number(candidate.get("estimated_overhead_seconds")))
    if overhead <= 0.0:
        overhead = estimate_overhead_seconds(candidate, snapshot)
    score = total_gain / (exposure + overhead)

    combined_quality = max(0.0, _number(candidate.get("combined_quality")))
    score *= _target_condition_factor(candidate, combined_quality)

    altitude = _number(candidate.get("altitude_deg"), 90.0)
    minimum_altitude = _number(
        _planning_contract(snapshot).get("minimum_altitude_deg"), 30.0
    )
    if altitude < minimum_altitude + 5.0:
        score *= 0.96
    elif altitude >= 60.0:
        score *= 1.02

    airmass = max(1.0, _number(candidate.get("airmass"), 1.0))
    score *= max(0.94, 1.0 - 0.015 * (airmass - 1.0))

    cursor = snapshot.get("cursor")
    cursor_time = _parse_utc(cursor.get("timestamp_utc")) if isinstance(cursor, Mapping) else None
    window_end = _parse_utc(candidate.get("window_end_utc"))
    if cursor_time is not None and window_end is not None:
        slack = (window_end - cursor_time).total_seconds() - exposure - overhead
        if 0.0 <= slack <= 300.0:
            score *= 1.05
    return score


def rank_candidates(
    candidates: Sequence[Mapping[str, object]], snapshot: Mapping[str, object]
) -> list[Mapping[str, object]]:
    """Rank candidates with stable tie-breaking and no mutation."""
    return sorted(
        candidates,
        key=lambda candidate: (
            -planning_score(candidate, snapshot),
            -_number(candidate.get("estimated_total_gain")),
            str(candidate.get("tile_id", "")),
            str(candidate.get("request_id", "")),
            str(candidate.get("program", "")),
        ),
    )


def choose_action(
    candidates: Sequence[Mapping[str, object]],
    snapshot: Mapping[str, object],
    memory: dict[str, object],
) -> Mapping[str, object] | None:
    """Choose one legal candidate or wait when the site is not observable."""
    weather = snapshot.get("current_site_weather")
    if isinstance(weather, Mapping) and weather.get("is_observable") is False:
        return None
    if not candidates:
        return None

    ranked = rank_candidates(candidates, snapshot)
    choice = dict(ranked[0])
    overhead = max(0.0, _number(choice.get("estimated_overhead_seconds")))
    if overhead <= 0.0:
        overhead = estimate_overhead_seconds(choice, snapshot)
    score = planning_score(choice, snapshot)
    memory["last_policy"] = POLICY_VERSION
    memory["last_tile_id"] = str(choice.get("tile_id", ""))
    memory["last_planning_score"] = round(score, 9)
    memory["last_overhead_seconds"] = round(overhead, 3)
    choice["reason"] = (
        f"{POLICY_VERSION}: gain per exposure-plus-overhead second, "
        f"using altitude/airmass and target-condition fit; overhead={overhead:g}s"
    )
    return choice
