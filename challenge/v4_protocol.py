"""Validation helpers for the published participant-agent-protocol-v4 contract."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping


PROTOCOL_VERSION = "participant-agent-protocol-v4"
INITIAL_PUBLICATION_VERSION = "initial-publication-v4"
DECISION_SNAPSHOT_VERSION = "decision-snapshot-v4"


class V4ProtocolError(ValueError):
    """Raised when a v4 envelope or decision violates the public contract."""


def _require_exact_keys(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise V4ProtocolError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V4ProtocolError(f"{label} must be a number")
    return float(value)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V4ProtocolError(f"{label} must be an integer")
    return int(value)


def parse_utc(value: object, label: str = "UTC timestamp") -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise V4ProtocolError(f"{label} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1].replace("T", " ")).replace(tzinfo=None)
    except ValueError as exc:
        raise V4ProtocolError(f"{label} is not a valid UTC timestamp") from exc


def parse_platform_message(message: Mapping[str, object]) -> tuple[str, dict]:
    """Validate one platform message and return its type and payload."""
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise V4ProtocolError("unsupported participant protocol_version")
    message_type = message.get("message_type")
    payload = message.get("payload")
    if not isinstance(message_type, str) or not isinstance(payload, dict):
        raise V4ProtocolError("v4 message requires message_type and object payload")
    if message_type == "initialize":
        if payload.get("schema_version") != INITIAL_PUBLICATION_VERSION:
            raise V4ProtocolError("unsupported initial-publication schema_version")
    elif message_type == "decision_request":
        if payload.get("schema_version") != DECISION_SNAPSHOT_VERSION:
            raise V4ProtocolError("unsupported decision-snapshot schema_version")
        sequence = _integer(message.get("decision_sequence"), "decision_sequence")
        if sequence != _integer(payload.get("decision_sequence"), "payload.decision_sequence"):
            raise V4ProtocolError("decision sequence differs between envelope and payload")
    elif message_type == "finish":
        return message_type, payload
    else:
        raise V4ProtocolError(f"unsupported platform message_type {message_type!r}")
    return message_type, payload


def validate_decision_response(sequence: int, response: Mapping[str, object]) -> dict[str, object]:
    """Validate a participant response, rejecting unknown fields like the platform."""
    if not isinstance(response, Mapping):
        raise V4ProtocolError("decision response must be an object")
    common = {"protocol_version", "message_type", "decision_sequence", "action"}
    if response.get("protocol_version") != PROTOCOL_VERSION:
        raise V4ProtocolError("decision response has an unsupported protocol_version")
    if response.get("message_type") != "decision_response":
        raise V4ProtocolError("decision response has an unsupported message_type")
    if _integer(response.get("decision_sequence"), "decision_sequence") != int(sequence):
        raise V4ProtocolError("decision_sequence does not match the request")
    action = response.get("action")
    if action not in {"observe", "wait", "report", "finish"}:
        raise V4ProtocolError(f"unsupported v4 action {action!r}")

    if action == "observe":
        allowed = common | {"pointing", "assignments", "duration_seconds", "program"}
        _require_exact_keys(response, allowed, "observe response")
        pointing = response.get("pointing")
        if not isinstance(pointing, Mapping):
            raise V4ProtocolError("observe.pointing must be an object")
        _require_exact_keys(pointing, {"alt_deg", "az_deg"}, "observe.pointing")
        alt_deg = _number(pointing.get("alt_deg"), "pointing.alt_deg")
        az_deg = _number(pointing.get("az_deg"), "pointing.az_deg")
        if not 0.0 <= alt_deg <= 90.0 or not 0.0 <= az_deg < 360.0:
            raise V4ProtocolError("pointing must have alt_deg in [0, 90] and az_deg in [0, 360)")
        assignments = response.get("assignments")
        if not isinstance(assignments, Mapping):
            raise V4ProtocolError("observe.assignments must be an object")
        normalized_assignments: dict[str, str] = {}
        for fiber, target in assignments.items():
            if not isinstance(fiber, str) or not fiber.isascii() or not fiber.isdigit():
                raise V4ProtocolError("assignment fibre keys must be decimal strings")
            if fiber != "0" and fiber.startswith("0"):
                raise V4ProtocolError("assignment fibre keys must not contain leading zeroes")
            if not isinstance(target, str) or not target:
                raise V4ProtocolError("assignment target ids must be non-empty strings")
            normalized_assignments[fiber] = target
        if len(set(normalized_assignments.values())) != len(normalized_assignments):
            raise V4ProtocolError("a target may be assigned to only one fibre")
        duration = _integer(response.get("duration_seconds"), "duration_seconds")
        if not 60 <= duration <= 3600:
            raise V4ProtocolError("observe.duration_seconds must be in [60, 3600]")
        program = response.get("program", "BACKUP")
        if program not in {"DARK", "BRIGHT", "BACKUP"}:
            raise V4ProtocolError("observe.program must be DARK, BRIGHT or BACKUP")
        return {
            "action": action,
            "pointing": {"alt_deg": alt_deg, "az_deg": az_deg},
            "assignments": normalized_assignments,
            "duration_seconds": duration,
            "program": program,
        }

    if action == "wait":
        allowed = common | {"duration_seconds", "until_utc"}
        _require_exact_keys(response, allowed, "wait response")
        has_duration = "duration_seconds" in response
        has_until = "until_utc" in response
        if has_duration == has_until:
            raise V4ProtocolError("wait requires exactly one of duration_seconds or until_utc")
        if has_duration:
            duration = _integer(response.get("duration_seconds"), "duration_seconds")
            if not 60 <= duration <= 3600:
                raise V4ProtocolError("wait.duration_seconds must be in [60, 3600]")
            return {"action": action, "duration_seconds": duration}
        until_utc = response.get("until_utc")
        parse_utc(until_utc, "wait.until_utc")
        return {"action": action, "until_utc": until_utc}

    _require_exact_keys(response, common, f"{action} response")
    return {"action": action}


def decision_response(sequence: int, decision: Mapping[str, object]) -> dict[str, object]:
    """Wrap a validated participant decision in the v4 response envelope."""
    action = decision.get("action")
    envelope: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "message_type": "decision_response",
        "decision_sequence": int(sequence),
        "action": action,
    }
    if action == "observe":
        envelope.update({
            "pointing": dict(decision["pointing"]),
            "assignments": dict(decision["assignments"]),
            "duration_seconds": int(decision["duration_seconds"]),
            "program": decision.get("program", "BACKUP"),
        })
    elif action == "wait":
        if "duration_seconds" in decision:
            envelope["duration_seconds"] = int(decision["duration_seconds"])
        else:
            envelope["until_utc"] = decision["until_utc"]
    return envelope
