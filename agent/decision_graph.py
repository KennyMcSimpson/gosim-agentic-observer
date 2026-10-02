"""Small acyclic LangGraph for bounded public-snapshot model decisions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Mapping

from anomaly_detection import AnomalyDetector
from scoring_preview import CandidatePreview, preview_actions
from state import DecisionState

try:  # the participant's single-file strategy (optional: the deterministic ranking is used when absent)
    import my_strategy
except Exception as exc:  # noqa: BLE001  (a syntax error in the strategy must not kill the whole run)
    import sys as _sys
    print(f"my_strategy.py could not be imported ({type(exc).__name__}: {exc}); using the default ranking", file=_sys.stderr, flush=True)
    my_strategy = None


SYSTEM_PROMPT = """You choose one telescope action for the current decision only.
Every listed candidate is a legal current start and already uses the public scoring
formula. Return exactly one JSON object with action, tile_id, program, request_id,
and reason. Select only a listed (tile_id, program, request_id) tuple. Do not plan
future slots and do not invent simulator calls or fields."""

PLANNER_PROMPT = """You are the planning stage of a telescope scheduler. Use only the
current public snapshot and the listed legal candidates. Produce one JSON object with
preferred_region_ids (zero or more listed region IDs), priority_request_ids (zero or
more listed request IDs), and reason. Do not invent IDs, inspect future truth, or
choose an action. Keep the lists short."""


def _compact(preview: CandidatePreview, rank: int) -> dict[str, object]:
    return {
        "rank": rank,
        "tile_id": preview.tile_id,
        "program": preview.program,
        "request_id": preview.request_id,
        "region_id": preview.region_id,
        "scheduling_class": preview.scheduling_class,
        "nominal_exptime_seconds": preview.nominal_exptime_seconds,
        "combined_quality": preview.combined_quality,
        "quality_band": preview.quality_band,
        "altitude_deg": preview.altitude_deg,
        "airmass": preview.airmass,
        "target_class_counts": preview.target_class_counts,
        "estimated_science_score": preview.estimated_science_score,
        "terminal_penalty_avoidance": preview.terminal_penalty_avoidance,
        "request_policy_value": preview.request_policy_value,
        "estimated_total_gain": preview.estimated_total_gain,
        "estimated_gain_per_second": preview.estimated_gain_per_second,
        "estimated_overhead_seconds": preview.estimated_overhead_seconds,
        "planning_gain_per_second": preview.planning_gain_per_second,
    }


def _extract_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _parse_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model output contains no JSON object")
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output must be a JSON object")
    return value


def _prepare(state: DecisionState) -> dict[str, object]:
    previews = preview_actions(
        state["snapshot"], state["initial_publication"]["scoring_contract"],
        state.get("tile_best_scores"),
    )
    top = previews[: state["top_k"]]
    return {
        "previews": previews,
        "compact_candidates": [
            _compact(preview, rank)
            for rank, preview in enumerate(top, start=1)
        ],
    }


def _known_plan_ids(state: DecisionState) -> tuple[set[str], set[str]]:
    """Collect IDs that the public publication makes meaningful to a plan.

    A plan can refer to a request or region published for a future window, so the
    validator cannot be limited to the current Top-K candidate rows.  The values
    still come only from the current snapshot or immutable initial publication.
    """
    snapshot = state["snapshot"]
    regions: set[str] = set()
    requests: set[str] = set()

    for candidate in snapshot.get("candidate_tiles", []):
        if isinstance(candidate, Mapping) and candidate.get("region_id"):
            regions.add(str(candidate["region_id"]))
    catalog = (state.get("initial_publication") or {}).get("tile_catalog", {})
    if isinstance(catalog, Mapping):
        for region_id in catalog.get("region_ids", []) or []:
            if isinstance(region_id, str) and region_id:
                regions.add(region_id)
        for tile in catalog.get("tiles", []) or []:
            if isinstance(tile, Mapping) and tile.get("region_id"):
                regions.add(str(tile["region_id"]))

    def collect_window_rows(rows: object) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if isinstance(row, Mapping) and row.get("region_id"):
                regions.add(str(row["region_id"]))

    night_start = snapshot.get("night_start")
    if isinstance(night_start, Mapping):
        collect_window_rows(night_start.get("tile_windows"))
    weekly = snapshot.get("weekly")
    if isinstance(weekly, Mapping):
        collect_window_rows(weekly.get("tile_windows"))

    def collect_request_rows(rows: object) -> None:
        if not isinstance(rows, list):
            return
        for request in rows:
            if isinstance(request, Mapping) and request.get("request_id"):
                requests.add(str(request["request_id"]))

    collect_request_rows(snapshot.get("active_requests"))
    if isinstance(weekly, Mapping):
        collect_request_rows(weekly.get("observation_requests"))
    return regions, requests


def _validated_model_plan(plan: Mapping[str, object], state: DecisionState) -> dict[str, object]:
    """Validate and normalize a planner response before it reaches the selector."""
    required = ("preferred_region_ids", "priority_request_ids")
    for key in required:
        values = plan.get(key)
        if not isinstance(values, list):
            raise ValueError(f"planner field {key} must be a list")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"planner field {key} must contain non-empty strings")

    known_regions, known_requests = _known_plan_ids(state)
    region_values = list(dict.fromkeys(str(value) for value in plan["preferred_region_ids"]))
    request_values = list(dict.fromkeys(str(value) for value in plan["priority_request_ids"]))
    unknown_regions = sorted(set(region_values) - known_regions)
    unknown_requests = sorted(set(request_values) - known_requests)
    if unknown_regions or unknown_requests:
        raise ValueError("planner returned an unpublished region or request ID")
    reason_value = plan.get("reason", "model plan")
    if not isinstance(reason_value, str):
        raise ValueError("planner reason must be a string")
    reason = " ".join(reason_value.split())[:240]
    return {
        "preferred_region_ids": region_values[:8],
        "priority_request_ids": request_values[:8],
        "reason": reason or "model plan",
    }


def _planner_node(state: DecisionState, model: object | None) -> dict[str, object]:
    """Run the first model stage only at the caller's bounded refresh trigger."""
    if model is None or not state.get("allow_model_call"):
        return {"model_plan": None, "model_stage_trace": []}
    candidates = state["compact_candidates"]
    if not candidates:
        return {"model_plan": None, "model_stage_trace": ["planner:skipped-empty"]}
    prompt = json.dumps(
        {
            "cursor": state["snapshot"]["cursor"],
            "night_start": state["snapshot"].get("night_start"),
            "weekly": state["snapshot"].get("weekly"),
            "candidates": candidates,
            "output_schema": {
                "preferred_region_ids": ["listed region_id"],
                "priority_request_ids": ["listed request_id"],
                "reason": "one short sentence",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        plan = _parse_object(_extract_text(model.invoke([("system", PLANNER_PROMPT), ("human", prompt)])))
        normalized = _validated_model_plan(plan, state)
        return {
            "model_plan": normalized,
            "model_stage_trace": ["planner:ok"],
        }
    except Exception as exc:
        return {"model_plan": None, "model_stage_trace": [f"planner:error:{type(exc).__name__}"], "model_error": type(exc).__name__}


def _selector_node(state: DecisionState, model: object | None) -> dict[str, object]:
    """Run the second model stage against the planner output and legal Top-K."""
    candidates = state["compact_candidates"]
    if model is None or not state.get("allow_model_call") or not candidates:
        return {"model_selection": None, "model_stage_trace": state.get("model_stage_trace", [])}
    # A selector response without a validated plan is not an independent action
    # authority.  This preserves deterministic behavior when planning failed.
    stage_trace = list(state.get("model_stage_trace", []))
    if stage_trace and "planner:ok" not in stage_trace:
        stage_trace.append("selector:skipped-planner")
        return {"model_selection": None, "model_stage_trace": stage_trace}
    prompt = json.dumps(
        {
            "decision_sequence": state["snapshot"]["decision_sequence"],
            "cursor": state["snapshot"]["cursor"],
            "planner": state.get("model_plan"),
            "candidates": candidates,
            "output_schema": {
                "action": "observe",
                "tile_id": "one listed tile_id",
                "program": "the listed program",
                "request_id": "the listed request_id, possibly empty",
                "reason": "one short sentence",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        selection = _parse_object(
            _extract_text(model.invoke([("system", SYSTEM_PROMPT), ("human", prompt)]))
        )
        trace = list(state.get("model_stage_trace", []))
        if not _selection_matches_candidates(selection, candidates):
            trace.append("selector:invalid")
            return {"model_selection": None, "model_stage_trace": trace}
        trace.append("selector:ok")
        return {"model_selection": selection, "model_stage_trace": trace}
    except Exception as exc:
        trace = list(state.get("model_stage_trace", []))
        trace.append(f"selector:error:{type(exc).__name__}")
        return {"model_selection": None, "model_stage_trace": trace, "model_error": type(exc).__name__}


def _model_node(state: DecisionState, model: object | None) -> dict[str, object]:
    """Compatibility alias for callers that exercised the old selector node."""
    return _selector_node(state, model)


def _selection_matches_candidates(
    selection: Mapping[str, object] | None,
    candidates: list[Mapping[str, object]],
) -> bool:
    if selection is None or str(selection.get("action")) != "observe":
        return False
    key = (
        str(selection.get("tile_id", "")),
        str(selection.get("program", "")),
        str(selection.get("request_id", "")),
    )
    return any(
        (str(candidate.get("tile_id", "")), str(candidate.get("program", "")), str(candidate.get("request_id", "")))
        == key
        for candidate in candidates
    )


def _validated_model_decision(
    selection: Mapping[str, object] | None,
    previews: list[CandidatePreview],
    top_k: int,
) -> dict[str, object] | None:
    if selection is None or str(selection.get("action")) != "observe":
        return None
    key = (
        str(selection.get("tile_id", "")),
        str(selection.get("program", "")),
        str(selection.get("request_id", "")),
    )
    allowed = {
        (item.tile_id, item.program, item.request_id): item
        for item in previews[:top_k]
    }
    if key not in allowed:
        return None
    reason = " ".join(str(selection.get("reason", "model selection")).split())[:240]
    return {
        "action": "observe",
        "tile_id": key[0],
        "program": key[1],
        "request_id": key[2],
        "reason": reason or "model selection",
        "decision_source": "model",
    }


def _night_distance(current: str, previous: str) -> int | None:
    """Return elapsed observing nights for the standard or compact night IDs."""
    if not current or not previous or current == previous:
        return 0 if current == previous and current else None
    if current.startswith("N") and previous.startswith("N"):
        current_suffix, previous_suffix = current[1:], previous[1:]
        if (
            len(current_suffix) == len(previous_suffix) == 8
            and current_suffix.isdigit()
            and previous_suffix.isdigit()
        ):
            try:
                current_date = datetime.strptime(current_suffix, "%Y%m%d").date()
                previous_date = datetime.strptime(previous_suffix, "%Y%m%d").date()
                return (current_date - previous_date).days
            except ValueError:
                return None
        if current_suffix.isdigit() and previous_suffix.isdigit():
            return int(current_suffix) - int(previous_suffix)
    return None


def _finalize(state: DecisionState) -> dict[str, object]:
    previews = state["previews"]
    selected = _validated_model_decision(
        state.get("model_selection"), previews, state["top_k"]
    )
    if selected is not None:
        return {"decision": selected}
    if not previews:
        return {
            "decision": {
                "action": "wait",
                "tile_id": "",
                "program": "",
                "request_id": "",
                "reason": "no legal observable candidate can finish in its known window",
                "decision_source": "deterministic",
            }
        }
    strategy = _strategy_decision(previews, state)
    if strategy is not None:
        return {"decision": strategy}
    best = previews[0]
    suffix = f" after {state['model_error']}" if state.get("model_error") else ""
    return {
        "decision": {
            "action": "observe",
            "tile_id": best.tile_id,
            "program": best.program,
            "request_id": best.request_id,
            "reason": f"highest public current-snapshot estimate{suffix}",
            "decision_source": "deterministic",
        }
    }


def _strategy_decision(previews: list[CandidatePreview], state: DecisionState) -> dict[str, object] | None:
    """Ask my_strategy.choose_action; anything invalid falls back to the default ranking (logged to stderr)."""
    chooser = getattr(my_strategy, "choose_action", None) if my_strategy is not None else None
    if chooser is None:
        return None
    candidates = [_compact(preview, rank) for rank, preview in enumerate(previews, start=1)]
    allowed = {(c["tile_id"], c["program"], c["request_id"]): c for c in candidates}
    memory = state.setdefault("memory", {})  # type: ignore[typeddict-item]
    try:
        # The scoring contract arrives once, in the initialize message, but a strategy only ever sees the
        # per-decision snapshot — so surface it there. Competition scenarios carry the coverage weight in it.
        snapshot = state["snapshot"]
        contract = (state.get("initial_publication") or {}).get("scoring_contract")
        if contract and "scoring_contract" not in snapshot:
            snapshot = {**snapshot, "scoring_contract": contract, "score_config": contract.get("score_config", {})}
        choice = chooser(candidates, snapshot, memory)
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"my_strategy.choose_action raised {type(exc).__name__}: {exc}; using the default ranking", file=sys.stderr, flush=True)
        return None
    if choice is None:
        return {"action": "wait", "tile_id": "", "program": "", "request_id": "", "reason": "my_strategy chose to wait", "decision_source": "strategy"}
    if isinstance(choice, int) and not isinstance(choice, bool) and 0 <= choice < len(candidates):
        choice = candidates[choice]
    if isinstance(choice, str):
        choice = next((c for c in candidates if c["tile_id"] == choice), None)
    if not isinstance(choice, dict):
        return None
    key = (str(choice.get("tile_id", "")), str(choice.get("program", "")), str(choice.get("request_id", "")))
    if key not in allowed:
        import sys
        print(f"my_strategy returned a candidate that is not legal now ({key}); using the default ranking", file=sys.stderr, flush=True)
        return None
    best = previews[0]
    if key == (best.tile_id, best.program, best.request_id) and not choice.get("reason"):
        return None  # the default strategy agrees with the public ranking: keep the deterministic decision as is
    reason = " ".join(str(choice.get("reason") or "my_strategy choice").split())[:240]
    return {"action": "observe", "tile_id": key[0], "program": key[1], "request_id": key[2], "reason": reason, "decision_source": "strategy"}


class _SequentialGraph:
    def __init__(self, model: object | None) -> None:
        self.model = model

    def invoke(self, state: DecisionState) -> DecisionState:
        state = {**state, **_prepare(state)}
        state = {**state, **_planner_node(state, self.model)}
        state = {**state, **_selector_node(state, self.model)}
        return {**state, **_finalize(state)}


def build_decision_graph(model: object | None):
    """Build LangGraph when installed, otherwise preserve deterministic fallback."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ModuleNotFoundError:
        return _SequentialGraph(model)
    graph = StateGraph(DecisionState)
    graph.add_node("prepare", _prepare)
    graph.add_node("plan", lambda state: _planner_node(state, model))
    graph.add_node("select", lambda state: _selector_node(state, model))
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "plan")
    graph.add_edge("plan", "select")
    graph.add_edge("select", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


class MinimalDecisionAgent:
    """Stateful facade with deterministic legality and bounded model refreshes."""

    def __init__(self, initial_publication: dict, model: object | None, top_k: int, model_refresh_nights: int = 7) -> None:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.initial_publication = initial_publication
        self.model = model
        self.top_k = top_k
        if model_refresh_nights < 1:
            raise ValueError("model_refresh_nights must be positive")
        self.model_refresh_nights = model_refresh_nights
        self.memory: dict = {}  # handed to my_strategy.choose_action on every decision; persists for the run
        self.detector = AnomalyDetector(initial_publication)
        self.graph = build_decision_graph(model)

    def decide(self, snapshot: dict) -> dict[str, object]:
        # Practice scenarios speak the pre-anomaly snapshot: no score feedback, no
        # reports, and a repeat observation would be an invalid duplicate there.
        mechanics = snapshot.get("schema_version") == "decision-snapshot-v3"
        reports = self.detector.process_snapshot(snapshot) if mechanics else []
        if mechanics:
            snapshot = self.detector.filter_fault_scope(snapshot)
        night_id = str((snapshot.get("cursor") or {}).get("night_id", ""))
        last_model_night = str(self.memory.get("last_model_night", ""))
        night_distance = _night_distance(night_id, last_model_night)
        allow_model_call = bool(
            self.model is not None
            and mechanics
            and isinstance(snapshot.get("night_start"), dict)
            and night_id
            and (
                not last_model_night
                or (
                    night_distance is not None
                    and night_distance >= self.model_refresh_nights
                )
            )
        )
        result = self.graph.invoke(
            {
                "initial_publication": self.initial_publication,
                "snapshot": snapshot,
                "top_k": self.top_k,
                "memory": self.memory,
                "tile_best_scores": self.detector.bests if mechanics else None,
                "allow_model_call": allow_model_call,
            }
        )
        if allow_model_call:
            self.memory["last_model_night"] = night_id
            self.memory["model_stage_trace"] = result.get("model_stage_trace", [])
            self.memory["model_plan"] = result.get("model_plan")
            self.memory.setdefault("model_stage_history", []).append(
                list(result.get("model_stage_trace", []))
            )
        decision = result["decision"]
        # When nothing on the board gains anything, spend the slot confirming a
        # suspect tile: a second read separates permanent tags from weather edges.
        suspect = self.detector.top_suspect(result["previews"]) if mechanics else None
        if suspect is not None and (
            not result["previews"] or result["previews"][0].estimated_gain_per_second <= 0
        ):
            decision = {
                "action": "observe", "tile_id": suspect.tile_id, "program": suspect.program,
                "request_id": suspect.request_id,
                "reason": "repeat observation to confirm an anomalous realized-score deviation",
                "decision_source": "detector",
            }
        if mechanics and decision["action"] == "observe":
            row = next(
                (
                    item
                    for item in result["previews"]
                    if (item.tile_id, item.program, item.request_id)
                    == (decision["tile_id"], decision["program"], decision["request_id"])
                ),
                None,
            )
            self.detector.note_observation(
                decision["tile_id"], self.detector.potential_of(row) if row is not None else None,
                under_cold_wave=self.detector.under_cold_wave(snapshot),
            )
        elif mechanics:
            self.detector.note_observation(None, None)
        if reports:
            decision = {**decision, "reports": reports}
        return decision
