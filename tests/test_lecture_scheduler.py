from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from lecture_scheduler import choose_action, estimate_overhead_seconds, planning_score  # noqa: E402


class LectureSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = {
            "cursor": {"timestamp_utc": "2026-09-08T03:00:00Z"},
            "current_site_weather": {"is_observable": True},
            "scoring_contract": {
                "planning_contract": {
                    "pointing_overhead_seconds": 30.0,
                    "readout_overhead_seconds": 15.0,
                    "slew_seconds_per_degree": 0.0,
                    "minimum_altitude_deg": 30.0,
                }
            },
        }

    def candidate(self, **updates):
        value = {
            "tile_id": "T00001",
            "program": "DARK",
            "request_id": "",
            "estimated_total_gain": 100.0,
            "nominal_exptime_seconds": 450,
            "combined_quality": 0.8,
            "altitude_deg": 60.0,
            "airmass": 1.15,
            "target_class_counts": {"ELG": 80, "LRG": 40, "BGS": 10},
            "window_end_utc": "2026-09-08T06:00:00Z",
        }
        value.update(updates)
        return value

    def test_overhead_is_explicit_but_planning_only(self):
        candidate = self.candidate()
        self.assertEqual(estimate_overhead_seconds(candidate, self.snapshot), 45.0)
        self.assertLess(planning_score(candidate, self.snapshot), 100.0 / 450.0)

    def test_shorter_exposure_can_win_on_effective_throughput(self):
        long = self.candidate(tile_id="LONG", estimated_total_gain=180.0, nominal_exptime_seconds=1800)
        short = self.candidate(tile_id="SHORT", estimated_total_gain=100.0, nominal_exptime_seconds=450)
        choice = choose_action([long, short], self.snapshot, {})
        self.assertIsNotNone(choice)
        self.assertEqual(choice["tile_id"], "SHORT")

    def test_unobservable_site_waits(self):
        snapshot = {**self.snapshot, "current_site_weather": {"is_observable": False}}
        self.assertIsNone(choose_action([self.candidate()], snapshot, {}))

    def test_altitude_and_airmass_break_a_tie(self):
        low = self.candidate(tile_id="LOW", altitude_deg=35.0, airmass=1.9)
        high = self.candidate(tile_id="HIGH", altitude_deg=70.0, airmass=1.05)
        choice = choose_action([low, high], self.snapshot, {})
        self.assertIsNotNone(choice)
        self.assertEqual(choice["tile_id"], "HIGH")


if __name__ == "__main__":
    unittest.main()
