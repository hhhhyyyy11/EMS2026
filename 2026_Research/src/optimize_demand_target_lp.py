# -*- coding: utf-8 -*-
"""Demand-target MILP model with monthly rolling demand-charge variables.

This script is intentionally separate from optimize_LP.py.  It keeps the
existing annual-peak model untouched and builds a model whose demand charge is
based on monthly target variables constrained by the current month plus the
previous 11 months.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)


DELTA_T_HOURS = 0.5


@dataclass(frozen=True)
class BatteryParams:
    capacity_kwh: float
    charge_limit_kw: float
    discharge_limit_kw: float
    charge_efficiency: float
    discharge_efficiency: float
    initial_soc_ratio: float

    @property
    def initial_soc_kwh(self) -> float:
        return self.capacity_kwh * self.initial_soc_ratio

    @property
    def soc_min_kwh(self) -> float:
        return self.capacity_kwh * 0.05

    @property
    def soc_max_kwh(self) -> float:
        return self.capacity_kwh * 0.95


@dataclass(frozen=True)
class TariffParams:
    basic_rate_yen_per_kw_month: float
    energy_rate_fallback_yen_per_kwh: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MILP optimization with rolling contract power and an optional demand target."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(ROOT_DIR, "config.json"),
        help="Path to config.json",
    )
    parser.add_argument("--sheet", default="30分値", help="Excel sheet name")
    parser.add_argument(
        "--output-dir",
        default=os.path.join(ROOT_DIR, "results", "demand_target_lp"),
        help="Directory for CSV/JSON outputs",
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=1800.0,
        help="SCIP time limit in seconds",
    )
    parser.add_argument(
        "--basic-rate",
        type=float,
        default=2829.60 * 0.85,
        help="Monthly demand charge rate [yen/kW/month], including power-factor adjustment",
    )
    parser.add_argument(
        "--reuse-year1-as-year2",
        action="store_true",
        default=True,
        help="Use the loaded one-year data both as past actual data and optimization-year data",
    )
    parser.add_argument(
        "--past-grid-source",
        choices=["lp_results", "net_demand"],
        default="lp_results",
        help="Source for fixed Year 1 grid purchase values",
    )
    parser.add_argument(
        "--past-grid-csv",
        default=os.path.join(
            ROOT_DIR, "results", "lp_baseline", "dynamic_lp_results_minimize_total_cost.csv"
        ),
        help="CSV containing prior LP results with an sBY column",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run small structural checks without loading project data",
    )
    parser.add_argument(
        "--demand-target-kw",
        type=float,
        default=None,
        help="Optional operational upper bound on every 30-minute grid purchase [kW]",
    )
    parser.add_argument(
        "--no-terminal-soc",
        action="store_true",
        help="Do not require final SOC to equal initial SOC (not recommended for comparisons)",
    )
    return parser.parse_args()


def load_project_data(config_path: str, sheet_name: str):
    from Shared import data_loader

    config = data_loader.load_config(config_path)
    df = data_loader.get_simulation_data(config_path, sheet_name=sheet_name)
    return config, df


def battery_params_from_config(config: dict) -> BatteryParams:
    battery_config = config.get("battery", {})
    return BatteryParams(
        capacity_kwh=float(battery_config.get("capacity_kWh", 860.0)),
        charge_limit_kw=float(battery_config.get("charge_limit_kW", 400.0)),
        discharge_limit_kw=float(battery_config.get("discharge_limit_kW", 400.0)),
        charge_efficiency=float(battery_config.get("charge_efficiency", 0.98)),
        discharge_efficiency=float(battery_config.get("discharge_efficiency", 0.98)),
        initial_soc_ratio=float(battery_config.get("initial_soc_ratio", 0.5)),
    )


def make_two_year_data(df_one_year):
    """Return (past_df, future_df).

    The current repository has one common year of demand/PV/price data.  Until a
    separate past-actual file is prepared, the same data are used for both years
    and the future index is shifted by one year.
    """
    import pandas as pd

    if not isinstance(df_one_year.index, pd.DatetimeIndex):
        raise TypeError("Simulation data must have a DatetimeIndex.")
    if df_one_year.empty:
        raise ValueError("Simulation data is empty.")

    past_df = df_one_year.copy()
    future_df = df_one_year.copy()
    future_df.index = future_df.index + pd.DateOffset(years=1)
    return past_df, future_df


def estimate_past_grid_purchase_kw(past_df) -> List[float]:
    """Estimate past S_BY constants from measured demand and PV.

    If real historical grid-purchase data become available, replace this
    calculation with that measured series.  For the current data shape, the best
    available proxy is net demand without battery dispatch.
    """
    values = (past_df["consumption_kW"] - past_df["pv_kW"]).clip(lower=0.0)
    return [float(x) for x in values.to_numpy()]


def load_lp_result_grid_purchase_kw(csv_path: str, expected_length: int) -> List[float]:
    import pandas as pd

    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"Past LP result CSV not found: {csv_path}. "
            "Run src/optimize_LP.py first, or use --past-grid-source net_demand."
        )
    df = pd.read_csv(csv_path)
    if "sBY" not in df.columns:
        raise KeyError(f"Expected column 'sBY' in {csv_path}.")
    if len(df) != expected_length:
        raise ValueError(
            f"Past LP result length mismatch: expected {expected_length}, got {len(df)}."
        )
    return [float(x) for x in df["sBY"].to_numpy()]


def get_past_grid_purchase_kw(
    past_df, source: str, lp_result_csv: str
) -> Tuple[List[float], str]:
    if source == "lp_results":
        return (
            load_lp_result_grid_purchase_kw(lp_result_csv, len(past_df)),
            f"LP result CSV ({lp_result_csv})",
        )
    return (
        estimate_past_grid_purchase_kw(past_df),
        "net demand estimate max(consumption - PV, 0)",
    )


def future_month_periods(future_index) -> List:
    periods = list(future_index.to_period("M").unique())
    periods.sort()
    return periods


def in_rolling_12_month_window(timestamp, target_period) -> bool:
    start_period = target_period - 11
    current_period = timestamp.to_period("M")
    return start_period <= current_period <= target_period


def build_reference_sets(past_index, future_index, target_months) -> Dict:
    """Build rolling 12-month reference sets for each future month.

    Returns a mapping:
        month -> {"past": [past positions], "future": [future positions]}
    """
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


def month_label(period) -> str:
    return str(period)


def solve_demand_target_lp(
    past_df,
    future_df,
    past_grid_purchase_kw: List[float],
    battery: BatteryParams,
    tariff: TariffParams,
    time_limit: float,
    demand_target_kw: float | None = None,
    past_monthly_peaks: Dict | None = None,
    enforce_terminal_soc: bool = True,
):
    from pyscipopt import Model, quicksum

    if len(past_df) != len(past_grid_purchase_kw):
        raise ValueError("past_grid_purchase_kw length must match past_df length.")

    k_future = len(future_df)
    if k_future == 0:
        raise ValueError("future_df is empty.")

    future_months = future_month_periods(future_df.index)
    reference_sets = build_reference_sets(past_df.index, future_df.index, future_months)
    future_step_month = [timestamp.to_period("M") for timestamp in future_df.index]
    past_monthly_peaks = past_monthly_peaks or {
        month: max(
            past_grid_purchase_kw[i]
            for i, timestamp in enumerate(past_df.index)
            if timestamp.to_period("M") == month
        )
        for month in sorted(past_df.index.to_period("M").unique())
    }

    demand_kw = [float(x) for x in future_df["consumption_kW"].to_numpy()]
    pv_available_kw = [max(0.0, float(x)) for x in future_df["pv_kW"].to_numpy()]
    prices = [
        float(x) if x == x else tariff.energy_rate_fallback_yen_per_kwh
        for x in future_df["price_yen_per_kWh"].to_numpy()
    ]

    model = Model("DemandTarget_LP_30min")
    model.setParam("limits/time", float(time_limit))
    model.hideOutput()

    s_by = {k: model.addVar(vtype="C", name=f"sBY_{k}", lb=0.0) for k in range(k_future)}
    s_sl = {k: model.addVar(vtype="C", name=f"sSL_{k}", lb=0.0) for k in range(k_future)}
    pv_used = {k: model.addVar(vtype="C", name=f"gP2_{k}", lb=0.0) for k in range(k_future)}
    waste = {k: model.addVar(vtype="C", name=f"waste_{k}", lb=0.0) for k in range(k_future)}

    soc = {k: model.addVar(vtype="C", name=f"bF_{k}", lb=0.0) for k in range(k_future)}
    charge_input = {
        k: model.addVar(vtype="C", name=f"xFC1_{k}", lb=0.0) for k in range(k_future)
    }
    charge_stored = {
        k: model.addVar(vtype="C", name=f"xFC2_{k}", lb=0.0) for k in range(k_future)
    }
    discharge_from_battery = {
        k: model.addVar(vtype="C", name=f"xFD1_{k}", lb=0.0) for k in range(k_future)
    }
    discharge_used = {
        k: model.addVar(vtype="C", name=f"xFD2_{k}", lb=0.0) for k in range(k_future)
    }
    charge_mode = {
        k: model.addVar(vtype="B", name=f"z_charge_{k}") for k in range(k_future)
    }
    monthly_peak = {
        month: model.addVar(vtype="C", name=f"monthly_peak_{month_label(month)}", lb=0.0)
        for month in future_months
    }
    contract_power = {
        month: model.addVar(vtype="C", name=f"contract_power_{month_label(month)}", lb=0.0)
        for month in future_months
    }

    for k in range(k_future):
        model.addCons(
            pv_used[k]
            + s_by[k]
            - s_sl[k]
            - charge_input[k]
            + discharge_used[k]
            - demand_kw[k]
            - waste[k]
            == 0.0
        )
        model.addCons(pv_used[k] <= pv_available_kw[k])
        model.addCons(s_sl[k] == 0.0)
        if demand_target_kw is not None:
            model.addCons(s_by[k] <= float(demand_target_kw))

        if battery.capacity_kwh <= 0.0:
            model.addCons(soc[k] == 0.0)
            model.addCons(charge_input[k] == 0.0)
            model.addCons(charge_stored[k] == 0.0)
            model.addCons(discharge_from_battery[k] == 0.0)
            model.addCons(discharge_used[k] == 0.0)
        else:
            if k == 0:
                previous_soc = battery.initial_soc_kwh
            else:
                previous_soc = soc[k - 1]
            model.addCons(
                soc[k]
                == previous_soc
                + DELTA_T_HOURS * charge_stored[k]
                - DELTA_T_HOURS * discharge_from_battery[k]
            )
            model.addCons(soc[k] >= battery.soc_min_kwh)
            model.addCons(soc[k] <= battery.soc_max_kwh)

            model.addCons(charge_stored[k] == battery.charge_efficiency * charge_input[k])
            model.addCons(
                discharge_used[k]
                == battery.discharge_efficiency * discharge_from_battery[k]
            )
            model.addCons(charge_stored[k] <= battery.charge_limit_kw)
            model.addCons(discharge_from_battery[k] <= battery.discharge_limit_kw)
            max_charge_input_kw = battery.charge_limit_kw / battery.charge_efficiency
            model.addCons(charge_input[k] <= max_charge_input_kw * charge_mode[k])
            model.addCons(
                discharge_from_battery[k]
                <= battery.discharge_limit_kw * (1 - charge_mode[k])
            )

    if enforce_terminal_soc and battery.capacity_kwh > 0.0:
        model.addCons(soc[k_future - 1] == battery.initial_soc_kwh)

    for k, month in enumerate(future_step_month):
        model.addCons(s_by[k] <= monthly_peak[month])

    past_periods = sorted(past_monthly_peaks)
    for month in future_months:
        window_start = month - 11
        for past_month in past_periods:
            if window_start <= past_month <= month:
                model.addCons(float(past_monthly_peaks[past_month]) <= contract_power[month])
        for future_month in future_months:
            if window_start <= future_month <= month:
                model.addCons(monthly_peak[future_month] <= contract_power[month])

    basic_cost = quicksum(
        tariff.basic_rate_yen_per_kw_month * contract_power[month] for month in future_months
    )
    energy_cost = quicksum(
        prices[k] * s_by[k] * DELTA_T_HOURS for k in range(k_future)
    )
    model.setObjective(basic_cost + energy_cost, "minimize")

    start = time.perf_counter()
    model.optimize()
    elapsed = time.perf_counter() - start

    status = model.getStatus()
    if model.getNSols() == 0:
        return {
            "model": model,
            "status": str(status),
            "feasible": False,
            "elapsed_seconds": elapsed,
            "gap": None,
            "demand_target_kw": demand_target_kw,
            "enforce_terminal_soc": enforce_terminal_soc,
        }

    s_by_values = [model.getVal(s_by[k]) for k in range(k_future)]
    soc_values = [model.getVal(soc[k]) for k in range(k_future)]
    pv_used_values = [model.getVal(pv_used[k]) for k in range(k_future)]
    charge_values = [model.getVal(charge_input[k]) for k in range(k_future)]
    discharge_values = [model.getVal(discharge_used[k]) for k in range(k_future)]
    discharge_from_values = [
        model.getVal(discharge_from_battery[k]) for k in range(k_future)
    ]
    charge_stored_values = [model.getVal(charge_stored[k]) for k in range(k_future)]
    monthly_peak_values = {month: model.getVal(monthly_peak[month]) for month in future_months}
    contract_power_values = {
        month: model.getVal(contract_power[month]) for month in future_months
    }

    return {
        "model": model,
        "status": status,
        "feasible": True,
        "elapsed_seconds": elapsed,
        "future_months": future_months,
        "reference_sets": reference_sets,
        "s_by": s_by_values,
        "soc": soc_values,
        "pv_used": pv_used_values,
        "charge_input": charge_values,
        "charge_stored": charge_stored_values,
        "discharge_from_battery": discharge_from_values,
        "discharge_used": discharge_values,
        "monthly_peak": monthly_peak_values,
        "contract_power": contract_power_values,
        "s_bar": contract_power_values,
        "demand_target_kw": demand_target_kw,
        "enforce_terminal_soc": enforce_terminal_soc,
        "past_monthly_peaks": {month_label(k): float(v) for k, v in past_monthly_peaks.items()},
        "prices": prices,
        "objective_value": model.getObjVal(),
        "gap": model.getGap() if status != "optimal" else 0.0,
    }


def summarize_monthly(future_df, result: dict, tariff: TariffParams):
    import pandas as pd

    df = pd.DataFrame(
        {
            "timestamp": future_df.index,
            "sBY": result["s_by"],
            "electricity_price": result["prices"],
        }
    )
    df["month"] = df["timestamp"].dt.to_period("M")

    rows = []
    for month in result["future_months"]:
        month_df = df[df["month"] == month]
        energy_cost = float(
            (month_df["electricity_price"] * month_df["sBY"] * DELTA_T_HOURS).sum()
        )
        monthly_peak = float(month_df["sBY"].max()) if not month_df.empty else 0.0
        contract_power = float(result["contract_power"][month])
        basic_cost = tariff.basic_rate_yen_per_kw_month * contract_power
        rows.append(
            {
                "month": month_label(month),
                "demand_target_kW": result["demand_target_kw"],
                "contract_power_kW": contract_power,
                "monthly_peak_kW": monthly_peak,
                "basic_cost_yen": basic_cost,
                "energy_cost_yen": energy_cost,
                "total_cost_yen": basic_cost + energy_cost,
                "past_reference_steps": len(result["reference_sets"][month]["past"]),
                "future_reference_steps": len(result["reference_sets"][month]["future"]),
            }
        )
    return rows


def write_outputs(output_dir: str, future_df, result: dict, monthly_rows: List[dict]):
    import pandas as pd

    os.makedirs(output_dir, exist_ok=True)

    timeseries_df = pd.DataFrame(
        {
            "timestamp": future_df.index,
            "pv_available_kW": future_df["pv_kW"].to_numpy(),
            "pv_used_kW": result["pv_used"],
            "demand_kW": future_df["consumption_kW"].to_numpy(),
            "sBY_kW": result["s_by"],
            "charge_input_kW": result["charge_input"],
            "charge_stored_kW": result["charge_stored"],
            "discharge_from_battery_kW": result["discharge_from_battery"],
            "discharge_used_kW": result["discharge_used"],
            "soc_kWh": result["soc"],
            "electricity_price_yen_per_kWh": result["prices"],
        }
    )
    timeseries_path = os.path.join(output_dir, "demand_target_timeseries.csv")
    timeseries_df.to_csv(timeseries_path, index=False)

    monthly_df = pd.DataFrame(monthly_rows)
    monthly_path = os.path.join(output_dir, "demand_target_monthly_summary.csv")
    monthly_df.to_csv(monthly_path, index=False)

    annual_energy_cost = float(monthly_df["energy_cost_yen"].sum())
    annual_basic_cost = float(monthly_df["basic_cost_yen"].sum())
    annual_total_cost = float(monthly_df["total_cost_yen"].sum())
    summary = {
        "status": result["status"],
        "objective_value_yen": float(result["objective_value"]),
        "gap": float(result["gap"]),
        "elapsed_seconds": float(result["elapsed_seconds"]),
        "annual_energy_cost_yen": annual_energy_cost,
        "annual_basic_cost_yen": annual_basic_cost,
        "annual_total_cost_yen": annual_total_cost,
        "annual_max_grid_purchase_kW": float(max(result["s_by"])),
        "demand_target_kW": result["demand_target_kw"],
        "max_monthly_contract_power_kW": float(
            max(row["contract_power_kW"] for row in monthly_rows)
        ),
        "initial_soc_kWh": float(result["soc"][0] - DELTA_T_HOURS * result["charge_stored"][0] + DELTA_T_HOURS * result["discharge_from_battery"][0]),
        "final_soc_kWh": float(result["soc"][-1]),
        "battery_throughput_kWh": float(
            DELTA_T_HOURS * sum(result["charge_input"])
            + DELTA_T_HOURS * sum(result["discharge_used"])
        ),
        "pv_used_kWh": float(DELTA_T_HOURS * sum(result["pv_used"])),
        "pv_curtailment_kWh": float(
            DELTA_T_HOURS * (sum(future_df["pv_kW"].to_numpy()) - sum(result["pv_used"]))
        ),
        "target_hit_count": int(
            sum(
                1
                for value in result["s_by"]
                if result["demand_target_kw"] is not None
                and abs(value - result["demand_target_kw"]) <= 1e-4
            )
        ),
        "simultaneous_charge_discharge_count": int(
            sum(
                1
                for charge, discharge in zip(result["charge_input"], result["discharge_used"])
                if charge > 1e-6 and discharge > 1e-6
            )
        ),
    }
    summary_path = os.path.join(output_dir, "demand_target_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return timeseries_path, monthly_path, summary_path, summary


def run_self_test() -> None:
    class FakePeriod:
        def __init__(self, year: int, month: int):
            absolute = year * 12 + (month - 1)
            self.year = absolute // 12
            self.month = absolute % 12 + 1
            self.absolute = absolute

        def __sub__(self, months: int):
            absolute = self.absolute - months
            return FakePeriod(absolute // 12, absolute % 12 + 1)

        def __lt__(self, other):
            return self.absolute < other.absolute

        def __le__(self, other):
            return self.absolute <= other.absolute

        def __eq__(self, other):
            return isinstance(other, FakePeriod) and self.absolute == other.absolute

        def __hash__(self):
            return hash(self.absolute)

        def __str__(self):
            return f"{self.year:04d}-{self.month:02d}"

    class FakeTimestamp:
        def __init__(self, year: int, month: int):
            self.period = FakePeriod(year, month)

        def to_period(self, freq: str):
            if freq != "M":
                raise ValueError("Self-test only supports monthly periods.")
            return self.period

    def repeated_months(year: int, days_by_month: Dict[int, int]) -> List[FakeTimestamp]:
        values: List[FakeTimestamp] = []
        for month, days in days_by_month.items():
            values.extend(FakeTimestamp(year, month) for _ in range(days * 48))
        return values

    days_2024 = {
        1: 31,
        2: 29,
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 30,
    }
    days_2025 = {
        1: 31,
        2: 28,
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 30,
    }
    index_past = repeated_months(2024, days_2024)
    index_future = repeated_months(2025, days_2025)
    months = [FakePeriod(2025, month) for month in range(1, 13)]
    refs = build_reference_sets(index_past, index_future, months)

    january = FakePeriod(2025, 1)
    june = FakePeriod(2025, 6)
    assert january in refs
    assert june in refs
    assert len(refs[january]["future"]) == 48 * 31
    assert len(refs[january]["past"]) == 48 * 334
    assert len(refs[june]["future"]) == 48 * (31 + 28 + 31 + 30 + 31 + 30)

    monthly_rows = [
        {
            "month": f"2025-{m:02d}",
            "demand_target_kW": 100.0 + m,
            "monthly_peak_kW": 90.0 + m,
            "basic_cost_yen": 2405.16 * (100.0 + m),
            "energy_cost_yen": 10.0,
            "total_cost_yen": 2405.16 * (100.0 + m) + 10.0,
            "past_reference_steps": 0,
            "future_reference_steps": 0,
        }
        for m in range(1, 13)
    ]
    assert len(monthly_rows) == 12
    print("Self-test passed.")


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return

    config, df_one_year = load_project_data(args.config, args.sheet)
    battery = battery_params_from_config(config)
    tariff = TariffParams(
        basic_rate_yen_per_kw_month=float(args.basic_rate),
        energy_rate_fallback_yen_per_kwh=float(
            config.get("fixed_price_yen_per_kWh", 21.51)
        ),
    )

    past_df, future_df = make_two_year_data(df_one_year)
    past_grid_purchase_kw, past_grid_source_label = get_past_grid_purchase_kw(
        past_df, args.past_grid_source, args.past_grid_csv
    )

    print("Demand-target MILP")
    print(f"Past actual steps: {len(past_df)}")
    print(f"Optimization-year steps: {len(future_df)}")
    print(f"Past grid source: {past_grid_source_label}")
    print(f"Monthly basic rate: {tariff.basic_rate_yen_per_kw_month:.2f} yen/kW/month")
    print("Solving with SCIP...")

    result = solve_demand_target_lp(
        past_df=past_df,
        future_df=future_df,
        past_grid_purchase_kw=past_grid_purchase_kw,
        battery=battery,
        tariff=tariff,
        time_limit=args.time_limit,
        demand_target_kw=args.demand_target_kw,
        enforce_terminal_soc=not args.no_terminal_soc,
    )
    if not result["feasible"]:
        print(f"Status: {result['status']}")
        print("No feasible solution for the specified demand target.")
        return
    monthly_rows = summarize_monthly(future_df, result, tariff)
    paths = write_outputs(args.output_dir, future_df, result, monthly_rows)
    timeseries_path, monthly_path, summary_path, summary = paths

    print(f"Status: {summary['status']}")
    print(f"Objective: {summary['objective_value_yen']:.0f} yen")
    print(f"Annual energy cost: {summary['annual_energy_cost_yen']:.0f} yen")
    print(f"Annual basic cost: {summary['annual_basic_cost_yen']:.0f} yen")
    print(f"Annual total cost: {summary['annual_total_cost_yen']:.0f} yen")
    print(f"Annual max grid purchase: {summary['annual_max_grid_purchase_kW']:.2f} kW")
    print(f"Demand target: {summary['demand_target_kW']} kW")
    print(f"Max monthly contract power: {summary['max_monthly_contract_power_kW']:.2f} kW")
    print(f"Timeseries CSV: {timeseries_path}")
    print(f"Monthly summary CSV: {monthly_path}")
    print(f"Summary JSON: {summary_path}")


if __name__ == "__main__":
    main()
