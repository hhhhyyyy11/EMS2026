#!/usr/bin/env python3
"""T07 regression tests for the same-grid DP/MILP comparison."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(SRC))
RUNNER_PATH = SRC / "run_e0_validation.py"
SPEC = importlib.util.spec_from_file_location("run_e0_validation", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load E0 runner: {RUNNER_PATH}")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class E0ValidationTests(unittest.TestCase):
    def test_dp_and_grid_milp_match_within_common_tolerances(self) -> None:
        result = RUNNER.run(HERE)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["comparisons"]), 3)
        for comparison in result["comparisons"]:
            with self.subTest(case=comparison["case_id"]):
                self.assertEqual(comparison["status"], "pass")
                self.assertEqual(comparison["dp"]["evaluation"]["status"], "pass")
                self.assertEqual(
                    comparison["grid_milp"]["evaluation"]["status"], "pass"
                )
                self.assertEqual(
                    comparison["continuous_milp"]["evaluation"]["status"], "pass"
                )
                self.assertEqual(
                    comparison["grid_milp"]["summary"]["method"], "grid_milp"
                )
                for details in comparison["field_comparison"].values():
                    self.assertEqual(details["status"], "pass")
                for details in comparison["soc_grid_membership"].values():
                    self.assertEqual(details["status"], "pass")

    def test_grid_constraint_is_rejected_for_lp(self) -> None:
        case = __import__("json").loads(
            (HERE / "case_a_waiting.json").read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(ValueError, "only for method='milp'"):
            RUNNER.solve_math_program(case["problem"], "lp", soc_grid_count=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
