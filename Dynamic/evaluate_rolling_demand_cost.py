# -*- coding: utf-8 -*-
"""Re-evaluate dispatch results with rolling 12-month demand charges.

This script evaluates an already-computed dispatch schedule under the same
monthly demand-target rule used by optimize_demand_target_lp.py.  It is used to
compare a conventional annual-peak LP dispatch against the proposed
demand-target LP dispatch with a common cost metric.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List

import pandas as pd


DELTA_T_HOURS = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate conventional LP results using rolling demand charges."
    )
    parser.add_argument(
        "--conventional-csv",
        default="Dynamic/results/dynamic_lp_results_minimize_total_cost.csv",
        help="CSV from Dynamic/optimize_LP.py containing datetime, sBY, and electricity_price columns",
    )
    parser.add_argument(
        "--proposed-monthly-csv",
        default="Dynamic/results/demand_target_lp/demand_target_monthly_summary.csv",
        help="Monthly summary CSV from Dynamic/optimize_demand_target_lp.py",
    )
    parser.add_argument(
        "--proposed-summary-json",
        default="Dynamic/results/demand_target_lp/demand_target_summary.json",
        help="Annual summary JSON from Dynamic/optimize_demand_target_lp.py",
    )
    parser.add_argument(
        "--output-dir",
        default="Dynamic/results/rolling_demand_reassessment",
        help="Output directory for reassessment summaries",
    )
    parser.add_argument(
        "--basic-rate",
        type=float,
        default=2829.60 * 0.85,
        help="Monthly demand charge rate [yen/kW/month], including power-factor adjustment",
    )
    return parser.parse_args()


def month_label(period) -> str:
    return str(period)


def in_rolling_12_month_window(timestamp, target_period) -> bool:
    start_period = target_period - 11
    current_period = timestamp.to_period("M")
    return start_period <= current_period <= target_period


def build_reference_sets(past_index, future_index, target_months) -> Dict:
    reference_sets = {}
    for month in target_months:
        past_positions = [
            i
            for i, timestamp in enumerate(past_index)
            if in_rolling_12_month_window(timestamp, month)
        ]
        future_positions = [
            i
            for i, timestamp in enumerate(future_index)
            if in_rolling_12_month_window(timestamp, month)
        ]
        reference_sets[month] = {"past": past_positions, "future": future_positions}
    return reference_sets


def read_conventional_dispatch(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = {"datetime", "sBY", "electricity_price"}
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"Missing columns in {path}: {sorted(missing)}")

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def summarize_conventional(df: pd.DataFrame, basic_rate: float) -> List[dict]:
    past_df = df.copy()
    future_df = df.copy()
    future_df["datetime"] = future_df["datetime"] + pd.DateOffset(years=1)

    past_index = pd.DatetimeIndex(past_df["datetime"])
    future_index = pd.DatetimeIndex(future_df["datetime"])
    future_months = sorted(future_index.to_period("M").unique())
    reference_sets = build_reference_sets(past_index, future_index, future_months)

    rows = []
    past_sby = past_df["sBY"].to_numpy()
    future_sby = future_df["sBY"].to_numpy()

    future_df["month"] = future_df["datetime"].dt.to_period("M")
    for month in future_months:
        refs = reference_sets[month]
        reference_values = []
        if refs["past"]:
            reference_values.extend(float(past_sby[i]) for i in refs["past"])
        if refs["future"]:
            reference_values.extend(float(future_sby[i]) for i in refs["future"])

        month_df = future_df[future_df["month"] == month]
        demand_target = max(reference_values) if reference_values else 0.0
        monthly_peak = float(month_df["sBY"].max()) if not month_df.empty else 0.0
        energy_cost = float(
            (month_df["electricity_price"] * month_df["sBY"] * DELTA_T_HOURS).sum()
        )
        basic_cost = basic_rate * demand_target
        rows.append(
            {
                "month": month_label(month),
                "demand_target_kW": demand_target,
                "monthly_peak_kW": monthly_peak,
                "basic_cost_yen": basic_cost,
                "energy_cost_yen": energy_cost,
                "total_cost_yen": basic_cost + energy_cost,
                "past_reference_steps": len(refs["past"]),
                "future_reference_steps": len(refs["future"]),
            }
        )
    return rows


def annual_summary(monthly_rows: List[dict], status: str = "evaluated") -> dict:
    return {
        "status": status,
        "annual_energy_cost_yen": float(
            sum(row["energy_cost_yen"] for row in monthly_rows)
        ),
        "annual_basic_cost_yen": float(
            sum(row["basic_cost_yen"] for row in monthly_rows)
        ),
        "annual_total_cost_yen": float(
            sum(row["total_cost_yen"] for row in monthly_rows)
        ),
        "annual_max_grid_purchase_kW": float(
            max(row["monthly_peak_kW"] for row in monthly_rows)
        ),
        "max_monthly_demand_target_kW": float(
            max(row["demand_target_kW"] for row in monthly_rows)
        ),
    }


def load_proposed_summary(monthly_csv: str, summary_json: str) -> tuple[pd.DataFrame, dict]:
    monthly_df = pd.read_csv(monthly_csv)
    if os.path.exists(summary_json):
        with open(summary_json, "r", encoding="utf-8") as f:
            summary = json.load(f)
    else:
        summary = annual_summary(monthly_df.to_dict("records"), status="loaded")
    return monthly_df, summary


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    conventional_df = read_conventional_dispatch(args.conventional_csv)
    conventional_rows = summarize_conventional(conventional_df, args.basic_rate)
    conventional_summary = annual_summary(conventional_rows)

    proposed_monthly_df, proposed_summary = load_proposed_summary(
        args.proposed_monthly_csv, args.proposed_summary_json
    )

    conventional_monthly_df = pd.DataFrame(conventional_rows)
    conventional_monthly_path = os.path.join(
        args.output_dir, "conventional_reassessed_monthly_summary.csv"
    )
    conventional_monthly_df.to_csv(conventional_monthly_path, index=False)

    monthly_comparison = conventional_monthly_df.merge(
        proposed_monthly_df,
        on="month",
        suffixes=("_conventional", "_proposed"),
    )
    monthly_comparison["total_cost_saving_yen"] = (
        monthly_comparison["total_cost_yen_conventional"]
        - monthly_comparison["total_cost_yen_proposed"]
    )
    monthly_comparison_path = os.path.join(args.output_dir, "monthly_comparison.csv")
    monthly_comparison.to_csv(monthly_comparison_path, index=False)

    annual_comparison = {
        "conventional_reassessed": conventional_summary,
        "proposed": proposed_summary,
        "difference_conventional_minus_proposed": {
            "annual_energy_cost_yen": conventional_summary["annual_energy_cost_yen"]
            - proposed_summary["annual_energy_cost_yen"],
            "annual_basic_cost_yen": conventional_summary["annual_basic_cost_yen"]
            - proposed_summary["annual_basic_cost_yen"],
            "annual_total_cost_yen": conventional_summary["annual_total_cost_yen"]
            - proposed_summary["annual_total_cost_yen"],
            "annual_max_grid_purchase_kW": conventional_summary[
                "annual_max_grid_purchase_kW"
            ]
            - proposed_summary["annual_max_grid_purchase_kW"],
            "max_monthly_demand_target_kW": conventional_summary[
                "max_monthly_demand_target_kW"
            ]
            - proposed_summary["max_monthly_demand_target_kW"],
        },
    }
    annual_comparison_path = os.path.join(args.output_dir, "annual_comparison.json")
    with open(annual_comparison_path, "w", encoding="utf-8") as f:
        json.dump(annual_comparison, f, ensure_ascii=False, indent=2)

    print("Rolling demand-charge reassessment")
    print(f"Conventional annual energy cost: {conventional_summary['annual_energy_cost_yen']:.0f} yen")
    print(f"Conventional annual basic cost: {conventional_summary['annual_basic_cost_yen']:.0f} yen")
    print(f"Conventional annual total cost: {conventional_summary['annual_total_cost_yen']:.0f} yen")
    print(f"Proposed annual energy cost: {proposed_summary['annual_energy_cost_yen']:.0f} yen")
    print(f"Proposed annual basic cost: {proposed_summary['annual_basic_cost_yen']:.0f} yen")
    print(f"Proposed annual total cost: {proposed_summary['annual_total_cost_yen']:.0f} yen")
    print(
        "Total saving (conventional - proposed): "
        f"{annual_comparison['difference_conventional_minus_proposed']['annual_total_cost_yen']:.0f} yen"
    )
    print(f"Conventional monthly summary CSV: {conventional_monthly_path}")
    print(f"Monthly comparison CSV: {monthly_comparison_path}")
    print(f"Annual comparison JSON: {annual_comparison_path}")


if __name__ == "__main__":
    main()
