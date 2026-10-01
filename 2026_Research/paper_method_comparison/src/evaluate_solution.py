#!/usr/bin/env python3
"""Independently recompute EMS costs and check every common-model constraint."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_TOLERANCES = {
    "power_kW": 1e-6,
    "energy_kWh": 1e-6,
    "cost_absolute_yen": 0.01,
    "cost_relative": 1e-8,
}


class EvaluationInputError(ValueError):
    """Raised when an evaluation input is structurally unusable."""


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationInputError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationInputError(f"{name} must be a finite number")
    return result


def _positive(value: Any, name: str) -> float:
    result = _number(value, name)
    if result <= 0:
        raise EvaluationInputError(f"{name} must be greater than zero")
    return result


def _series(
    values: Any,
    name: str,
    expected_length: int,
) -> list[float]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise EvaluationInputError(f"{name} must be an array")
    if len(values) != expected_length:
        raise EvaluationInputError(
            f"{name} has {len(values)} values; expected {expected_length}"
        )
    return [_number(value, f"{name}[{index}]") for index, value in enumerate(values)]


def _tolerances(overrides: Mapping[str, Any] | None) -> dict[str, float]:
    result = dict(DEFAULT_TOLERANCES)
    if overrides:
        unknown = set(overrides) - set(result)
        if unknown:
            raise EvaluationInputError(f"unknown tolerance keys: {sorted(unknown)}")
        result.update({key: _number(value, f"tolerances.{key}") for key, value in overrides.items()})
    if any(value < 0 for value in result.values()):
        raise EvaluationInputError("tolerances must be nonnegative")
    return result


def _cost_tolerance(reference_yen: float, tolerances: Mapping[str, float]) -> float:
    return max(
        tolerances["cost_absolute_yen"],
        abs(reference_yen) * tolerances["cost_relative"],
    )


def evaluate_solution(
    problem: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    reported: Mapping[str, Any] | None = None,
    tolerances: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return recomputed values and detailed violations without using a solver.

    ``problem`` is a normalized, method-independent description. Charge and
    discharge powers are on the battery-internal side; SOC is stored energy.
    ``reported`` is optional, but when supplied its peak and cost fields are
    checked against the independent recomputation.
    """

    tol = _tolerances(tolerances)
    dt = _positive(problem.get("time_step_hours"), "problem.time_step_hours")
    load = problem.get("load_kW")
    if isinstance(load, (str, bytes)) or not isinstance(load, Sequence) or not load:
        raise EvaluationInputError("problem.load_kW must be a non-empty array")
    interval_count = len(load)
    load_values = _series(load, "problem.load_kW", interval_count)
    pv_available = _series(problem.get("pv_available_kW"), "problem.pv_available_kW", interval_count)
    price = _series(problem.get("price_yen_per_kWh"), "problem.price_yen_per_kWh", interval_count)
    if any(value < 0 for value in load_values):
        raise EvaluationInputError("problem.load_kW must be nonnegative")
    if any(value < 0 for value in pv_available):
        raise EvaluationInputError("problem.pv_available_kW must be nonnegative")

    capacity = _positive(problem.get("battery_capacity_kWh"), "problem.battery_capacity_kWh")
    charge_limit = _number(problem.get("charge_limit_kW_internal"), "problem.charge_limit_kW_internal")
    discharge_limit = _number(problem.get("discharge_limit_kW_internal"), "problem.discharge_limit_kW_internal")
    eta_charge = _positive(problem.get("charge_efficiency"), "problem.charge_efficiency")
    eta_discharge = _positive(problem.get("discharge_efficiency"), "problem.discharge_efficiency")
    if charge_limit < 0 or discharge_limit < 0:
        raise EvaluationInputError("battery power limits must be nonnegative")
    if eta_charge > 1 or eta_discharge > 1:
        raise EvaluationInputError("battery efficiencies must not exceed one")
    soc_min = _number(problem.get("soc_min_kWh"), "problem.soc_min_kWh")
    soc_max = _number(problem.get("soc_max_kWh"), "problem.soc_max_kWh")
    initial_soc = _number(problem.get("initial_soc_kWh"), "problem.initial_soc_kWh")
    terminal_soc = _number(problem.get("terminal_soc_kWh"), "problem.terminal_soc_kWh")
    if not (0 <= soc_min <= initial_soc <= soc_max <= capacity):
        raise EvaluationInputError("initial SOC and SOC bounds are inconsistent")
    if not soc_min <= terminal_soc <= soc_max:
        raise EvaluationInputError("terminal SOC lies outside the SOC bounds")
    basic_rate = _number(
        problem.get("basic_charge_yen_per_kW"),
        "problem.basic_charge_yen_per_kW",
    )
    if basic_rate < 0:
        raise EvaluationInputError("basic charge coefficient must be nonnegative")

    buy = _series(trajectory.get("purchased_power_kW"), "trajectory.purchased_power_kW", interval_count)
    pv_used = _series(trajectory.get("pv_used_kW"), "trajectory.pv_used_kW", interval_count)
    charge = _series(
        trajectory.get("charge_power_kW_internal"),
        "trajectory.charge_power_kW_internal",
        interval_count,
    )
    discharge = _series(
        trajectory.get("discharge_power_kW_internal"),
        "trajectory.discharge_power_kW_internal",
        interval_count,
    )
    soc = _series(trajectory.get("soc_kWh"), "trajectory.soc_kWh", interval_count + 1)

    violations: list[dict[str, Any]] = []
    check_maxima: dict[str, dict[str, Any]] = {}

    def record(
        check: str,
        magnitude: float,
        tolerance: float,
        unit: str,
        index: int | None = None,
    ) -> None:
        magnitude = max(0.0, float(magnitude))
        current = check_maxima.get(check)
        if current is None or magnitude > current["magnitude"]:
            check_maxima[check] = {
                "magnitude": magnitude,
                "tolerance": tolerance,
                "unit": unit,
                "index": index,
            }
        if magnitude > tolerance:
            violations.append(
                {
                    "check": check,
                    "index": index,
                    "magnitude": magnitude,
                    "tolerance": tolerance,
                    "unit": unit,
                }
            )

    power_tol = tol["power_kW"]
    energy_tol = tol["energy_kWh"]
    for index in range(interval_count):
        record("purchased_power_nonnegative", -buy[index], power_tol, "kW", index)
        record("pv_used_nonnegative", -pv_used[index], power_tol, "kW", index)
        record("pv_availability", pv_used[index] - pv_available[index], power_tol, "kW", index)
        record("charge_power_nonnegative", -charge[index], power_tol, "kW", index)
        record("discharge_power_nonnegative", -discharge[index], power_tol, "kW", index)
        record("charge_power_limit", charge[index] - charge_limit, power_tol, "kW", index)
        record("discharge_power_limit", discharge[index] - discharge_limit, power_tol, "kW", index)
        record("simultaneous_charge_discharge", min(charge[index], discharge[index]), power_tol, "kW", index)
        balance = (
            buy[index]
            + pv_used[index]
            + eta_discharge * discharge[index]
            - load_values[index]
            - charge[index] / eta_charge
        )
        record("power_balance", abs(balance), power_tol, "kW", index)
        transition = soc[index + 1] - soc[index] - dt * (charge[index] - discharge[index])
        record("soc_transition", abs(transition), energy_tol, "kWh", index)

    for index, value in enumerate(soc):
        record("soc_lower_bound", soc_min - value, energy_tol, "kWh", index)
        record("soc_upper_bound", value - soc_max, energy_tol, "kWh", index)
    record("initial_soc", abs(soc[0] - initial_soc), energy_tol, "kWh", 0)
    record("terminal_soc", abs(soc[-1] - terminal_soc), energy_tol, "kWh", interval_count)

    maximum_purchased_power = max(buy)
    energy_charge = sum(
        price[index] * buy[index] * dt for index in range(interval_count)
    )
    basic_charge = basic_rate * maximum_purchased_power
    total_cost = energy_charge + basic_charge

    reported_checks = {
        "maximum_purchased_power_kW": (maximum_purchased_power, power_tol, "kW"),
        "contract_equivalent_power_kW": (maximum_purchased_power, power_tol, "kW"),
        "energy_charge_yen": (energy_charge, _cost_tolerance(energy_charge, tol), "yen"),
        "basic_charge_yen": (basic_charge, _cost_tolerance(basic_charge, tol), "yen"),
        "objective_yen": (total_cost, _cost_tolerance(total_cost, tol), "yen"),
    }
    if reported is not None:
        missing = set(reported_checks) - set(reported)
        if missing:
            raise EvaluationInputError(f"reported values are missing: {sorted(missing)}")
        for field, (expected, threshold, unit) in reported_checks.items():
            actual = _number(reported[field], f"reported.{field}")
            record(f"reported_{field}", abs(actual - expected), threshold, unit)

    physical_checks = {
        name: details
        for name, details in check_maxima.items()
        if not name.startswith("reported_")
    }
    physical_maximum = max(
        (details["magnitude"] for details in physical_checks.values()),
        default=0.0,
    )
    return {
        "schema_version": 1,
        "status": "pass" if not violations else "fail",
        "interval_count": interval_count,
        "recomputed": {
            "maximum_purchased_power_kW": maximum_purchased_power,
            "contract_equivalent_power_kW": maximum_purchased_power,
            "energy_charge_yen": energy_charge,
            "basic_charge_yen": basic_charge,
            "objective_yen": total_cost,
        },
        "tolerances": tol,
        "cost_tolerance_yen": _cost_tolerance(total_cost, tol),
        "maximum_constraint_violation": physical_maximum,
        "checks": check_maxima,
        "violations": violations,
    }


def evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the standard JSON case format used by T04 and later tests."""

    for key in ("problem", "trajectory"):
        if not isinstance(case.get(key), Mapping):
            raise EvaluationInputError(f"case.{key} must be an object")
    reported = case.get("reported")
    if reported is not None and not isinstance(reported, Mapping):
        raise EvaluationInputError("case.reported must be an object")
    tolerances = case.get("tolerances")
    if tolerances is not None and not isinstance(tolerances, Mapping):
        raise EvaluationInputError("case.tolerances must be an object")
    result = evaluate_solution(case["problem"], case["trajectory"], reported, tolerances)
    if "case_id" in case:
        result["case_id"] = case["case_id"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="JSON file containing problem, trajectory, and reported values")
    parser.add_argument("--output", type=Path, help="optional path for the JSON evaluation report")
    args = parser.parse_args()
    with args.case.open(encoding="utf-8") as source:
        case = json.load(source)
    result = evaluate_case(case)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EvaluationInputError, KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
