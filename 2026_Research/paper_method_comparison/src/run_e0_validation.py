#!/usr/bin/env python3
"""Run E0 and compare DP, same-grid MILP, and continuous-SOC MILP."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluate_solution import DEFAULT_TOLERANCES
from solve_dp import build_soc_grid, solve_dp
from solve_math_program import solve_math_program


CASES = (
    ("case_a_waiting.json", 3),
    ("case_b_arbitrage.json", 3),
    ("case_c_pv_loss.json", 9),
)
FIELDS = (
    "maximum_purchased_power_kW",
    "energy_charge_yen",
    "basic_charge_yen",
    "objective_yen",
)


def _difference_passes(field: str, difference: float, reference: float) -> tuple[float, bool]:
    if field == "maximum_purchased_power_kW":
        tolerance = DEFAULT_TOLERANCES["power_kW"]
    else:
        tolerance = max(
            DEFAULT_TOLERANCES["cost_absolute_yen"],
            abs(reference) * DEFAULT_TOLERANCES["cost_relative"],
        )
    return tolerance, difference <= tolerance


def run(case_dir: Path) -> dict[str, Any]:
    comparisons = []
    all_passed = True
    for filename, grid_count in CASES:
        case = json.loads((case_dir / filename).read_text(encoding="utf-8"))
        problem = case["problem"]
        case_id = case["case_id"]
        dp = solve_dp(problem, grid_count, case_id=case_id)
        grid_milp = solve_math_program(
            problem, "milp", case_id=case_id, soc_grid_count=grid_count
        )
        continuous_milp = solve_math_program(problem, "milp", case_id=case_id)
        grid, _, _ = build_soc_grid(problem, grid_count)
        grid_membership = {}
        grid_membership_pass = True
        for name, result in (("dp", dp), ("grid_milp", grid_milp)):
            maximum_distance = max(
                min(abs(value - point) for point in grid)
                for value in result["trajectory"]["soc_kWh"]
            )
            passed = maximum_distance <= DEFAULT_TOLERANCES["energy_kWh"]
            grid_membership[name] = {
                "maximum_distance_kWh": maximum_distance,
                "tolerance_kWh": DEFAULT_TOLERANCES["energy_kWh"],
                "status": "pass" if passed else "fail",
            }
            grid_membership_pass = grid_membership_pass and passed
        field_differences = {}
        field_passes = True
        for field in FIELDS:
            difference = abs(dp["summary"][field] - grid_milp["summary"][field])
            tolerance, passed = _difference_passes(
                field, difference, dp["summary"][field]
            )
            field_differences[field] = {
                "absolute_difference": difference,
                "tolerance": tolerance,
                "status": "pass" if passed else "fail",
            }
            field_passes = field_passes and passed
        evaluations_pass = all(
            result["evaluation"] is not None
            and result["evaluation"]["status"] == "pass"
            for result in (dp, grid_milp, continuous_milp)
        )
        statuses_pass = all(
            result["summary"]["status"] == "success"
            for result in (dp, grid_milp, continuous_milp)
        )
        case_passed = (
            field_passes
            and grid_membership_pass
            and evaluations_pass
            and statuses_pass
        )
        all_passed = all_passed and case_passed
        comparisons.append(
            {
                "case_id": case_id,
                "source": filename,
                "soc_grid_count": grid_count,
                "status": "pass" if case_passed else "fail",
                "field_comparison": field_differences,
                "soc_grid_membership": grid_membership,
                "dp": dp,
                "grid_milp": grid_milp,
                "continuous_milp": continuous_milp,
            }
        )
    return {
        "schema_version": 1,
        "experiment_id": "E0_validation",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "pass" if all_passed else "fail",
        "tolerances": DEFAULT_TOLERANCES,
        "comparisons": comparisons,
    }


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-dir", type=Path, default=project / "tests" / "small_cases"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.case_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
