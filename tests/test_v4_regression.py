"""Regression coverage for the isolated Agent Observer v4 harness."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from challenge.v4_geometry import (
    altaz_to_radec,
    fiber_center_offset,
    radec_to_altaz,
    target_in_fiber_cell,
)
from challenge.v4_protocol import (
    DECISION_SNAPSHOT_VERSION,
    PROTOCOL_VERSION,
    V4ProtocolError,
    parse_platform_message,
    validate_decision_response,
)
from challenge.v4_scorer import V4Card, V4Scorer, V4Target


CARD_ROOT = ROOT / "scenarios" / "v4-demo"


def observe_response(
    *,
    sequence: int = 0,
    duration_seconds: int = 60,
    assignments: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_type": "decision_response",
        "decision_sequence": sequence,
        "action": "observe",
        "pointing": {"alt_deg": 60.0, "az_deg": 90.0},
        "assignments": assignments or {"0": "V4D0001"},
        "duration_seconds": duration_seconds,
        "program": "BACKUP",
    }


def observe_decision(
    pointing: dict[str, float],
    assignments: dict[str, str],
    duration_seconds: int = 60,
) -> dict[str, object]:
    return {
        "action": "observe",
        "pointing": pointing,
        "assignments": assignments,
        "duration_seconds": duration_seconds,
        "program": "BACKUP",
    }


def pointing_for_cell(card: V4Card, target: V4Target, fiber_index: int) -> tuple[dict[str, float], float, float]:
    """Build an Alt/Az pointing whose target falls in one fiber cell."""
    east_deg, north_deg = fiber_center_offset(card.fibers, fiber_index)
    pointing_ra_deg = (
        target.ra_deg - east_deg / math.cos(math.radians(target.dec_deg))
    ) % 360.0
    pointing_dec_deg = target.dec_deg - north_deg
    alt_deg, az_deg = radec_to_altaz(
        pointing_ra_deg,
        pointing_dec_deg,
        card.first_utc,
        card.site,
    )
    return {"alt_deg": alt_deg, "az_deg": az_deg}, pointing_ra_deg, pointing_dec_deg


def target_at_altitude(card: V4Card, target_id: str, altitude_deg: float) -> V4Target:
    ra_deg, dec_deg = altaz_to_radec(altitude_deg, 180.0, card.first_utc, card.site)
    target = V4Target(
        target_id=target_id,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        target_class="test",
        feature_flux=5.0,
        science_weight=1.0,
        required=False,
    )
    card.targets[target_id] = target
    return target


class V4ProtocolRegressionTests(unittest.TestCase):
    def test_observe_response_unknown_field_is_rejected(self) -> None:
        response = observe_response()
        response["unexpected_field"] = True

        with self.assertRaisesRegex(V4ProtocolError, "unknown fields"):
            validate_decision_response(0, response)

    def test_sequence_mismatch_is_rejected(self) -> None:
        response = observe_response(sequence=1)
        with self.assertRaisesRegex(V4ProtocolError, "does not match"):
            validate_decision_response(0, response)

        request = {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": "decision_request",
            "decision_sequence": 2,
            "payload": {
                "schema_version": DECISION_SNAPSHOT_VERSION,
                "decision_sequence": 1,
            },
        }
        with self.assertRaisesRegex(V4ProtocolError, "differs"):
            parse_platform_message(request)

    def test_observe_duration_accepts_inclusive_bounds_and_rejects_outside(self) -> None:
        for duration_seconds in (60, 3600):
            with self.subTest(duration_seconds=duration_seconds):
                normalized = validate_decision_response(
                    0,
                    observe_response(duration_seconds=duration_seconds),
                )
                self.assertEqual(normalized["duration_seconds"], duration_seconds)

        for duration_seconds in (59, 3601):
            with self.subTest(duration_seconds=duration_seconds):
                with self.assertRaisesRegex(V4ProtocolError, r"in \[60, 3600\]"):
                    validate_decision_response(
                        0,
                        observe_response(duration_seconds=duration_seconds),
                    )

    def test_fibre_alias_with_leading_zero_is_rejected(self) -> None:
        with self.assertRaisesRegex(V4ProtocolError, "leading zeroes"):
            validate_decision_response(
                0,
                observe_response(assignments={"00": "V4D0001"}),
            )


class V4GeometryAndScorerRegressionTests(unittest.TestCase):
    def test_fiber_cell_is_legal_only_for_the_matching_assignment(self) -> None:
        card = V4Card(CARD_ROOT)
        target = card.targets["V4D0001"]
        pointing, pointing_ra_deg, pointing_dec_deg = pointing_for_cell(card, target, 0)

        self.assertTrue(
            target_in_fiber_cell(
                card.fibers,
                pointing_ra_deg,
                pointing_dec_deg,
                target.ra_deg,
                target.dec_deg,
                0,
            )
        )
        self.assertFalse(
            target_in_fiber_cell(
                card.fibers,
                pointing_ra_deg,
                pointing_dec_deg,
                target.ra_deg,
                target.dec_deg,
                1,
            )
        )

        legal_scorer = V4Scorer(card)
        legal_result = legal_scorer.apply(
            observe_decision(pointing, {"0": target.target_id})
        )
        self.assertEqual([hit["target_id"] for hit in legal_result["hits"]], [target.target_id])

        invalid_scorer = V4Scorer(V4Card(CARD_ROOT))
        invalid_result = invalid_scorer.apply(
            observe_decision(pointing, {"1": target.target_id})
        )
        self.assertEqual(invalid_result["hits"], [])
        self.assertNotIn(target.target_id, invalid_scorer.best_factor)

    def test_target_below_30_degrees_is_skipped_and_target_above_it_is_scored(self) -> None:
        low_card = V4Card(CARD_ROOT)
        low_target = target_at_altitude(low_card, "LOW-ALT", 29.0)
        low_pointing, _, _ = pointing_for_cell(low_card, low_target, 0)
        low_scorer = V4Scorer(low_card)
        low_result = low_scorer.apply(
            observe_decision(low_pointing, {"0": low_target.target_id})
        )
        self.assertEqual(low_card.minimum_altitude_deg, 30.0)
        self.assertEqual(low_result["hits"], [])
        self.assertNotIn(low_target.target_id, low_scorer.best_factor)

        high_card = V4Card(CARD_ROOT)
        high_target = target_at_altitude(high_card, "HIGH-ALT", 31.0)
        high_pointing, _, _ = pointing_for_cell(high_card, high_target, 0)
        high_scorer = V4Scorer(high_card)
        high_result = high_scorer.apply(
            observe_decision(high_pointing, {"0": high_target.target_id})
        )
        self.assertEqual(
            [hit["target_id"] for hit in high_result["hits"]],
            [high_target.target_id],
        )
        self.assertGreaterEqual(high_result["hits"][0]["altitude_min_deg"], 30.0)

    def test_report_records_repair_reward_and_message(self) -> None:
        card = V4Card(CARD_ROOT)
        card.events.append(
            {
                "kind": "Instrument_Failure",
                "actual_start_utc": "2026-10-04T00:00:00Z",
                "actual_end_utc": "2026-10-04T00:10:00Z",
            }
        )
        scorer = V4Scorer(card)

        result = scorer.apply({"action": "report"})
        self.assertEqual(result["correct"], True)
        self.assertEqual(result["repaired"], True)
        self.assertEqual(result["score_delta"], 100.0)

        snapshot = scorer.snapshot(0, 10.0)
        self.assertEqual(snapshot["last_result"]["action"], "report")
        self.assertEqual(snapshot["new_messages"][0]["type"], "report_result")
        self.assertEqual(snapshot["new_messages"][0]["correct"], True)
        self.assertEqual(scorer.snapshot(1, 10.0)["new_messages"], [])

        repeated = scorer.apply({"action": "report"})
        self.assertEqual(repeated["correct"], False)
        self.assertEqual(repeated["score_delta"], 0.0)
        self.assertEqual(scorer.apply({"action": "report"})["score_delta"], 0.0)
        self.assertEqual(scorer.apply({"action": "report"})["score_delta"], -150.0)

        report = scorer.finalize("agent_finish")
        self.assertEqual(report["score"]["report_reward"], -50.0)

    def test_initial_false_report_is_not_free_and_request_window_is_complete(self) -> None:
        card = V4Card(CARD_ROOT)
        scorer = V4Scorer(card)
        false_report = scorer.apply({"action": "report"})
        self.assertEqual(false_report["score_delta"], -150.0)

        request_card = V4Card(CARD_ROOT)
        request_card.requests[0]["deadline_utc"] = "2026-10-04T00:00:30Z"
        target = request_card.targets["V4D0001"]
        pointing, _, _ = pointing_for_cell(request_card, target, 0)
        request_scorer = V4Scorer(request_card)
        public_request = request_scorer.active_requests()[0]
        self.assertNotIn("completion_reward", public_request)
        request_scorer.apply(observe_decision(pointing, {"0": target.target_id}, 60))
        self.assertEqual(request_scorer.requests_seen["REQ-DEMO"], set())
        snapshot = request_scorer.snapshot(0, 10.0)
        message_types = [message["type"] for message in snapshot["new_messages"]]
        self.assertIn("observation_request", message_types)
        self.assertIn("observation_request_result", message_types)
        self.assertFalse(snapshot["new_messages"][-1]["completed"])

    def test_finish_is_recorded_without_advancing_simulated_time(self) -> None:
        scorer = V4Scorer(V4Card(CARD_ROOT))
        initial_time = scorer.now_utc

        result = scorer.apply({"action": "finish"})

        self.assertEqual(result, {"action": "finish"})
        self.assertEqual(scorer.now_utc, initial_time)
        report = scorer.finalize("agent_finish")
        self.assertEqual(report["termination_reason"], "agent_finish")
        self.assertEqual(report["actions"], 1)


if __name__ == "__main__":
    unittest.main()
