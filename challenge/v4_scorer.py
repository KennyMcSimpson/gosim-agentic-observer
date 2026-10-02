"""Deterministic local replay engine for the published Agent Observer v4 rules."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from .v4_geometry import (
    FiberConfig,
    Site,
    as_fiber_config,
    as_site,
    altaz_to_radec,
    minimum_altitude_deg,
    radec_to_altaz,
    target_in_fiber_cell,
)
from .v4_protocol import V4ProtocolError, parse_utc


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} contains a non-object JSON line")
            rows.append(value)
    return rows


def _bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _utc(value: object) -> datetime:
    try:
        return parse_utc(value)
    except V4ProtocolError as exc:
        raise ValueError(str(exc)) from exc


def _round(value: float) -> float:
    return round(float(value), 8)


@dataclass(frozen=True)
class V4Target:
    target_id: str
    ra_deg: float
    dec_deg: float
    target_class: str
    feature_flux: float
    science_weight: float
    required: bool

    def public_dict(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
            "target_class": self.target_class,
            "feature_flux": self.feature_flux,
            "science_weight": self.science_weight,
            "required": self.required,
        }


@dataclass(frozen=True)
class V4Night:
    night_id: str
    night_date: str
    observing_start_utc: datetime
    observing_end_utc: datetime

    def public_dict(self) -> dict[str, object]:
        return {
            "night_id": self.night_id,
            "night_date": self.night_date,
            "observing_start_utc": self.observing_start_utc.isoformat(timespec="seconds") + "Z",
            "observing_end_utc": self.observing_end_utc.isoformat(timespec="seconds") + "Z",
        }


class V4Card:
    """Loaded card inputs; truth files are used only by the local scorer."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        config_path = self.root / "config" / "v4_scenario.json"
        self.scenario = _read_json(config_path)
        if self.scenario.get("schema_version") != "v4-scenario-v1":
            raise ValueError("unsupported v4 scenario schema")
        self.site: Site = as_site(self.scenario["site"])
        self.minimum_altitude_deg = float(self.scenario.get("minimum_altitude_deg", 30.0))
        self.fiber_raw = _read_json(self.root / "config" / str(self.scenario.get("fiber_config", "v4_fiber_config.json")))
        self.score_config = _read_json(self.root / "config" / str(self.scenario.get("score_config", "v4_score_config.json")))
        if self.fiber_raw.get("schema_version") != "v4-fiber-map-v1":
            raise ValueError("unsupported v4 fiber map schema")
        if self.score_config.get("schema_version") != "v4-score-v1":
            raise ValueError("unsupported v4 score schema")
        self.fibers: FiberConfig = as_fiber_config(self.fiber_raw)
        products = self.scenario.get("products", {})

        def product(name: str, fallback: str) -> Path:
            configured = products.get(name, fallback)
            return (config_path.parent / configured).resolve()

        target_rows = _read_csv(product("targets_csv", "../public/targets.csv"))
        self.targets: dict[str, V4Target] = {}
        for row in target_rows:
            target = V4Target(
                target_id=row["target_id"],
                ra_deg=float(row["ra_deg"]),
                dec_deg=float(row["dec_deg"]),
                target_class=row.get("target_class", "unknown"),
                feature_flux=float(row["feature_flux"]),
                science_weight=float(row["science_weight"]),
                required=_bool(row.get("required", False)),
            )
            if target.target_id in self.targets:
                raise ValueError(f"duplicate target_id {target.target_id}")
            if target.feature_flux <= 0 or target.science_weight <= 0:
                raise ValueError(f"target {target.target_id} has non-positive score input")
            self.targets[target.target_id] = target

        self.footprint = _read_csv(product("footprint_csv", "../public/footprint.csv"))
        self.nights = [
            V4Night(
                night_id=row["night_id"],
                night_date=row["night_date"],
                observing_start_utc=_utc(row["observing_start_utc"]),
                observing_end_utc=_utc(row["observing_end_utc"]),
            )
            for row in _read_csv(product("night_calendar_csv", "../public/v4_night_calendar.csv"))
        ]
        if not self.nights:
            raise ValueError("v4 card has no observing nights")
        self.bulletins = _read_jsonl(product("bulletins_jsonl", "../public/v4_bulletins.jsonl"))
        self.forecasts = _read_jsonl(product("forecasts_jsonl", "../public/v4_forecasts.jsonl"))
        weather_path = product("weather_truth_csv", "../truth/v4_weather_truth.csv")
        events_path = product("events_csv", "../truth/v4_events.csv")
        self.weather = _read_csv(weather_path) if weather_path.is_file() else []
        self.events = _read_csv(events_path) if events_path.is_file() else []
        self.requests = _read_jsonl(product("observation_requests_jsonl", "../truth/v4_observation_requests.jsonl"))
        self.limit_seconds = float(self.scenario.get("limits", {}).get("global_wallclock_seconds", 900))

    @property
    def first_utc(self) -> datetime:
        return self.nights[0].observing_start_utc

    @property
    def last_utc(self) -> datetime:
        return self.nights[-1].observing_end_utc

    def initial_publication(self) -> dict[str, object]:
        return {
            "schema_version": "initial-publication-v4",
            "site": {
                "name": self.scenario["site"].get("name", "Paranal, Chile (virtual)"),
                "latitude_deg": self.site.latitude_deg,
                "longitude_deg": self.site.longitude_deg,
                "utc_offset_hours": self.site.utc_offset_hours,
                "sun_altitude_limit_deg": self.scenario["site"].get("sun_altitude_limit_deg", -18.0),
            },
            "calendar": {"nights": [night.public_dict() for night in self.nights]},
            "targets": [target.public_dict() for target in self.targets.values()],
            "footprint": self.footprint,
            "fiber_config": self.fiber_raw,
            "scoring": self.score_config,
            "time_limit_seconds": self.limit_seconds,
            "task_card": dict(self.scenario.get("task_card", {})),
        }


