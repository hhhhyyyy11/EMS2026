#!/usr/bin/env python3
"""Regression tests and hand-calculation checks for T04."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
EVALUATOR_PATH = HERE.parents[1] / "src" / "evaluate_solution.py"
SPEC = importlib.util.spec_from_file_location("evaluate_solution", EVALUATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load evaluator: {EVALUATOR_PATH}")
EVALUATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATOR)


def load_json(name: str) -> dict:
    with (HERE / name).open(encoding="utf-8") as source:
        return json.load(source)


def set_path(document: dict, path: list, value: float) -> None:
    target = document
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value


class SmallCaseTests(unittest.TestCase):
    def assert_passes(self, case_name: str) -> dict:
        result = EVALUATOR.evaluate_case(load_json(case_name))
        self.assertEqual(result["status"], "pass", result["violations"])
        self.assertEqual(result["violations"], [])
        return result

    def test_case_a_waiting_hand_calculation(self) -> None:
        result = self.assert_passes("case_a_waiting.json")
        self.assertAlmostEqual(result["recomputed"]["energy_charge_yen"], 30.0)
        self.assertAlmostEqual(result["recomputed"]["basic_charge_yen"], 8.0)
        self.assertAlmostEqual(result["recomputed"]["objective_yen"], 38.0)

    def test_case_b_arbitrage_hand_calculation(self) -> None:
        case = load_json("case_b_arbitrage.json")
        result = EVALUATOR.evaluate_case(case)
        self.assertEqual(result["status"], "pass", result["violations"])
        self.assertAlmostEqual(result["recomputed"]["maximum_purchased_power_kW"], 2.0)
        self.assertAlmostEqual(result["recomputed"]["energy_charge_yen"], 20.0)
        self.assertAlmostEqual(result["recomputed"]["basic_charge_yen"], 10.0)
        self.assertAlmostEqual(result["recomputed"]["objective_yen"], 30.0)
        self.assertLess(result["recomputed"]["objective_yen"], case["comparison"]["waiting_objective_yen"])

    def test_case_c_pv_loss_hand_calculation(self) -> None:
        case = load_json("case_c_pv_loss.json")
        result = EVALUATOR.evaluate_case(case)
        self.assertEqual(result["status"], "pass", result["violations"])
        hand = case["hand_calculation"]
        self.assertAlmostEqual(
            hand["pv_input_to_battery_kWh"] - hand["energy_delivered_to_load_kWh"],
            hand["round_trip_loss_kWh"],
        )
        self.assertAlmostEqual(result["recomputed"]["objective_yen"], 0.0)
        self.assertLess(result["recomputed"]["objective_yen"], hand["waiting_objective_yen"])

    def test_case_d_detects_every_intentional_break(self) -> None:
        base = load_json("case_b_arbitrage.json")
        specification = load_json("case_d_invalid_examples.json")
        for mutation in specification["mutations"]:
            with self.subTest(mutation=mutation["name"]):
                invalid = copy.deepcopy(base)
                set_path(invalid, mutation["path"], mutation["value"])
                result = EVALUATOR.evaluate_case(invalid)
                detected = {violation["check"] for violation in result["violations"]}
                self.assertEqual(result["status"], "fail")
                self.assertIn(mutation["expected_check"], detected)

    def test_documented_tolerances_are_applied(self) -> None:
        case = load_json("case_a_waiting.json")
        case["trajectory"]["purchased_power_kW"][0] += 0.5e-6
        case["reported"]["maximum_purchased_power_kW"] += 0.5e-6
        case["reported"]["contract_equivalent_power_kW"] += 0.5e-6
        case["reported"]["energy_charge_yen"] += 0.0000025
        case["reported"]["basic_charge_yen"] += 0.000002
        case["reported"]["objective_yen"] += 0.0000045
        result = EVALUATOR.evaluate_case(case)
        self.assertEqual(result["status"], "pass", result["violations"])
        self.assertEqual(result["tolerances"], EVALUATOR.DEFAULT_TOLERANCES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
