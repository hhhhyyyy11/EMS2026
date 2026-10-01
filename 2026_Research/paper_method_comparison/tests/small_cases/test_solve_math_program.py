#!/usr/bin/env python3
"""T05 regression tests for the shared MILP and diagnostic LP."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(SRC))
SOLVER_PATH = SRC / "solve_math_program.py"
SPEC = importlib.util.spec_from_file_location("solve_math_program", SOLVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load solver: {SOLVER_PATH}")
SOLVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOLVER)


def load_json(name: str) -> dict:
    with (HERE / name).open(encoding="utf-8") as source:
        return json.load(source)


class MathProgramTests(unittest.TestCase):
    def test_milp_and_lp_match_all_hand_calculated_optima(self) -> None:
        for case_name in (
            "case_a_waiting.json",
            "case_b_arbitrage.json",
            "case_c_pv_loss.json",
        ):
            case = load_json(case_name)
            for method in SOLVER.METHODS:
                with self.subTest(case=case_name, method=method):
                    result = SOLVER.solve_math_program(
                        case["problem"], method, case_id=case["case_id"]
                    )
                    summary = result["summary"]
                    expected = case["reported"]
                    self.assertEqual(summary["status"], "success", summary["message"])
                    self.assertEqual(summary["solver_status"], "optimal")
                    self.assertEqual(result["evaluation"]["status"], "pass")
                    self.assertAlmostEqual(summary["objective_yen"], expected["objective_yen"], places=6)
                    self.assertAlmostEqual(
                        summary["energy_charge_yen"], expected["energy_charge_yen"], places=6
                    )
                    self.assertAlmostEqual(
                        summary["basic_charge_yen"], expected["basic_charge_yen"], places=6
                    )
                    self.assertAlmostEqual(
                        summary["maximum_purchased_power_kW"],
                        expected["maximum_purchased_power_kW"],
                        places=6,
                    )
                    self.assertAlmostEqual(summary["best_bound_yen"], expected["objective_yen"], places=6)
                    self.assertAlmostEqual(summary["relative_gap"], 0.0, places=12)
                    self.assertEqual(summary["simultaneous_charge_discharge_count"], 0)

    def test_milp_contains_binary_modes_while_lp_is_continuous(self) -> None:
        case = load_json("case_b_arbitrage.json")
        milp = SOLVER.solve_math_program(case["problem"], "milp")
        lp = SOLVER.solve_math_program(case["problem"], "lp")
        self.assertAlmostEqual(milp["summary"]["objective_yen"], lp["summary"]["objective_yen"])
        self.assertEqual(milp["summary"]["simultaneous_charge_discharge_count"], 0)
        self.assertEqual(lp["summary"]["simultaneous_charge_discharge_count"], 0)

    def test_invalid_method_is_rejected(self) -> None:
        case = load_json("case_a_waiting.json")
        with self.assertRaises(ValueError):
            SOLVER.solve_math_program(case["problem"], "not-a-method")


if __name__ == "__main__":
    unittest.main(verbosity=2)
