from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor" / "gosim-official-v4" / "runner"))

from challenge.v4_runner import load_scenario
from simulator.cards import available_fixed_cards, list_base_profiles, prepare_fixed_card, prepare_seed_card


class SyntheticCardTests(unittest.TestCase):
    def test_fixed_calibration_cards_use_public_alpha_delta_inputs(self) -> None:
        self.assertEqual([card["card_id"] for card in available_fixed_cards()], ["alpha", "beta", "gamma", "delta"])
        self.assertEqual([profile["profile_id"] for profile in list_base_profiles()], ["alpha-like", "beta-like", "gamma-like", "delta-like"])
        public_root = ROOT / "vendor" / "public-input"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for card_id in ("alpha", "beta", "gamma", "delta"):
                card = prepare_fixed_card(card_id, root / card_id)
                scenario = load_scenario(card / "config" / "v4_scenario.json")
                self.assertEqual(len(scenario.targets), available_fixed_cards()[("alpha", "beta", "gamma", "delta").index(card_id)]["target_count"])
                self.assertTrue(scenario.slots)
                self.assertFalse(scenario.config["task_card"].get("seed"))
                self.assertEqual(scenario.config["task_card"]["environment_type"], "fixed-synthetic-calibration")
                for filename in ("targets.csv", "footprint.csv", "v4_night_calendar.csv"):
                    source = public_root / card_id / "public" / filename
                    copied = card / "public" / filename
                    self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), hashlib.sha256(copied.read_bytes()).digest())
                self.assertFalse((card / "public" / "v4_weather_truth.csv").exists())
                self.assertTrue((card / "truth" / "v4_weather_truth.csv").is_file())

    def test_seed_cards_are_repeatable_and_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = prepare_seed_card("alpha-like", 42, root / "first")
            same = prepare_seed_card("alpha-like", 42, root / "same")
            other = prepare_seed_card("alpha-like", 43, root / "other")
            file_name = "truth/v4_weather_truth.csv"
            self.assertEqual((first / file_name).read_bytes(), (same / file_name).read_bytes())
            self.assertNotEqual((first / file_name).read_bytes(), (other / file_name).read_bytes())
            self.assertEqual((first / "public/targets.csv").read_bytes(), (same / "public/targets.csv").read_bytes())
            first_manifest = json.loads((first / "simulation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(first_manifest["environment_type"], "seed-generated-synthetic")
            self.assertEqual(first_manifest["seed"], 42)
            self.assertFalse(first_manifest["official_truth"])


if __name__ == "__main__":
    unittest.main()
