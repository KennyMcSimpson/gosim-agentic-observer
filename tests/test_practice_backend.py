from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from practice_backend import (
    CALIBRATION_MODE,
    CALIBRATION_REFERENCES,
    SEED_MODE,
    available_cards,
    available_modes,
)


class PracticeBackendCatalogTests(unittest.TestCase):
    def test_modes_keep_calibration_and_seed_separate(self) -> None:
        self.assertEqual([row["mode"] for row in available_modes()], [CALIBRATION_MODE, SEED_MODE])
        self.assertEqual([row["card_id"] for row in available_cards(CALIBRATION_MODE)], ["alpha", "beta", "gamma", "delta"])
        self.assertEqual(
            [row["card_id"] for row in available_cards(SEED_MODE)],
            ["synthetic-alpha-like", "synthetic-beta-like", "synthetic-gamma-like", "synthetic-delta-like"],
        )

    def test_calibration_metadata_uses_screenshot_reference_values(self) -> None:
        cards = {row["card_id"]: row for row in available_cards(CALIBRATION_MODE)}
        public_root = ROOT / "vendor" / "public-input"
        for card_id, reference in CALIBRATION_REFERENCES.items():
            self.assertEqual(cards[card_id]["frozen_baseline_score"], reference["frozen_baseline_score"])
            self.assertEqual(cards[card_id]["high_score"], reference["high_score"])
            self.assertEqual(cards[card_id]["source"], "synthetic-fixed-calibration")
            card_root = public_root / card_id
            self.assertTrue((card_root / "public" / "targets.csv").is_file())
            self.assertTrue((card_root / "public" / "v4_night_calendar.csv").is_file())
            self.assertFalse((card_root / "truth").exists())

    def test_seed_profiles_do_not_inherit_screenshot_scores(self) -> None:
        for card in available_cards(SEED_MODE):
            self.assertEqual(card["source"], "synthetic-seed-profile")
            self.assertNotIn("frozen_baseline_score", card)
            self.assertNotIn("high_score", card)


if __name__ == "__main__":
    unittest.main()
