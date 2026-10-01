#!/usr/bin/env python3
"""Solve the common EMS model as a reference MILP or diagnostic LP."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyscipopt import Model, quicksum

from evaluate_solution import EvaluationInputError, evaluate_solution
from solve_dp import build_soc_grid


METHODS = ("milp", "lp")
SUCCESSFUL_SOLVER_STATUSES = {"optimal", "gaplimit"}


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationInputError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationInputError(f"{name} must be a finite number")
    return result


def _series(problem: Mapping[str, Any], key: str, length: int | None = None) -> list[float]:
    values = problem.get(key)
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EvaluationInputError(f"problem.{key} must be an array")
    if length is not None and len(values) != length:
        raise EvaluationInputError(
            f"problem.{key} has {len(values)} values; expected {length}"
        )
    result = [_finite_number(value, f"problem.{key}[{index}]") for index, value in enumerate(values)]
    return result


def _validated_problem(problem: Mapping[str, Any]) -> dict[str, Any]:
    """Validate solver inputs and return a numeric copy.

    The independent evaluator remains the authority for solution feasibility.
    This validation prevents malformed data from reaching the solver API.
    """

    load = _series(problem, "load_kW")
    if not load:
        raise EvaluationInputError("problem.load_kW must be a non-empty array")
    interval_count = len(load)
    pv = _series(problem, "pv_available_kW", interval_count)
    price = _series(problem, "price_yen_per_kWh", interval_count)
    if any(value < 0 for value in load):
        raise EvaluationInputError("problem.load_kW must be nonnegative")
    if any(value < 0 for value in pv):
        raise EvaluationInputError("problem.pv_available_kW must be nonnegative")

    scalar_keys = (
        "time_step_hours",
        "battery_capacity_kWh",
        "charge_limit_kW_internal",
        "discharge_limit_kW_internal",
        "charge_efficiency",
        "discharge_efficiency",
        "soc_min_kWh",
        "soc_max_kWh",
        "initial_soc_kWh",
        "terminal_soc_kWh",
        "basic_charge_yen_per_kW",
    )
    normalized = {key: _finite_number(problem.get(key), f"problem.{key}") for key in scalar_keys}
    normalized.update(
        {
            "load_kW": load,
            "pv_available_kW": pv,
            "price_yen_per_kWh": price,
        }
    )
    if normalized["time_step_hours"] <= 0:
        raise EvaluationInputError("problem.time_step_hours must be greater than zero")
    if normalized["battery_capacity_kWh"] <= 0:
        raise EvaluationInputError("problem.battery_capacity_kWh must be greater than zero")
    if normalized["charge_limit_kW_internal"] < 0 or normalized["discharge_limit_kW_internal"] < 0:
        raise EvaluationInputError("battery power limits must be nonnegative")
    for key in ("charge_efficiency", "discharge_efficiency"):
        if not 0 < normalized[key] <= 1:
            raise EvaluationInputError(f"problem.{key} must lie in (0, 1]")
    if not (
        0
        <= normalized["soc_min_kWh"]
        <= normalized["initial_soc_kWh"]
        <= normalized["soc_max_kWh"]
        <= normalized["battery_capacity_kWh"]
    ):
        raise EvaluationInputError("initial SOC and SOC bounds are inconsistent")
    if not normalized["soc_min_kWh"] <= normalized["terminal_soc_kWh"] <= normalized["soc_max_kWh"]:
        raise EvaluationInputError("terminal SOC lies outside the SOC bounds")
    if normalized["basic_charge_yen_per_kW"] < 0:
        raise EvaluationInputError("basic charge coefficient must be nonnegative")
    return normalized


def _clean(value: float, tolerance: float = 1e-9) -> float:
    return 0.0 if abs(value) <= tolerance else float(value)


def solve_math_program(
    problem: Mapping[str, Any],
    method: str = "milp",
    *,
    time_limit_seconds: float = 300.0,
    threads: int = 1,
    relative_mip_gap: float = 0.0,
    display_solver_output: bool = False,
    case_id: str | None = None,
    soc_grid_count: int | None = None,
) -> dict[str, Any]:
    """Build, solve, and independently evaluate the shared mathematical model.

    When ``soc_grid_count`` is supplied, every SOC boundary is constrained to
    the same exact uniform grid used by the DP.  This creates the independent
    grid-MILP reference used in E0; the ordinary MILP remains continuous-SOC.
    """

    method = method.lower()
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be greater than zero")
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ValueError("threads must be a positive integer")
    if relative_mip_gap < 0:
        raise ValueError("relative_mip_gap must be nonnegative")
    if soc_grid_count is not None and method != "milp":
        raise ValueError("soc_grid_count is supported only for method='milp'")

    data = _validated_problem(problem)
    n = len(data["load_kW"])
    dt = data["time_step_hours"]
    charge_limit = data["charge_limit_kW_internal"]
    discharge_limit = data["discharge_limit_kW_internal"]
    eta_charge = data["charge_efficiency"]
    eta_discharge = data["discharge_efficiency"]
    soc_grid: list[float] | None = None
    if soc_grid_count is not None:
        soc_grid, _, _ = build_soc_grid(data, soc_grid_count)

    total_start = time.perf_counter()
    tracemalloc.start()
    model = Model(f"common_ems_{method}")
    if not display_solver_output:
        model.hideOutput()
    model.setRealParam("limits/time", float(time_limit_seconds))
    model.setIntParam("parallel/maxnthreads", threads)
    model.setRealParam("limits/gap", float(relative_mip_gap))

    build_start = time.perf_counter()
    buy = [model.addVar(lb=0.0, name=f"buy[{t}]") for t in range(n)]
    pv_used = [
        model.addVar(lb=0.0, ub=data["pv_available_kW"][t], name=f"pv_used[{t}]")
        for t in range(n)
    ]
    charge = [model.addVar(lb=0.0, ub=charge_limit, name=f"charge[{t}]") for t in range(n)]
    discharge = [
        model.addVar(lb=0.0, ub=discharge_limit, name=f"discharge[{t}]")
        for t in range(n)
    ]
    soc = [
        model.addVar(lb=data["soc_min_kWh"], ub=data["soc_max_kWh"], name=f"soc[{t}]")
        for t in range(n + 1)
    ]
    contract_power = model.addVar(lb=0.0, name="contract_power")
    mode = []
    if method == "milp":
        mode = [model.addVar(vtype="B", name=f"charge_mode[{t}]") for t in range(n)]
    soc_grid_choice = []
    if soc_grid is not None:
        soc_grid_choice = [
            [model.addVar(vtype="B", name=f"soc_grid_choice[{t},{s}]") for s in range(len(soc_grid))]
            for t in range(n + 1)
        ]
        for t in range(n + 1):
            model.addCons(
                quicksum(soc_grid_choice[t]) == 1,
                name=f"soc_grid_one_hot[{t}]",
            )
            model.addCons(
                soc[t]
                == quicksum(soc_grid[s] * soc_grid_choice[t][s] for s in range(len(soc_grid))),
                name=f"soc_grid_value[{t}]",
            )

    model.addCons(soc[0] == data["initial_soc_kWh"], name="initial_soc")
    model.addCons(soc[n] == data["terminal_soc_kWh"], name="terminal_soc")
    for t in range(n):
        model.addCons(
            buy[t] + pv_used[t] + eta_discharge * discharge[t]
            == data["load_kW"][t] + charge[t] / eta_charge,
            name=f"power_balance[{t}]",
        )
        model.addCons(
            soc[t + 1] == soc[t] + dt * (charge[t] - discharge[t]),
            name=f"soc_transition[{t}]",
        )
        model.addCons(contract_power >= buy[t], name=f"contract_epigraph[{t}]")
        if method == "milp":
            model.addCons(charge[t] <= charge_limit * mode[t], name=f"charge_exclusive[{t}]")
            model.addCons(
                discharge[t] <= discharge_limit * (1 - mode[t]),
                name=f"discharge_exclusive[{t}]",
            )

    energy_expression = quicksum(
        data["price_yen_per_kWh"][t] * dt * buy[t] for t in range(n)
    )
    model.setObjective(
        energy_expression + data["basic_charge_yen_per_kW"] * contract_power,
        "minimize",
    )
    model_build_time = time.perf_counter() - build_start

    solve_start = time.perf_counter()
    model.optimize()
    solve_time = time.perf_counter() - solve_start
    solver_status = str(model.getStatus())
    solution_count = model.getNSols()
    _, traced_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    best_bound = _clean(model.getDualbound()) if math.isfinite(model.getDualbound()) else None
    relative_gap = model.getGap() if solution_count > 0 else None
    if relative_gap is not None and not math.isfinite(relative_gap):
        relative_gap = None

    base_summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": case_id,
        "experiment_id": "E0_validation" if case_id else None,
        "method": "grid_milp" if soc_grid is not None else method,
        "status": "failed",
        "objective_yen": None,
        "energy_charge_yen": None,
        "basic_charge_yen": None,
        "maximum_purchased_power_kW": None,
        "contract_equivalent_power_kW": None,
        "maximum_constraint_violation": None,
        "solve_time_seconds": solve_time,
        "total_time_seconds": time.perf_counter() - total_start,
        "peak_memory_mib": traced_peak_bytes / (1024 * 1024),
        "message": "No feasible solution was returned by SCIP.",
        "solver_status": solver_status,
        "best_bound_yen": best_bound,
        "relative_gap": relative_gap,
        "model_build_time_seconds": model_build_time,
        "simultaneous_charge_discharge_count": None,
        "maximum_simultaneous_charge_discharge_kW": None,
        "soc_grid_count": len(soc_grid) if soc_grid is not None else None,
        "soc_grid_step_kWh": soc_grid[1] - soc_grid[0] if soc_grid is not None else None,
    }
    if solution_count == 0:
        return {"summary": base_summary, "trajectory": None, "evaluation": None}

    trajectory = {
        "purchased_power_kW": [_clean(model.getVal(variable)) for variable in buy],
        "pv_used_kW": [_clean(model.getVal(variable)) for variable in pv_used],
        "charge_power_kW_internal": [_clean(model.getVal(variable)) for variable in charge],
        "discharge_power_kW_internal": [_clean(model.getVal(variable)) for variable in discharge],
        "soc_kWh": [_clean(model.getVal(variable)) for variable in soc],
    }
    maximum_purchased = max(trajectory["purchased_power_kW"])
    energy_charge = sum(
        data["price_yen_per_kWh"][t] * trajectory["purchased_power_kW"][t] * dt
        for t in range(n)
    )
    basic_charge = data["basic_charge_yen_per_kW"] * maximum_purchased
    objective = energy_charge + basic_charge
    simultaneous = [
        min(trajectory["charge_power_kW_internal"][t], trajectory["discharge_power_kW_internal"][t])
        for t in range(n)
    ]
    reported = {
        "maximum_purchased_power_kW": maximum_purchased,
        "contract_equivalent_power_kW": maximum_purchased,
        "energy_charge_yen": energy_charge,
        "basic_charge_yen": basic_charge,
        "objective_yen": objective,
    }
    evaluation = evaluate_solution(data, trajectory, reported)
    evaluation_passed = evaluation["status"] == "pass"
    successful_status = solver_status in SUCCESSFUL_SOLVER_STATUSES
    common_status = (
        "success"
        if evaluation_passed and successful_status
        else "time_limit"
        if solver_status == "timelimit"
        else "failed"
    )
    base_summary.update(
        {
            **reported,
            "status": common_status,
            "maximum_constraint_violation": evaluation["maximum_constraint_violation"],
            "message": (
                "SCIP returned a feasible solution and independent evaluation passed."
                if common_status == "success"
                else "SCIP reached the time limit with a feasible independently evaluated solution."
                if common_status == "time_limit" and evaluation_passed
                else "SCIP returned a solution, but independent evaluation failed."
            ),
            "simultaneous_charge_discharge_count": sum(value > 1e-6 for value in simultaneous),
            "maximum_simultaneous_charge_discharge_kW": max(simultaneous, default=0.0),
            "solver_objective_yen": _clean(model.getObjVal()),
            "contract_epigraph_value_kW": _clean(model.getVal(contract_power)),
            "total_time_seconds": time.perf_counter() - total_start,
        }
    )
    return {"summary": base_summary, "trajectory": trajectory, "evaluation": evaluation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="T04 JSON case containing a normalized problem")
    parser.add_argument("--method", choices=METHODS, default="milp")
    parser.add_argument("--time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--relative-mip-gap", type=float, default=0.0)
    parser.add_argument("--show-solver-output", action="store_true")
    parser.add_argument(
        "--soc-grid-count",
        type=int,
        help="constrain every SOC boundary to the exact uniform DP grid (MILP only)",
    )
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()

    with args.case.open(encoding="utf-8") as source:
        case = json.load(source)
    if not isinstance(case, Mapping) or not isinstance(case.get("problem"), Mapping):
        raise EvaluationInputError("case.problem must be an object")
    result = solve_math_program(
        case["problem"],
        args.method,
        time_limit_seconds=args.time_limit_seconds,
        threads=args.threads,
        relative_mip_gap=args.relative_mip_gap,
        display_solver_output=args.show_solver_output,
        case_id=case.get("case_id"),
        soc_grid_count=args.soc_grid_count,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["summary"]["status"] == "success" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EvaluationInputError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
