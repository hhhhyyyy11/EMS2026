# -*- coding: utf-8 -*-
"""Run and summarize the July demand-target MILP experiment matrix."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from optimize_demand_target_lp import (
    DELTA_T_HOURS,
    TariffParams,
    battery_params_from_config,
    get_past_grid_purchase_kw,
    load_project_data,
    make_two_year_data,
    solve_demand_target_lp,
    summarize_monthly,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT_DIR / "results" / "demand_target_sensitivity"
PEAKS_KW = (120.0, 140.0, 160.0, 180.0)
REMAINING_MONTHS = (1, 3, 6, 11)
TARGETS_KW = (None, 140.0, 150.0, 160.0, 170.0, 180.0)
BASE_PAST_PEAK_KW = 100.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT_DIR / "config.json"))
    parser.add_argument("--sheet", default="30分値")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None)
    return parser.parse_args()


def target_label(target_kw: float | None) -> str:
    return "none" if target_kw is None else f"{int(target_kw)}kW"


def scenario_id(peak_kw: float, remaining_months: int, target_kw: float | None) -> str:
    return f"peak{int(peak_kw)}_remain{remaining_months}_target{target_label(target_kw)}"


def synthetic_past_monthly_peaks(
    past_index: pd.DatetimeIndex,
    future_index: pd.DatetimeIndex,
    peak_kw: float,
    remaining_months: int,
    base_peak_kw: float = BASE_PAST_PEAK_KW,
) -> tuple[dict[pd.Period, float], pd.Period, pd.Period]:
    if remaining_months not in REMAINING_MONTHS:
        raise ValueError(f"Unsupported remaining months: {remaining_months}")
    past_months = sorted(past_index.to_period("M").unique())
    future_start = future_index.min().to_period("M")
    peak_month = future_start + (remaining_months - 12)
    expiry_month = future_start + remaining_months
    if peak_month not in past_months:
        raise ValueError(f"Peak month {peak_month} is outside available past months")
    values = {month: float(base_peak_kw) for month in past_months}
    values[peak_month] = float(peak_kw)
    return values, peak_month, expiry_month


def months_containing_peak(
    future_index: pd.DatetimeIndex, peak_month: pd.Period
) -> list[pd.Period]:
    future_months = sorted(future_index.to_period("M").unique())
    return [month for month in future_months if month - 11 <= peak_month <= month]


def write_case_outputs(
    case_dir: Path,
    future_df: pd.DataFrame,
    result: dict,
    monthly_rows: list[dict],
    metadata: dict,
) -> dict:
    case_dir.mkdir(parents=True, exist_ok=True)
    timeseries = pd.DataFrame(
        {
            "timestamp": future_df.index,
            "demand_kW": future_df["consumption_kW"].to_numpy(),
            "pv_available_kW": future_df["pv_kW"].to_numpy(),
            "pv_used_kW": result["pv_used"],
            "grid_purchase_kW": result["s_by"],
            "charge_input_kW": result["charge_input"],
            "charge_stored_kW": result["charge_stored"],
            "discharge_from_battery_kW": result["discharge_from_battery"],
            "discharge_used_kW": result["discharge_used"],
            "soc_kWh": result["soc"],
            "electricity_price_yen_per_kWh": result["prices"],
        }
    )
    timeseries.to_csv(case_dir / "timeseries.csv.gz", index=False, compression="gzip")
    pd.DataFrame(monthly_rows).to_csv(case_dir / "monthly.csv", index=False)

    max_pos = int(np.argmax(result["s_by"]))
    initial_soc = (
        result["soc"][0]
        - DELTA_T_HOURS * result["charge_stored"][0]
        + DELTA_T_HOURS * result["discharge_from_battery"][0]
    )
    summary = {
        **metadata,
        "status": str(result["status"]),
        "feasible": True,
        "objective_value_yen": float(result["objective_value"]),
        "annual_energy_cost_yen": float(sum(row["energy_cost_yen"] for row in monthly_rows)),
        "annual_basic_cost_yen": float(sum(row["basic_cost_yen"] for row in monthly_rows)),
        "annual_total_cost_yen": float(sum(row["total_cost_yen"] for row in monthly_rows)),
        "annual_max_grid_purchase_kW": float(max(result["s_by"])),
        "annual_max_grid_purchase_timestamp": str(future_df.index[max_pos]),
        "max_monthly_contract_power_kW": float(
            max(row["contract_power_kW"] for row in monthly_rows)
        ),
        "initial_soc_kWh": float(initial_soc),
        "final_soc_kWh": float(result["soc"][-1]),
        "battery_throughput_kWh": float(
            DELTA_T_HOURS
            * (sum(result["charge_input"]) + sum(result["discharge_used"]))
        ),
        "pv_used_kWh": float(DELTA_T_HOURS * sum(result["pv_used"])),
        "pv_curtailment_kWh": float(
            DELTA_T_HOURS
            * (sum(future_df["pv_kW"].to_numpy()) - sum(result["pv_used"]))
        ),
        "target_hit_count": int(
            sum(
                1
                for value in result["s_by"]
                if metadata["demand_target_kW"] is not None
                and abs(value - metadata["demand_target_kW"]) <= 1e-4
            )
        ),
        "target_excess_max_kW": float(
            0.0
            if metadata["demand_target_kW"] is None
            else max(0.0, max(result["s_by"]) - metadata["demand_target_kW"])
        ),
        "simultaneous_charge_discharge_count": int(
            sum(
                1
                for charge, discharge in zip(
                    result["charge_input"], result["discharge_used"]
                )
                if charge > 1e-6 and discharge > 1e-6
            )
        ),
        "elapsed_seconds": float(result["elapsed_seconds"]),
        "gap": float(result["gap"]),
    }
    with open(case_dir / "summary.json", "w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    return summary


def run_case(
    output_dir: Path,
    past_df: pd.DataFrame,
    future_df: pd.DataFrame,
    past_grid_purchase_kw: list[float],
    past_monthly_peaks: dict[pd.Period, float],
    battery,
    tariff: TariffParams,
    time_limit: float,
    metadata: dict,
    overwrite: bool,
) -> dict:
    case_dir = output_dir / "cases" / metadata["case_id"]
    summary_path = case_dir / "summary.json"
    if summary_path.exists() and not overwrite:
        with open(summary_path, encoding="utf-8") as stream:
            return json.load(stream)

    result = solve_demand_target_lp(
        past_df=past_df,
        future_df=future_df,
        past_grid_purchase_kw=past_grid_purchase_kw,
        past_monthly_peaks=past_monthly_peaks,
        battery=battery,
        tariff=tariff,
        time_limit=time_limit,
        demand_target_kw=metadata["demand_target_kW"],
        enforce_terminal_soc=True,
    )
    case_dir.mkdir(parents=True, exist_ok=True)
    if not result["feasible"]:
        summary = {
            **metadata,
            "status": str(result["status"]),
            "feasible": False,
            "elapsed_seconds": float(result["elapsed_seconds"]),
            "gap": None,
        }
        with open(summary_path, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2)
        return summary

    monthly_rows = summarize_monthly(future_df, result, tariff)
    return write_case_outputs(case_dir, future_df, result, monthly_rows, metadata)


def clone_nonbinding_target_case(
    output_dir: Path, baseline_summary: dict, metadata: dict, overwrite: bool
) -> dict:
    """Reuse a proven optimum when the added target is above its maximum grid purchase."""
    source_dir = output_dir / "cases" / baseline_summary["case_id"]
    case_dir = output_dir / "cases" / metadata["case_id"]
    summary_path = case_dir / "summary.json"
    if summary_path.exists() and not overwrite:
        with open(summary_path, encoding="utf-8") as stream:
            return json.load(stream)
    case_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("timeseries.csv.gz", "monthly.csv"):
        shutil.copy2(source_dir / filename, case_dir / filename)
    monthly = pd.read_csv(case_dir / "monthly.csv")
    monthly["demand_target_kW"] = metadata["demand_target_kW"]
    monthly.to_csv(case_dir / "monthly.csv", index=False)
    summary = {
        **baseline_summary,
        **metadata,
        "target_hit_count": 0,
        "target_excess_max_kW": 0.0,
        "elapsed_seconds": 0.0,
        "reused_from_case_id": baseline_summary["case_id"],
        "reuse_proof": "baseline optimum satisfies added upper bound; constrained optimum is identical",
    }
    with open(summary_path, "w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    return summary


def make_plots(results: pd.DataFrame, output_dir: Path) -> None:
    figures = output_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    feasible = results[results["feasible"]].copy()
    synthetic = feasible[feasible["scenario_type"] == "synthetic"].copy()

    baselines = synthetic[synthetic["demand_target_kW"].isna()][
        ["past_peak_kW", "remaining_months", "annual_total_cost_yen"]
    ].rename(columns={"annual_total_cost_yen": "baseline_total_cost_yen"})
    synthetic = synthetic.merge(baselines, on=["past_peak_kW", "remaining_months"])
    synthetic["cost_change_vs_unconstrained_yen"] = (
        synthetic["annual_total_cost_yen"] - synthetic["baseline_total_cost_yen"]
    )

    best_targets = (
        synthetic[synthetic["demand_target_kW"].notna()]
        .sort_values("annual_total_cost_yen")
        .groupby(["past_peak_kW", "remaining_months"], as_index=False)
        .first()
    )
    heat = best_targets.pivot(
        index="past_peak_kW",
        columns="remaining_months",
        values="cost_change_vs_unconstrained_yen",
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    image = ax.imshow(heat.values, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(heat.columns)), [str(int(x)) for x in heat.columns])
    ax.set_yticks(range(len(heat.index)), [str(int(x)) for x in heat.index])
    ax.set_xlabel("Months until historical peak expires")
    ax.set_ylabel("Historical peak [kW]")
    ax.set_title("Best fixed target: cost change vs unconstrained MILP [yen]")
    for y in range(len(heat.index)):
        for x in range(len(heat.columns)):
            ax.text(x, y, f"{heat.iloc[y, x]:,.0f}", ha="center", va="center")
    fig.colorbar(image, ax=ax, label="Cost increase [yen]")
    fig.tight_layout()
    fig.savefig(figures / "cost_change_heatmap.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    for ax, peak in zip(axes.flat, PEAKS_KW):
        subset = synthetic[
            (synthetic["past_peak_kW"] == peak)
            & synthetic["demand_target_kW"].notna()
        ]
        for remaining in REMAINING_MONTHS:
            line = subset[subset["remaining_months"] == remaining].sort_values(
                "demand_target_kW"
            )
            ax.plot(
                line["demand_target_kW"],
                line["annual_total_cost_yen"] / 1e6,
                marker="o",
                label=f"{remaining} mo",
            )
        ax.set_title(f"Historical peak {int(peak)} kW")
        ax.grid(alpha=0.25)
    axes[1, 0].set_xlabel("Demand target [kW]")
    axes[1, 1].set_xlabel("Demand target [kW]")
    axes[0, 0].set_ylabel("Annual total cost [million yen]")
    axes[1, 0].set_ylabel("Annual total cost [million yen]")
    axes[0, 1].legend(ncol=2, fontsize=8)
    fig.suptitle("Demand target sensitivity across all 16 historical conditions")
    fig.tight_layout()
    fig.savefig(figures / "target_total_cost_curves.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.2))
    plot_df = synthetic[synthetic["demand_target_kW"].notna()].copy()
    labels = [
        f"{int(row.past_peak_kW)}/{int(row.remaining_months)}/{int(row.demand_target_kW)}"
        for row in plot_df.itertuples()
    ]
    x = np.arange(len(plot_df))
    ax.bar(x, plot_df["annual_energy_cost_yen"] / 1e6, label="Energy")
    ax.bar(
        x,
        plot_df["annual_basic_cost_yen"] / 1e6,
        bottom=plot_df["annual_energy_cost_yen"] / 1e6,
        label="Demand charge",
    )
    ax.set_xticks(x[::5], [labels[i] for i in range(0, len(labels), 5)], rotation=60, ha="right")
    ax.set_ylabel("Annual cost [million yen]")
    ax.set_xlabel("Historical peak / remaining months / target [kW]")
    ax.set_title("Cost breakdown for feasible fixed-target cases")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figures / "cost_breakdown_all_cases.png", dpi=180)
    plt.close(fig)

    all_synthetic = results[
        (results["scenario_type"] == "synthetic")
        & results["demand_target_kW"].notna()
    ].copy()
    feasibility = all_synthetic.pivot_table(
        index=["past_peak_kW", "remaining_months"],
        columns="demand_target_kW",
        values="feasible",
        aggfunc="first",
    )
    fig, ax = plt.subplots(figsize=(8.5, 6))
    ax.imshow(feasibility.astype(float).values, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(feasibility.columns)), [str(int(x)) for x in feasibility.columns])
    ax.set_yticks(
        range(len(feasibility.index)),
        [f"{int(p)} kW / {int(r)} mo" for p, r in feasibility.index],
    )
    ax.set_xlabel("Demand target [kW]")
    ax.set_title("Feasibility map (green: feasible, red: infeasible)")
    fig.tight_layout()
    fig.savefig(figures / "feasibility_map.png", dpi=180)
    plt.close(fig)

    best_targets.to_csv(output_dir / "best_fixed_target_by_condition.csv", index=False)

    baselines_only = synthetic[synthetic["demand_target_kW"].isna()].copy()
    minimum_cost = baselines_only["annual_total_cost_yen"].min()
    baselines_only["history_cost_increase_yen"] = (
        baselines_only["annual_total_cost_yen"] - minimum_cost
    )
    history_heat = baselines_only.pivot(
        index="past_peak_kW",
        columns="remaining_months",
        values="history_cost_increase_yen",
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    image = ax.imshow(history_heat.values, cmap="Blues", aspect="auto")
    ax.set_xticks(
        range(len(history_heat.columns)), [str(int(x)) for x in history_heat.columns]
    )
    ax.set_yticks(
        range(len(history_heat.index)), [str(int(x)) for x in history_heat.index]
    )
    ax.set_xlabel("Months until historical peak expires")
    ax.set_ylabel("Historical peak [kW]")
    ax.set_title("Cost impact of demand history vs minimum scenario [yen]")
    for y in range(len(history_heat.index)):
        for x in range(len(history_heat.columns)):
            ax.text(
                x,
                y,
                f"{history_heat.iloc[y, x] / 1000:,.0f}k",
                ha="center",
                va="center",
            )
    fig.colorbar(image, ax=ax, label="Annual cost increase [yen]")
    fig.tight_layout()
    fig.savefig(figures / "history_cost_heatmap.png", dpi=180)
    plt.close(fig)


def select_representative_cases(results: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    feasible = results[
        (results["scenario_type"] == "synthetic")
        & results["feasible"]
        & results["demand_target_kW"].notna()
    ].copy()
    baselines = results[
        (results["scenario_type"] == "synthetic")
        & results["feasible"]
        & results["demand_target_kW"].isna()
    ][["past_peak_kW", "remaining_months", "annual_total_cost_yen", "annual_max_grid_purchase_kW"]]
    baselines = baselines.rename(
        columns={
            "annual_total_cost_yen": "baseline_total_cost_yen",
            "annual_max_grid_purchase_kW": "baseline_max_grid_kW",
        }
    )
    feasible = feasible.merge(baselines, on=["past_peak_kW", "remaining_months"])
    feasible["cost_change_yen"] = feasible["annual_total_cost_yen"] - feasible["baseline_total_cost_yen"]
    feasible["peak_reduction_kW"] = feasible["baseline_max_grid_kW"] - feasible["annual_max_grid_purchase_kW"]

    selected: list[tuple[str, pd.Series]] = []
    min_peak, max_peak = feasible["past_peak_kW"].min(), feasible["past_peak_kW"].max()
    min_remaining = feasible["remaining_months"].min()
    max_remaining = feasible["remaining_months"].max()
    corners = (
        ("low_peak_short_residual", min_peak, min_remaining),
        ("low_peak_long_residual", min_peak, max_remaining),
        ("high_peak_short_residual", max_peak, min_remaining),
        ("high_peak_long_residual", max_peak, max_remaining),
    )
    for reason, peak, remaining in corners:
        candidates = feasible[
            (feasible["past_peak_kW"] == peak)
            & (feasible["remaining_months"] == remaining)
        ].sort_values("demand_target_kW")
        if not candidates.empty:
            selected.append((reason, candidates.iloc[0]))

    infeasible = results[
        (results["scenario_type"] == "synthetic")
        & (~results["feasible"])
        & results["demand_target_kW"].notna()
    ]
    rows = []
    seen = set()
    for reason, row in selected:
        if row["case_id"] in seen:
            continue
        seen.add(row["case_id"])
        item = row.to_dict()
        item["selection_reason"] = reason
        rows.append(item)
    if len(rows) < 4:
        candidates = feasible.sort_values(
            ["remaining_months", "past_peak_kW", "demand_target_kW"],
            ascending=[True, False, True],
        )
        for _, row in candidates.iterrows():
            if row["case_id"] in seen:
                continue
            seen.add(row["case_id"])
            item = row.to_dict()
            item["selection_reason"] = "coverage_of_experiment_matrix"
            rows.append(item)
            if len(rows) >= 4:
                break
    if not infeasible.empty:
        row = infeasible.sort_values("demand_target_kW").iloc[0].to_dict()
        row["selection_reason"] = "infeasible_strict_target"
        rows.append(row)
    representatives = pd.DataFrame(rows)
    representatives.to_csv(output_dir / "representative_cases.csv", index=False)
    make_representative_plots(representatives, output_dir)
    return representatives


def make_representative_plots(representatives: pd.DataFrame, output_dir: Path) -> None:
    figures = output_dir / "figures" / "representative_cases"
    figures.mkdir(parents=True, exist_ok=True)
    for row in representatives.itertuples():
        if not bool(row.feasible):
            continue
        case_dir = output_dir / "cases" / row.case_id
        timeseries = pd.read_csv(case_dir / "timeseries.csv.gz")
        timeseries["timestamp"] = pd.to_datetime(timeseries["timestamp"])
        monthly = pd.read_csv(case_dir / "monthly.csv")
        peak_time = timeseries.loc[timeseries["grid_purchase_kW"].idxmax(), "timestamp"]
        window = timeseries[
            (timeseries["timestamp"] >= peak_time - pd.Timedelta(hours=36))
            & (timeseries["timestamp"] <= peak_time + pd.Timedelta(hours=36))
        ]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
        ax1.plot(window["timestamp"], window["grid_purchase_kW"], label="Grid purchase", lw=1.8)
        if pd.notna(row.demand_target_kW):
            ax1.axhline(row.demand_target_kW, color="tab:red", ls="--", label="Demand target")
        ax1.plot(window["timestamp"], window["demand_kW"], color="0.65", lw=0.9, label="Demand")
        ax1.set_ylabel("Power [kW]")
        ax1.legend(ncol=3, fontsize=8)
        ax1.grid(alpha=0.25)
        ax2.plot(window["timestamp"], window["soc_kWh"], color="tab:green", label="SOC")
        ax2.set_ylabel("SOC [kWh]")
        ax2.set_xlabel("Timestamp")
        ax2.grid(alpha=0.25)
        fig.suptitle(f"{row.case_id}: 72 hours around maximum grid purchase")
        fig.tight_layout()
        fig.savefig(figures / f"{row.case_id}_peak_72h.png", dpi=180)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(9, 4.5))
        x = np.arange(len(monthly))
        ax.plot(x, monthly["contract_power_kW"], marker="o", label="Contract power")
        ax.plot(x, monthly["monthly_peak_kW"], marker="s", label="Monthly grid peak")
        ax.set_xticks(x, monthly["month"], rotation=45, ha="right")
        ax.set_ylabel("Power [kW]")
        ax.set_title(f"{row.case_id}: monthly contract power and peak")
        ax.grid(alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(figures / f"{row.case_id}_monthly_contract.png", dpi=180)
        plt.close(fig)


def run_self_test() -> None:
    past = pd.date_range("2025-01-01", "2025-12-31 23:30", freq="30min")
    future = past + pd.DateOffset(years=1)
    for remaining in REMAINING_MONTHS:
        values, peak_month, expiry_month = synthetic_past_monthly_peaks(
            past, future, 180.0, remaining
        )
        included = months_containing_peak(future, peak_month)
        assert len(included) == remaining, (remaining, included)
        assert included[-1] + 1 == expiry_month
        assert values[peak_month] == 180.0
        assert all(value == 100.0 for month, value in values.items() if month != peak_month)
    print("Experiment self-test passed: peak residual months are correct.")


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return

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

    cases = []
    for peak_kw in PEAKS_KW:
        for remaining in REMAINING_MONTHS:
            monthly_peaks, peak_month, expiry_month = synthetic_past_monthly_peaks(
                past_df.index, future_df.index, peak_kw, remaining
            )
            for target_kw in TARGETS_KW:
                metadata = {
                    "case_id": scenario_id(peak_kw, remaining, target_kw),
                    "scenario_type": "synthetic",
                    "past_peak_kW": peak_kw,
                    "remaining_months": remaining,
                    "demand_target_kW": target_kw,
                    "past_peak_month": str(peak_month),
                    "expiry_month": str(expiry_month),
                    "other_past_month_peak_kW": BASE_PAST_PEAK_KW,
                    "past_grid_source": "controlled monthly peak scenario",
                }
                cases.append((metadata, monthly_peaks))

    real_monthly_peaks = {
        month: float(
            max(
                past_grid[i]
                for i, timestamp in enumerate(past_df.index)
                if timestamp.to_period("M") == month
            )
        )
        for month in sorted(past_df.index.to_period("M").unique())
    }
    for target_kw in TARGETS_KW:
        metadata = {
            "case_id": f"actual_reference_target{target_label(target_kw)}",
            "scenario_type": "actual_reference",
            "past_peak_kW": max(real_monthly_peaks.values()),
            "remaining_months": None,
            "demand_target_kW": target_kw,
            "past_peak_month": None,
            "expiry_month": None,
            "other_past_month_peak_kW": None,
            "past_grid_source": past_source,
        }
        cases.append((metadata, real_monthly_peaks))

    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    summaries = []
    scenario_baselines: dict[tuple, dict] = {}
    total = len(cases)
    for number, (metadata, monthly_peaks) in enumerate(cases, 1):
        print(f"[{number}/{total}] {metadata['case_id']}", flush=True)
        scenario_key = (
            metadata["scenario_type"],
            metadata["past_peak_kW"],
            metadata["remaining_months"],
        )
        baseline = scenario_baselines.get(scenario_key)
        if (
            baseline is not None
            and baseline.get("feasible")
            and metadata["demand_target_kW"] is not None
            and metadata["demand_target_kW"]
            >= baseline["annual_max_grid_purchase_kW"] - 1e-6
        ):
            summary = clone_nonbinding_target_case(
                output_dir, baseline, metadata, args.overwrite
            )
        else:
            summary = run_case(
                output_dir,
                past_df,
                future_df,
                past_grid,
                monthly_peaks,
                battery,
                tariff,
                args.time_limit,
                metadata,
                args.overwrite,
            )
        if metadata["demand_target_kW"] is None:
            scenario_baselines[scenario_key] = summary
        summaries.append(summary)
        pd.DataFrame(summaries).to_csv(output_dir / "all_results_partial.csv", index=False)

    results = pd.DataFrame(summaries)
    results.to_csv(output_dir / "all_results.csv", index=False)
    with open(output_dir / "experiment_config.json", "w", encoding="utf-8") as stream:
        json.dump(
            {
                "past_peaks_kW": PEAKS_KW,
                "remaining_months": REMAINING_MONTHS,
                "demand_targets_kW": TARGETS_KW,
                "other_past_month_peak_kW": BASE_PAST_PEAK_KW,
                "terminal_soc_equals_initial": True,
                "charge_discharge_exclusivity_binary": True,
                "basic_rate_yen_per_kw_month": tariff.basic_rate_yen_per_kw_month,
                "energy_rate_yen_per_kWh": tariff.energy_rate_fallback_yen_per_kwh,
                "number_of_synthetic_cases": 96,
                "number_of_actual_reference_cases": 6,
                "pyscipopt_version": "5.5.0",
                "scip_version": "9.2.1",
                "reproduction_command": "2026_Research/.venv/bin/python 2026_Research/src/run_demand_target_experiments.py --output-dir 2026_Research/results/demand_target_sensitivity --time-limit 300 --overwrite",
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )
    if len(results) >= 96:
        make_plots(results, output_dir)
        select_representative_cases(results, output_dir)
    print(f"Results: {output_dir}")


if __name__ == "__main__":
    sys.exit(main())
