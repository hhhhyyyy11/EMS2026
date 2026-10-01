#!/usr/bin/env python3
"""Solve the common EMS model on an exact, uniformly spaced SOC grid."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluate_solution import EvaluationInputError, evaluate_solution


NUMERIC_TOLERANCE = 1e-9


@dataclass(slots=True)
class Label:
    """One nondominated partial path ending at a particular SOC state."""

    peak_kW: float
    energy_charge_yen: float
    previous: Label | None
    previous_state: int | None
    state: int
    purchased_power_kW: float
    pv_used_kW: float
    charge_power_kW_internal: float
    discharge_power_kW_internal: float


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
    return [
        _finite_number(value, f"problem.{key}[{index}]")
        for index, value in enumerate(values)
    ]


def _validated_problem(problem: Mapping[str, Any]) -> dict[str, Any]:
    load = _series(problem, "load_kW")
    if not load:
        raise EvaluationInputError("problem.load_kW must be a non-empty array")
    n = len(load)
    pv = _series(problem, "pv_available_kW", n)
    price = _series(problem, "price_yen_per_kWh", n)
    if any(value < 0 for value in load):
        raise EvaluationInputError("problem.load_kW must be nonnegative")
    if any(value < 0 for value in pv):
        raise EvaluationInputError("problem.pv_available_kW must be nonnegative")
    # The study fixes a positive retail tariff. With a negative tariff, PV
    # curtailment creates a continuous peak/cost frontier rather than the
    # finite two-value labels implemented for this study.
    if any(value < 0 for value in price):
        raise EvaluationInputError("problem.price_yen_per_kWh must be nonnegative for this DP")

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
    data = {key: _finite_number(problem.get(key), f"problem.{key}") for key in scalar_keys}
    data.update(
        {
            "load_kW": load,
            "pv_available_kW": pv,
            "price_yen_per_kWh": price,
        }
    )
    if data["time_step_hours"] <= 0:
        raise EvaluationInputError("problem.time_step_hours must be greater than zero")
    if data["battery_capacity_kWh"] <= 0:
        raise EvaluationInputError("problem.battery_capacity_kWh must be greater than zero")
    if data["charge_limit_kW_internal"] < 0 or data["discharge_limit_kW_internal"] < 0:
        raise EvaluationInputError("battery power limits must be nonnegative")
    for key in ("charge_efficiency", "discharge_efficiency"):
        if not 0 < data[key] <= 1:
            raise EvaluationInputError(f"problem.{key} must lie in (0, 1]")
    if not (
        0
        <= data["soc_min_kWh"]
        <= data["initial_soc_kWh"]
        <= data["soc_max_kWh"]
        <= data["battery_capacity_kWh"]
    ):
        raise EvaluationInputError("initial SOC and SOC bounds are inconsistent")
    if not data["soc_min_kWh"] <= data["terminal_soc_kWh"] <= data["soc_max_kWh"]:
        raise EvaluationInputError("terminal SOC lies outside the SOC bounds")
    if data["basic_charge_yen_per_kW"] < 0:
        raise EvaluationInputError("basic charge coefficient must be nonnegative")
    return data


def _grid_index(grid: Sequence[float], value: float, name: str) -> int:
    scale = max(1.0, max(abs(point) for point in grid), abs(value))
    tolerance = NUMERIC_TOLERANCE * scale
    matches = [index for index, point in enumerate(grid) if abs(point - value) <= tolerance]
    if len(matches) != 1:
        raise EvaluationInputError(
            f"{name}={value} kWh is not exactly represented by the SOC grid"
        )
    return matches[0]


def build_soc_grid(data: Mapping[str, Any], soc_grid_count: int) -> tuple[list[float], int, int]:
    """Build a uniform grid and require exact initial and terminal states."""

    if isinstance(soc_grid_count, bool) or not isinstance(soc_grid_count, int):
        raise EvaluationInputError("soc_grid_count must be an integer")
    if soc_grid_count < 2:
        raise EvaluationInputError("soc_grid_count must be at least 2")
    lower = float(data["soc_min_kWh"])
    upper = float(data["soc_max_kWh"])
    if upper <= lower:
        raise EvaluationInputError("SOC grid requires soc_max_kWh greater than soc_min_kWh")
    spacing = (upper - lower) / (soc_grid_count - 1)
    grid = [lower + index * spacing for index in range(soc_grid_count)]
    grid[0] = lower
    grid[-1] = upper
    initial_index = _grid_index(grid, float(data["initial_soc_kWh"]), "initial_soc_kWh")
    terminal_index = _grid_index(grid, float(data["terminal_soc_kWh"]), "terminal_soc_kWh")
    # Store the specified boundary values, not a rounded approximation.
    grid[initial_index] = float(data["initial_soc_kWh"])
    grid[terminal_index] = float(data["terminal_soc_kWh"])
    return grid, initial_index, terminal_index


def _battery_edge(
    data: Mapping[str, Any], current_soc: float, next_soc: float
) -> tuple[float, float] | None:
    """Return internal charge/discharge for a power-feasible grid edge."""

    dt = float(data["time_step_hours"])
    delta = next_soc - current_soc
    if delta >= 0:
        charge = delta / dt
        discharge = 0.0
    else:
        charge = 0.0
        discharge = -delta / dt
    if charge > float(data["charge_limit_kW_internal"]) + NUMERIC_TOLERANCE:
        return None
    if discharge > float(data["discharge_limit_kW_internal"]) + NUMERIC_TOLERANCE:
        return None
    return charge, discharge


def _dispatch_for_edge(
    data: Mapping[str, Any], t: int, charge: float, discharge: float
) -> tuple[float, float] | None:
    """Return purchased power and PV use, or reject an excessive discharge."""

    residual = (
        float(data["load_kW"][t])
        + charge / float(data["charge_efficiency"])
        - float(data["discharge_efficiency"]) * discharge
    )
    # With no export or dump variable, excessive discharge is infeasible.
    if residual < -NUMERIC_TOLERANCE:
        return None
    residual = max(0.0, residual)
    pv_used = min(float(data["pv_available_kW"][t]), residual)
    purchased = max(0.0, residual - pv_used)
    return purchased, pv_used


def _pareto_prune(labels: list[Label]) -> list[Label]:
    """Keep only labels not dominated in both peak and energy charge."""

    labels.sort(key=lambda label: (label.peak_kW, label.energy_charge_yen))
    kept: list[Label] = []
    best_energy = math.inf
    for label in labels:
        # Earlier labels have no larger peak. Equal energy is therefore
        # dominated by the earlier (lower/equal peak) label.
        if label.energy_charge_yen < best_energy - NUMERIC_TOLERANCE:
            kept.append(label)
            best_energy = label.energy_charge_yen
    return kept


def _failure_result(
    *,
    case_id: str | None,
    status: str,
    message: str,
    total_start: float,
    solve_time: float,
    preparation_time: float,
    soc_grid_count: int,
    soc_grid_spacing: float,
    peak_memory_bytes: int,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    summary = {
        "schema_version": 1,
        "run_id": case_id,
        "experiment_id": "E0_validation" if case_id else None,
        "method": "dp",
        "status": "time_limit" if status == "time_limit" else "failed",
        "objective_yen": None,
        "energy_charge_yen": None,
        "basic_charge_yen": None,
        "maximum_purchased_power_kW": None,
        "contract_equivalent_power_kW": None,
        "maximum_constraint_violation": None,
        "solve_time_seconds": solve_time,
        "total_time_seconds": time.perf_counter() - total_start,
        "peak_memory_mib": peak_memory_bytes / (1024 * 1024),
        "message": message,
        "solver_status": status,
        "best_bound_yen": None,
        "relative_gap": None,
        "soc_grid_count": soc_grid_count,
        "soc_grid_step_kWh": soc_grid_spacing,
        "transition_count": metrics.get("feasible_state_transition_count"),
        "maximum_nondominated_labels": metrics.get("maximum_retained_labels_per_state"),
        "initial_compile_time_seconds": 0.0,
        "prepared_solve_time_seconds": solve_time,
        "initial_compilation_time_seconds": 0.0,
        "initial_compilation_status": "not_applicable_pure_python",
        "transition_preparation_time_seconds": preparation_time,
        "soc_grid_point_count": soc_grid_count,
        "soc_grid_spacing_kWh": soc_grid_spacing,
        **metrics,
    }
    return {"summary": summary, "trajectory": None, "evaluation": None}


def solve_dp(
    problem: Mapping[str, Any],
    soc_grid_count: int,
    *,
    time_limit_seconds: float = 300.0,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Solve a finite SOC-grid problem with exact peak/cost Pareto labels."""

    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be greater than zero")
    data = _validated_problem(problem)
    total_start = time.perf_counter()
    tracemalloc.start()

    preparation_start = time.perf_counter()
    grid, initial_index, terminal_index = build_soc_grid(data, soc_grid_count)
    n = len(data["load_kW"])
    grid_edges: list[list[tuple[int, float, float]]] = []
    for current_soc in grid:
        edges: list[tuple[int, float, float]] = []
        for next_index, next_soc in enumerate(grid):
            powers = _battery_edge(data, current_soc, next_soc)
            if powers is not None:
                edges.append((next_index, *powers))
        grid_edges.append(edges)
    preparation_time = time.perf_counter() - preparation_start

    initial = Label(0.0, 0.0, None, None, initial_index, 0.0, 0.0, 0.0, 0.0)
    labels_by_state: list[list[Label]] = [[] for _ in grid]
    labels_by_state[initial_index] = [initial]
    retained_by_boundary = [1]
    maximum_retained_per_state = 1
    feasible_state_transition_count = 0
    expanded_label_transition_count = 0
    deadline = total_start + time_limit_seconds
    solve_start = time.perf_counter()

    for t in range(n):
        candidates: list[list[Label]] = [[] for _ in grid]
        for state, labels in enumerate(labels_by_state):
            if not labels:
                continue
            for next_index, charge, discharge in grid_edges[state]:
                dispatch = _dispatch_for_edge(data, t, charge, discharge)
                if dispatch is None:
                    continue
                feasible_state_transition_count += 1
                purchased, pv_used = dispatch
                for label in labels:
                    expanded_label_transition_count += 1
                    candidates[next_index].append(
                        Label(
                            peak_kW=max(label.peak_kW, purchased),
                            energy_charge_yen=(
                                label.energy_charge_yen
                                + float(data["price_yen_per_kWh"][t])
                                * purchased
                                * float(data["time_step_hours"])
                            ),
                            previous=label,
                            previous_state=state,
                            state=next_index,
                            purchased_power_kW=purchased,
                            pv_used_kW=pv_used,
                            charge_power_kW_internal=charge,
                            discharge_power_kW_internal=discharge,
                        )
                    )
                    if expanded_label_transition_count % 4096 == 0 and time.perf_counter() > deadline:
                        _, peak_bytes = tracemalloc.get_traced_memory()
                        tracemalloc.stop()
                        return _failure_result(
                            case_id=case_id,
                            status="time_limit",
                            message="DP reached the time limit before completing all intervals.",
                            total_start=total_start,
                            solve_time=time.perf_counter() - solve_start,
                            preparation_time=preparation_time,
                            soc_grid_count=soc_grid_count,
                            soc_grid_spacing=grid[1] - grid[0],
                            peak_memory_bytes=peak_bytes,
                            metrics={
                                "feasible_state_transition_count": feasible_state_transition_count,
                                "expanded_label_transition_count": expanded_label_transition_count,
                                "retained_label_count_by_boundary": retained_by_boundary,
                                "maximum_retained_labels_per_state": maximum_retained_per_state,
                            },
                        )
        labels_by_state = [_pareto_prune(state_labels) for state_labels in candidates]
        retained_by_boundary.append(sum(len(state_labels) for state_labels in labels_by_state))
        maximum_retained_per_state = max(
            maximum_retained_per_state,
            max((len(state_labels) for state_labels in labels_by_state), default=0),
        )
        if time.perf_counter() > deadline:
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            return _failure_result(
                case_id=case_id,
                status="time_limit",
                message="DP reached the time limit before completing all intervals.",
                total_start=total_start,
                solve_time=time.perf_counter() - solve_start,
                preparation_time=preparation_time,
                soc_grid_count=soc_grid_count,
                soc_grid_spacing=grid[1] - grid[0],
                peak_memory_bytes=peak_bytes,
                metrics={
                    "feasible_state_transition_count": feasible_state_transition_count,
                    "expanded_label_transition_count": expanded_label_transition_count,
                    "retained_label_count_by_boundary": retained_by_boundary,
                    "maximum_retained_labels_per_state": maximum_retained_per_state,
                },
            )

    solve_time = time.perf_counter() - solve_start
    terminal_labels = labels_by_state[terminal_index]
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    metrics = {
        "feasible_state_transition_count": feasible_state_transition_count,
        "expanded_label_transition_count": expanded_label_transition_count,
        "retained_label_count_by_boundary": retained_by_boundary,
        "retained_label_count_final_boundary": retained_by_boundary[-1],
        "retained_label_count_terminal_state": len(terminal_labels),
        "maximum_retained_labels_per_state": maximum_retained_per_state,
    }
    if not terminal_labels:
        return _failure_result(
            case_id=case_id,
            status="infeasible",
            message="No path reaches the exact terminal SOC on the requested grid.",
            total_start=total_start,
            solve_time=solve_time,
            preparation_time=preparation_time,
            soc_grid_count=soc_grid_count,
            soc_grid_spacing=grid[1] - grid[0],
            peak_memory_bytes=peak_bytes,
            metrics=metrics,
        )

    basic_rate = float(data["basic_charge_yen_per_kW"])
    best = min(
        terminal_labels,
        key=lambda label: (
            label.energy_charge_yen + basic_rate * label.peak_kW,
            label.peak_kW,
            label.energy_charge_yen,
        ),
    )
    path: list[Label] = []
    cursor = best
    while cursor.previous is not None:
        path.append(cursor)
        cursor = cursor.previous
    path.reverse()
    if len(path) != n:
        raise RuntimeError("internal DP predecessor chain has an invalid length")

    trajectory = {
        "purchased_power_kW": [label.purchased_power_kW for label in path],
        "pv_used_kW": [label.pv_used_kW for label in path],
        "charge_power_kW_internal": [label.charge_power_kW_internal for label in path],
        "discharge_power_kW_internal": [label.discharge_power_kW_internal for label in path],
        "soc_kWh": [grid[initial_index]] + [grid[label.state] for label in path],
    }
    reported = {
        "maximum_purchased_power_kW": best.peak_kW,
        "contract_equivalent_power_kW": best.peak_kW,
        "energy_charge_yen": best.energy_charge_yen,
        "basic_charge_yen": basic_rate * best.peak_kW,
        "objective_yen": best.energy_charge_yen + basic_rate * best.peak_kW,
    }
    evaluation = evaluate_solution(data, trajectory, reported)
    passed = evaluation["status"] == "pass"
    summary = {
        "schema_version": 1,
        "run_id": case_id,
        "experiment_id": "E0_validation" if case_id else None,
        "method": "dp",
        "status": "success" if passed else "failed",
        **reported,
        "maximum_constraint_violation": evaluation["maximum_constraint_violation"],
        "solve_time_seconds": solve_time,
        "total_time_seconds": time.perf_counter() - total_start,
        "peak_memory_mib": peak_bytes / (1024 * 1024),
        "message": (
            "DP found an optimal grid path and independent evaluation passed."
            if passed
            else "DP returned a path, but independent evaluation failed."
        ),
        "solver_status": "optimal" if passed else "evaluation_failed",
        "best_bound_yen": reported["objective_yen"] if passed else None,
        "relative_gap": 0.0 if passed else None,
        "soc_grid_count": soc_grid_count,
        "soc_grid_step_kWh": grid[1] - grid[0],
        "transition_count": feasible_state_transition_count,
        "maximum_nondominated_labels": maximum_retained_per_state,
        "initial_compile_time_seconds": 0.0,
        "prepared_solve_time_seconds": solve_time,
        "initial_compilation_time_seconds": 0.0,
        "initial_compilation_status": "not_applicable_pure_python",
        "transition_preparation_time_seconds": preparation_time,
        "soc_grid_point_count": soc_grid_count,
        "soc_grid_spacing_kWh": grid[1] - grid[0],
        "soc_grid_initial_index": initial_index,
        "soc_grid_terminal_index": terminal_index,
        **metrics,
    }
    return {"summary": summary, "trajectory": trajectory, "evaluation": evaluation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="T04 JSON case containing a normalized problem")
    parser.add_argument("--soc-grid-count", type=int, required=True)
    parser.add_argument("--time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()

    with args.case.open(encoding="utf-8") as source:
        case = json.load(source)
    if not isinstance(case, Mapping) or not isinstance(case.get("problem"), Mapping):
        raise EvaluationInputError("case.problem must be an object")
    result = solve_dp(
        case["problem"],
        args.soc_grid_count,
        time_limit_seconds=args.time_limit_seconds,
        case_id=case.get("case_id"),
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
