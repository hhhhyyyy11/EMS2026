# -*- coding: utf-8 -*-
"""Analyze the 160--170 kW demand-target boundary.

The script first solves a peak-minimization MILP to obtain the physical lower
bound on annual maximum grid purchase.  It then compares that lower bound with
the unconstrained total-cost optimum already calculated for all 16 historical
demand conditions.  Targets are classified at 0.1 kW resolution without
re-solving cases that are mathematically proven infeasible or nonbinding.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from optimize_demand_target_lp import (  # noqa: E402
    TariffParams,
    battery_params_from_config,
    get_past_grid_purchase_kw,
    load_project_data,
    make_two_year_data,
    solve_demand_target_lp,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT_DIR / "config.json"))
    parser.add_argument("--sheet", default="30分値")
    parser.add_argument(
        "--baseline-results",
        default=str(ROOT_DIR / "results" / "demand_target_sensitivity" / "all_results.csv"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "results" / "demand_target_boundary_160_170"),
    )
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--grid-step", type=float, default=0.1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config, one_year = load_project_data(args.config, args.sheet)
    past_df, future_df = make_two_year_data(one_year)
    past_grid, past_source = get_past_grid_purchase_kw(
        past_df,
        "lp_results",
        str(ROOT_DIR / "results" / "lp_baseline" / "dynamic_lp_results_minimize_total_cost.csv"),
    )
    battery = battery_params_from_config(config)
    tariff = TariffParams(
        basic_rate_yen_per_kw_month=2829.60 * 0.85,
        energy_rate_fallback_yen_per_kwh=float(config.get("fixed_price_yen_per_kWh", 21.51)),
    )

    minimum_peak_result = solve_demand_target_lp(
        past_df=past_df,
        future_df=future_df,
        past_grid_purchase_kw=past_grid,
        battery=battery,
        tariff=tariff,
        time_limit=args.time_limit,
        demand_target_kw=None,
        enforce_terminal_soc=True,
        objective_mode="minimize_grid_peak",
    )
    if not minimum_peak_result["feasible"]:
        raise RuntimeError(
            f"Peak-minimization run failed: {minimum_peak_result['status']}"
        )
    minimum_feasible_target = float(
        minimum_peak_result["minimum_annual_grid_peak_kw"]
    )

    previous = pd.read_csv(args.baseline_results)
    baselines = previous[
        (previous["scenario_type"] == "synthetic")
        & previous["demand_target_kW"].isna()
        & previous["feasible"]
    ].copy()
    if len(baselines) != 16:
        raise ValueError(f"Expected 16 synthetic baselines, found {len(baselines)}")

    critical_values = baselines["annual_max_grid_purchase_kW"].to_numpy(dtype=float)
    critical_min = float(critical_values.min())
    critical_max = float(critical_values.max())
    equality_gap = float(critical_max - minimum_feasible_target)

    targets = list(np.round(np.arange(160.0, 170.0 + args.grid_step / 2, args.grid_step), 10))
    if not any(abs(value - minimum_feasible_target) <= 1e-9 for value in targets):
        targets.append(minimum_feasible_target)
        targets.sort()

    tolerance = 1e-6
    rows: list[dict] = []
    for baseline in baselines.itertuples(index=False):
        critical_target = float(baseline.annual_max_grid_purchase_kW)
        for target in targets:
            if target < minimum_feasible_target - tolerance:
                classification = "infeasible_below_physical_minimum"
                feasible = False
                total_cost = np.nan
                cost_change = np.nan
                proof = (
                    "Target is below the globally minimized annual grid peak; "
                    "no dispatch can satisfy it."
                )
            elif target >= critical_target - tolerance:
                classification = "feasible_nonbinding"
                feasible = True
                total_cost = float(baseline.annual_total_cost_yen)
                cost_change = 0.0
                proof = (
                    "The unconstrained total-cost optimum satisfies this target; "
                    "therefore the constrained optimum is identical."
                )
            else:
                classification = "feasible_binding_requires_solve"
                feasible = True
                total_cost = np.nan
                cost_change = np.nan
                proof = "Target lies between the physical minimum and unconstrained optimum."

            rows.append(
                {
                    "past_peak_kW": float(baseline.past_peak_kW),
                    "remaining_months": int(baseline.remaining_months),
                    "demand_target_kW": float(target),
                    "classification": classification,
                    "feasible": feasible,
                    "annual_total_cost_yen": total_cost,
                    "cost_change_vs_unconstrained_yen": cost_change,
                    "minimum_feasible_target_kW": minimum_feasible_target,
                    "unconstrained_critical_target_kW": critical_target,
                    "proof": proof,
                }
            )

    grid = pd.DataFrame(rows)
    grid.to_csv(output_dir / "target_grid_160_170_0p1kW.csv", index=False)

    threshold_rows = baselines[
        [
            "past_peak_kW",
            "remaining_months",
            "annual_total_cost_yen",
            "annual_max_grid_purchase_kW",
        ]
    ].copy()
    threshold_rows["minimum_feasible_target_kW"] = minimum_feasible_target
    threshold_rows["adjustable_interval_width_kW"] = (
        threshold_rows["annual_max_grid_purchase_kW"] - minimum_feasible_target
    )
    threshold_rows.to_csv(output_dir / "thresholds_by_history_condition.csv", index=False)

    unresolved = grid[grid["classification"] == "feasible_binding_requires_solve"]
    summary = {
        "status": str(minimum_peak_result["status"]),
        "minimum_feasible_target_kW": minimum_feasible_target,
        "unconstrained_critical_target_min_kW": critical_min,
        "unconstrained_critical_target_max_kW": critical_max,
        "difference_max_kW": equality_gap,
        "binding_feasible_grid_rows": int(len(unresolved)),
        "conclusion": (
            "The minimum feasible target equals the unconstrained optimum peak. "
            "Targets below it are infeasible; targets at or above it do not alter the optimum."
        ),
        "historical_conditions": int(len(baselines)),
        "target_grid_start_kW": 160.0,
        "target_grid_end_kW": 170.0,
        "target_grid_step_kW": float(args.grid_step),
        "terminal_soc_equals_initial": True,
        "charge_discharge_exclusivity_binary": True,
        "past_grid_source": past_source,
        "solver_elapsed_seconds": float(minimum_peak_result["elapsed_seconds"]),
        "gap": float(minimum_peak_result["gap"]),
    }
    with open(output_dir / "boundary_summary.json", "w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)

    condition_labels = [
        f"{int(row.past_peak_kW)}/{int(row.remaining_months)}"
        for row in baselines.sort_values(["past_peak_kW", "remaining_months"]).itertuples()
    ]
    plot_targets = np.round(np.arange(160.0, 170.0 + args.grid_step / 2, args.grid_step), 10)
    matrix = np.array(
        [
            [0.0 if target < minimum_feasible_target - tolerance else 1.0 for target in plot_targets]
            for _ in condition_labels
        ]
    )
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto", extent=[160, 170, len(condition_labels), 0])
    ax.axvline(minimum_feasible_target, color="black", linestyle="--", linewidth=1.5)
    ax.set_yticks(np.arange(len(condition_labels)) + 0.5, condition_labels)
    ax.set_xlabel("Demand target [kW]")
    ax.set_ylabel("Past monthly maximum / remaining months")
    ax.set_title("Demand-target boundary (red: infeasible, green: identical optimum)")
    ax.text(
        minimum_feasible_target + 0.05,
        0.7,
        f"Boundary = {minimum_feasible_target:.6f} kW",
        fontsize=9,
        va="center",
    )
    fig.tight_layout()
    fig.savefig(output_dir / "demand_target_boundary_map.png", dpi=180)
    plt.close(fig)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
