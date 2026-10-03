from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from practice_backend import _prepare_stress_card, available_cards, available_modes


class OfficialV4PackagingTests(unittest.TestCase):
    def test_public_cards_are_l1_to_l4_and_have_truth(self) -> None:
        self.assertEqual([item["card_id"] for item in available_cards()], ["L1", "L2", "L3", "L4"])
        for card_id in ("L1", "L2", "L3", "L4"):
            card = ROOT / "vendor" / "gosim-official-v4" / "local-cards" / card_id
            self.assertTrue((card / "config" / "v4_scenario.json").is_file())
            self.assertTrue((card / "truth" / "v4_weather_truth.csv").is_file())

    def test_modes_are_explicit(self) -> None:
        self.assertEqual([item["mode"] for item in available_modes()], ["official-fixed", "stress-seed"])

    def test_stress_seed_changes_hidden_weather_only(self) -> None:
        source = ROOT / "vendor" / "gosim-official-v4" / "local-cards" / "L1"
        with tempfile.TemporaryDirectory() as temporary:
            clone = _prepare_stress_card("L1", 123, Path(temporary))
            self.assertEqual((source / "public" / "targets.csv").read_bytes(), (clone / "public" / "targets.csv").read_bytes())
            self.assertNotEqual((source / "truth" / "v4_weather_truth.csv").read_bytes(), (clone / "truth" / "v4_weather_truth.csv").read_bytes())
            config = json.loads((clone / "config" / "v4_scenario.json").read_text(encoding="utf-8"))
            self.assertEqual(config["task_card"]["local_mode"], "stress-seed")
            self.assertEqual(config["task_card"]["seed"], 123)


if __name__ == "__main__":
    unittest.main()
