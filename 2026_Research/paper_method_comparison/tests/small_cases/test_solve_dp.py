#!/usr/bin/env python3
"""T06 regression tests for the shared SOC-grid dynamic program."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(SRC))
SOLVER_PATH = SRC / "solve_dp.py"
SPEC = importlib.util.spec_from_file_location("solve_dp", SOLVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load solver: {SOLVER_PATH}")
SOLVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SOLVER
SPEC.loader.exec_module(SOLVER)


def load_json(name: str) -> dict:
    with (HERE / name).open(encoding="utf-8") as source:
        return json.load(source)


class DynamicProgramTests(unittest.TestCase):
    GRID_COUNTS = {
        "case_a_waiting.json": 3,
        "case_b_arbitrage.json": 3,
        "case_c_pv_loss.json": 9,
    }

    def test_all_hand_calculated_optima_and_independent_evaluation(self) -> None:
        for case_name, grid_count in self.GRID_COUNTS.items():
            with self.subTest(case=case_name, grid_count=grid_count):
                case = load_json(case_name)
                result = SOLVER.solve_dp(
                    case["problem"], grid_count, case_id=case["case_id"]
                )
                summary = result["summary"]
                expected = case["reported"]
                self.assertEqual(summary["status"], "success", summary["message"])
                self.assertEqual(summary["solver_status"], "optimal")
                self.assertEqual(result["evaluation"]["status"], "pass")
                for field in (
                    "objective_yen",
                    "energy_charge_yen",
                    "basic_charge_yen",
                    "maximum_purchased_power_kW",
                ):
                    self.assertAlmostEqual(summary[field], expected[field], places=6)
                self.assertEqual(summary["soc_grid_point_count"], grid_count)
                self.assertEqual(summary["soc_grid_count"], grid_count)
                self.assertEqual(
                    summary["soc_grid_step_kWh"], summary["soc_grid_spacing_kWh"]
                )
                self.assertGreater(summary["feasible_state_transition_count"], 0)
                self.assertEqual(
                    summary["transition_count"],
                    summary["feasible_state_transition_count"],
                )
                self.assertGreater(summary["expanded_label_transition_count"], 0)
                self.assertGreater(summary["retained_label_count_final_boundary"], 0)
                self.assertEqual(
                    summary["maximum_nondominated_labels"],
                    summary["maximum_retained_labels_per_state"],
                )
                self.assertEqual(summary["initial_compile_time_seconds"], 0.0)
                self.assertEqual(summary["initial_compilation_time_seconds"], 0.0)
                self.assertEqual(
                    summary["initial_compilation_status"], "not_applicable_pure_python"
                )
                self.assertGreaterEqual(summary["transition_preparation_time_seconds"], 0.0)
                self.assertGreaterEqual(summary["solve_time_seconds"], 0.0)
                self.assertEqual(
                    summary["prepared_solve_time_seconds"], summary["solve_time_seconds"]
                )

    def test_peak_and_energy_tradeoff_keeps_two_terminal_labels(self) -> None:
        case = load_json("case_b_arbitrage.json")
        result = SOLVER.solve_dp(case["problem"], 3)
        self.assertEqual(result["summary"]["retained_label_count_terminal_state"], 2)
        self.assertGreaterEqual(result["summary"]["maximum_retained_labels_per_state"], 2)

    def test_grid_must_contain_initial_and_terminal_exactly(self) -> None:
        case = load_json("case_a_waiting.json")
        with self.assertRaisesRegex(SOLVER.EvaluationInputError, "initial_soc_kWh"):
            SOLVER.solve_dp(case["problem"], 4)

    def test_negative_price_is_rejected_for_finite_label_dp(self) -> None:
        case = load_json("case_a_waiting.json")
        case["problem"]["price_yen_per_kWh"][0] = -1.0
        with self.assertRaisesRegex(SOLVER.EvaluationInputError, "nonnegative"):
            SOLVER.solve_dp(case["problem"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