class V4Scorer:
    """Apply v4 decisions and produce a replayable score report."""

    def __init__(self, card: V4Card):
        self.card = card
        self.now_utc = card.first_utc
        self.best_factor: dict[str, float] = {}
        self.best_score: dict[str, float] = {}
        self.best_base: dict[str, float] = {}
        self.coverage_targets: defaultdict[int, set[str]] = defaultdict(set)
        self.report_reward = 0.0
        self.false_reports = 0
        self.false_report_allowance_active = False
        self.consecutive_reports = 0
        self.repaired_faults: set[str] = set()
        self.requests_seen: defaultdict[str, set[str]] = defaultdict(set)
        self.request_messages_emitted: set[str] = set()
        self.request_results_emitted: set[str] = set()
        self.last_result: dict[str, object] = {}
        self.last_messages: list[dict[str, object]] = []
        self.action_count = 0

    def _night(self, instant: datetime) -> V4Night | None:
        for night in self.card.nights:
            if night.observing_start_utc <= instant < night.observing_end_utc:
                return night
        return None

    def _next_observing_start(self, instant: datetime) -> datetime | None:
        for night in self.card.nights:
            if night.observing_start_utc > instant:
                return night.observing_start_utc
        return None

    def _truth_row(self, instant: datetime) -> dict[str, str]:
        if not self.card.weather:
            return {}
        selected = None
        for row in self.card.weather:
            timestamp = _utc(row.get("timestamp_utc"))
            if timestamp <= instant:
                selected = row
            else:
                break
        return selected or self.card.weather[0]

    def _quality(self, target: V4Target, instant: datetime) -> tuple[float, str | None]:
        row = self._truth_row(instant)
        score = self.card.score_config
        if "q" in row:
            quality = float(row["q"])
        else:
            quality = float(score.get("q0", 1.0))
            quality *= float(row.get("sky_quality", 1.0))
            quality *= float(row.get("instrument_quality", row.get("instrument_efficiency", 1.0)))
            quality *= float(row.get("transparency", 1.0))
            alt_deg = max(1e-6, radec_to_altaz(target.ra_deg, target.dec_deg, instant, self.card.site)[0])
            airmass = 1.0 / max(1e-6, math.sin(math.radians(alt_deg)))
            quality *= airmass ** -float(score.get("airmass_exponent", 0.0))
        return max(0.0, quality), row.get("sky_band") or row.get("program")

    def _program_multiplier(self, program: str, sky_band: str | None) -> float:
        program_config = self.card.score_config.get("program", {})
        multipliers = program_config.get("multipliers", {})
        if sky_band and program == sky_band:
            return float(multipliers.get(program, 1.0))
        if sky_band:
            return float(program_config.get("mismatch_multiplier", 1.0))
        return float(multipliers.get(program, 1.0))

    def _record_request_targets(
        self,
        target_id: str,
        factor: float,
        start_utc: datetime,
        end_utc: datetime,
    ) -> None:
        threshold = float(self.card.score_config.get("observation_requests", {}).get("completion_factor_threshold", 0.5))
        if factor < threshold:
            return
        for request in self.card.requests:
            request_id = str(request.get("request_id", ""))
            target_ids = set(request.get("target_ids", request.get("targets", [])))
            if target_id not in target_ids:
                continue
            available = _utc(request.get("available_from_utc", request.get("issued_at_utc", "1970-01-01T00:00:00Z")))
            deadline = _utc(request["deadline_utc"])
            if available <= start_utc and end_utc <= deadline:
                self.requests_seen[request_id].add(target_id)

    @staticmethod
    def _public_request(request: Mapping[str, object]) -> dict[str, object]:
        public_keys = {
            "request_id",
            "available_from_utc",
            "issued_at_utc",
            "deadline_utc",
            "required_target_count",
            "required_count",
        }
        row = {key: request[key] for key in public_keys if key in request}
        row["target_ids"] = sorted(request.get("target_ids", request.get("targets", [])))
        return row

    def _apply_observe(self, decision: Mapping[str, object]) -> dict[str, object]:
        night = self._night(self.now_utc)
        if night is None:
            raise V4ProtocolError("observe is only legal during an observing window")
        pointing = decision["pointing"]
        pointing_ra, pointing_dec = altaz_to_radec(
            float(pointing["alt_deg"]), float(pointing["az_deg"]), self.now_utc, self.card.site
        )
        requested_duration = int(decision["duration_seconds"])
        end_utc = min(self.now_utc + timedelta(seconds=requested_duration), night.observing_end_utc)
        actual_duration = max(0.0, (end_utc - self.now_utc).total_seconds())
        if actual_duration <= 0:
            raise V4ProtocolError("observe has no remaining time in the current night")
        hits = []
        total_delta = 0.0
        program = str(decision.get("program", "BACKUP"))
        for fiber_text, target_id in decision["assignments"].items():
            fiber_index = int(fiber_text)
            if not 0 <= fiber_index < self.card.fibers.n_fibers:
                raise V4ProtocolError(f"assignment fibre {fiber_text} is outside the configured map")
            target = self.card.targets.get(str(target_id))
            if target is None:
                raise V4ProtocolError(f"assignment references unknown target {target_id!r}")
            if not target_in_fiber_cell(
                self.card.fibers, pointing_ra, pointing_dec, target.ra_deg, target.dec_deg, fiber_index
            ):
                continue
            min_alt = minimum_altitude_deg(
                target.ra_deg, target.dec_deg, self.now_utc, end_utc, self.card.site
            )
            if min_alt < self.card.minimum_altitude_deg:
                continue
            quality, sky_band = self._quality(target, self.now_utc)
            factor = min(
                target.feature_flux
                * actual_duration
                * quality
                / (
                    float(self.card.score_config.get("flux_zero_point", 0.5))
                    * float(self.card.score_config.get("exposure_zero_point_seconds", 900))
                ),
                1.0,
            )
            multiplier = self._program_multiplier(program, sky_band)
            score = target.science_weight * factor * multiplier
            previous_factor = self.best_factor.get(target.target_id, 0.0)
            if factor > previous_factor:
                self.best_factor[target.target_id] = factor
            if factor >= float(self.card.score_config.get("uniformity", {}).get("observed_factor_threshold", 0.5)):
                band_width = float(self.card.score_config.get("uniformity", {}).get("ra_band_width_deg", 10.0))
                band_index = int((target.ra_deg % 360.0) // band_width)
                self.coverage_targets[band_index].add(target.target_id)
            self._record_request_targets(target.target_id, factor, self.now_utc, end_utc)
            old_score = self.best_score.get(target.target_id, 0.0)
            if score > old_score:
                delta = score - old_score
                self.best_score[target.target_id] = score
                self.best_base[target.target_id] = target.science_weight * factor
                total_delta += delta
            hits.append({
                "target_id": target.target_id,
                "fiber": fiber_index,
                "factor": _round(factor),
                "score": _round(score),
                "altitude_min_deg": _round(min_alt),
            })
        self.now_utc = end_utc
        self.last_result = {
            "action": "observe",
            "actual_duration_seconds": _round(actual_duration),
            "hits": hits,
            "score_delta": _round(total_delta),
        }
        return dict(self.last_result)

    def _apply_wait(self, decision: Mapping[str, object]) -> dict[str, object]:
        if "duration_seconds" in decision:
            end_utc = self.now_utc + timedelta(seconds=int(decision["duration_seconds"]))
        else:
            end_utc = _utc(decision["until_utc"])
        if end_utc <= self.now_utc:
            raise V4ProtocolError("wait target must be later than now_utc")
        self.now_utc = min(end_utc, self.card.last_utc)
        self.last_result = {"action": "wait", "now_utc": self.now_utc.isoformat(timespec="seconds") + "Z"}
        return dict(self.last_result)

    def _apply_report(self) -> dict[str, object]:
        self.consecutive_reports += 1
        reporting = self.card.score_config.get("reporting", {})
        if self.consecutive_reports > int(reporting.get("max_consecutive_reports", 32)):
            raise V4ProtocolError("maximum consecutive report actions exceeded")
        correct = False
        fault_id = None
        for index, row in enumerate(self.card.events):
            kind = row.get("kind", row.get("condition", "Instrument_Failure"))
            if kind not in {"Instrument_Failure", "instrument_failure", "fault"}:
                continue
            candidate_id = str(row.get("event_id") or f"fault-{index}")
            if candidate_id in self.repaired_faults:
                continue
            if _utc(row["actual_start_utc"]) <= self.now_utc < _utc(row["actual_end_utc"]):
                correct = True
                fault_id = candidate_id
                break
        if correct:
            self.report_reward += float(reporting.get("correct_reward", 100))
            self.false_reports = 0
            self.false_report_allowance_active = True
            assert fault_id is not None
            self.repaired_faults.add(fault_id)
            result = {"correct": True, "repaired": True, "score_delta": float(reporting.get("correct_reward", 100))}
        else:
            self.false_reports += 1
            allowance = int(reporting.get("false_report_free_allowance", 2))
            penalty = (
                0.0
                if self.false_report_allowance_active and self.false_reports <= allowance
                else float(reporting.get("false_penalty", -150))
            )
            self.report_reward += penalty
            result = {"correct": False, "repaired": False, "score_delta": penalty}
        self.last_result = {"action": "report", **result}
        self.last_messages.append({"type": "report_result", **result})
        return dict(self.last_result)

    def apply(self, decision: Mapping[str, object]) -> dict[str, object]:
        self.action_count += 1
        action = decision["action"]
        if action == "observe":
            result = self._apply_observe(decision)
            self.consecutive_reports = 0
            return result
        if action == "wait":
            result = self._apply_wait(decision)
            self.consecutive_reports = 0
            return result
        if action == "report":
            return self._apply_report()
        if action == "finish":
            self.last_result = {"action": "finish"}
            return dict(self.last_result)
        raise V4ProtocolError(f"unsupported action {action!r}")

    def active_requests(self) -> list[dict[str, object]]:
        rows = []
        for request in self.card.requests:
            deadline = _utc(request["deadline_utc"])
            available = _utc(request.get("available_from_utc", request.get("issued_at_utc", "1970-01-01T00:00:00Z")))
            if available <= self.now_utc <= deadline:
                row = self._public_request(request)
                row["completed_target_ids"] = sorted(self.requests_seen.get(str(request.get("request_id", "")), set()))
                rows.append(row)
        return rows

    def _refresh_request_messages(self) -> None:
        threshold = float(self.card.score_config.get("observation_requests", {}).get("completion_factor_threshold", 0.5))
        for request in self.card.requests:
            request_id = str(request.get("request_id", ""))
            available = _utc(request.get("available_from_utc", request.get("issued_at_utc", "1970-01-01T00:00:00Z")))
            deadline = _utc(request["deadline_utc"])
            if self.now_utc < available:
                continue
            if request_id not in self.request_messages_emitted:
                message = self._public_request(request)
                message["type"] = "observation_request"
                self.last_messages.append(message)
                self.request_messages_emitted.add(request_id)
            if request_id in self.request_results_emitted:
                continue
            target_ids = set(request.get("target_ids", request.get("targets", [])))
            completed = {
                target_id
                for target_id in self.requests_seen.get(request_id, set())
                if self.best_factor.get(target_id, 0.0) >= threshold
            }
            required_count = int(request.get("required_target_count", request.get("required_count", len(target_ids))))
            completed_ok = len(completed) >= required_count
            expired = self.now_utc > deadline
            if completed_ok or expired:
                reward = float(request.get("completion_reward", request.get("reward", 0.0))) if completed_ok else 0.0
                self.last_messages.append({
                    "type": "observation_request_result",
                    "request_id": request_id,
                    "completed": completed_ok,
                    "completed_target_ids": sorted(completed),
                    "required_target_count": required_count,
                    "score_delta": reward,
                })
                self.request_results_emitted.add(request_id)

    def snapshot(self, sequence: int, remaining_seconds: float) -> dict[str, object]:
        self._refresh_request_messages()
        bulletin = None
        for item in self.card.bulletins:
            issued = item.get("issued_at_utc") or item.get("timestamp_utc")
            if issued and _utc(issued) <= self.now_utc:
                bulletin = item
        forecast = None
        for item in self.card.forecasts:
            issued = item.get("issued_at_utc")
            if issued and _utc(issued) <= self.now_utc:
                forecast = item
        messages = list(self.last_messages)
        self.last_messages = []
        return {
            "schema_version": "decision-snapshot-v4",
            "decision_sequence": int(sequence),
            "now_utc": self.now_utc.isoformat(timespec="seconds") + "Z",
            "latest_bulletin": bulletin,
            "latest_forecast": forecast,
            "new_messages": messages,
            "last_result": self.last_result,
            "active_requests": self.active_requests(),
            "wallclock": {"remaining_seconds": max(0.0, float(remaining_seconds))},
        }

    def _coverage_penalty(self) -> float:
        band_width = float(self.card.score_config.get("uniformity", {}).get("ra_band_width_deg", 10.0))
        band_count = max(1, int(math.ceil(360.0 / band_width)))
        values = [len(self.coverage_targets[index]) for index in range(band_count)]
        if not values or sum(values) <= 0:
            return float(self.card.score_config.get("uniformity", {}).get("weight", 200.0))
        total = sum(values)
        jain = total * total / (len(values) * sum(value * value for value in values))
        weight = float(self.card.score_config.get("uniformity", {}).get("weight", 200.0))
        return weight * (1.0 - jain)

    def finalize(self, termination_reason: str) -> dict[str, object]:
        required_threshold = float(self.card.score_config.get("required", {}).get("observed_factor_threshold", 0.5))
        required_missing = sorted(
            target_id for target_id, target in self.card.targets.items()
            if target.required and self.best_factor.get(target_id, 0.0) < required_threshold
        )
        required_penalty = len(required_missing) * float(self.card.score_config.get("required", {}).get("penalty_per_missing", 50))
        request_rows = []
        request_reward = 0.0
        request_threshold = float(self.card.score_config.get("observation_requests", {}).get("completion_factor_threshold", 0.5))
        for request in self.card.requests:
            request_id = str(request.get("request_id", ""))
            target_ids = set(request.get("target_ids", request.get("targets", [])))
            completed = {target_id for target_id in self.requests_seen.get(request_id, set()) if self.best_factor.get(target_id, 0.0) >= request_threshold}
            required_count = int(request.get("required_target_count", request.get("required_count", len(target_ids))))
            done = len(completed) >= required_count
            reward = float(request.get("completion_reward", request.get("reward", 0.0))) if done else 0.0
            request_reward += reward
            request_rows.append({"request_id": request_id, "completed": done, "completed_target_count": len(completed), "required_target_count": required_count, "reward": reward})
        base_science = sum(self.best_base.values())
        program_bonus = sum(self.best_score.values()) - base_science
        coverage_penalty = self._coverage_penalty()
        total = base_science + program_bonus + request_reward + self.report_reward - required_penalty - coverage_penalty
        return {
            "schema_version": "score-report-v4",
            "termination_reason": termination_reason,
            "score": {
                "total": _round(total),
                "base_science": _round(base_science),
                "program_bonus": _round(program_bonus),
                "request_reward": _round(request_reward),
                "report_reward": _round(self.report_reward),
                "coverage_penalty": _round(coverage_penalty),
                "required_penalty": _round(required_penalty),
                "penalties": _round(required_penalty + coverage_penalty),
            },
            "completion": {
                "targets_observed": len(self.best_score),
                "required_missing": required_missing,
                "best_factors": {key: _round(value) for key, value in sorted(self.best_factor.items())},
            },
            "requests": request_rows,
            "reports": {"false_reports": self.false_reports, "consecutive_reports": self.consecutive_reports},
            "final_cursor": {"now_utc": self.now_utc.isoformat(timespec="seconds") + "Z"},
            "actions": self.action_count,
        }
