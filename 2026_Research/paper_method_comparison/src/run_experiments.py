#!/usr/bin/env python3
"""Run E1 day cases and save reproducible results without overwriting runs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from solve_dp import solve_dp
from solve_math_program import solve_math_program

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
FIELDS = ["case_id", "method", "grid_count", "replicate", "phase", "status", "solver_status", "objective_yen", "maximum_purchased_power_kW", "basic_charge_yen", "energy_charge_yen", "cost_difference_yen", "relative_difference", "solve_time_seconds", "total_time_seconds", "peak_memory_mib", "maximum_constraint_violation", "evaluation_status", "best_bound_yen", "relative_gap", "run_id", "result_directory", "message"]


class PeakRSS:
    """Sample resident memory during a solve, including native solver allocations."""
    def __init__(self):
        try:
            import psutil
            self.psutil = psutil
            self.peak = 0
        except ImportError:
            self.psutil, self.peak = None, None
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        if self.psutil:
            proc = self.psutil.Process()
            def sample():
                while not self.stop.is_set():
                    try:
                        self.peak = max(self.peak, proc.memory_info().rss)
                    except self.psutil.Error:
                        pass
                    self.stop.wait(0.02)
            self.thread = threading.Thread(target=sample, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join()

    def mib(self):
        return None if self.peak is None else self.peak / (1024 * 1024)


def dump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_problem(config_path: Path, config: dict[str, Any]):
    inp = config["input"]
    source = (config_path.parent / inp["energy_excel_path"]).resolve()
    frame = pd.read_excel(source, sheet_name=inp["energy_sheet"])
    load_col = inp["value_columns"]["load_energy"]
    pv_col = inp["value_columns"]["pv_energy"]
    numeric_load = pd.to_numeric(frame[load_col], errors="coerce")
    numeric_pv = pd.to_numeric(frame[pv_col], errors="coerce")
    usable = numeric_load.notna() & numeric_pv.notna()
    frame = frame.loc[usable].copy()
    frame[load_col] = numeric_load.loc[usable]
    frame[pv_col] = numeric_pv.loc[usable]
    ds = pd.to_datetime(frame[inp["timestamp_columns"]["date"]], errors="raise").dt.date
    ts = frame[inp["timestamp_columns"]["time"]]
    stamps = []
    for d, t in zip(ds, ts):
        offset = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second, microseconds=t.microsecond) if hasattr(t, "hour") else timedelta(days=float(t))
        stamps.append(datetime.combine(d, datetime.min.time()) + offset)
    frame = frame.copy()
    frame["_timestamp"] = stamps
    start = datetime.fromisoformat(config["period"]["start"]).replace(tzinfo=None)
    end = datetime.fromisoformat(config["period"]["end_exclusive"]).replace(tzinfo=None)
    selected = frame[(frame._timestamp >= start) & (frame._timestamp < end)].sort_values("_timestamp")
    dt = float(config["period"]["time_step_hours"])
    source_dt = float(inp["source_interval_hours"])
    n = round((end - start).total_seconds() / (dt * 3600))
    aggregation_ratio = round(dt / source_dt)
    expected_source_rows = n * aggregation_ratio
    if len(selected) != expected_source_rows:
        raise ValueError(f"Expected {expected_source_rows} source rows; found {len(selected)}")
    epoch = datetime(1970, 1, 1)
    seconds_per_step = source_dt * 3600
    selected = selected.copy()
    selected["_timestamp"] = [epoch + timedelta(seconds=round((stamp - epoch).total_seconds() / seconds_per_step) * seconds_per_step)
                               for stamp in selected["_timestamp"]]
    source_load = pd.to_numeric(selected[load_col], errors="raise").astype(float).to_numpy() / source_dt
    source_pv = pd.to_numeric(selected[pv_col], errors="raise").astype(float).to_numpy() / source_dt
    if aggregation_ratio > 1:
        load = source_load.reshape(n, aggregation_ratio).mean(axis=1).tolist()
        pv = source_pv.reshape(n, aggregation_ratio).mean(axis=1).tolist()
        selected = selected.iloc[::aggregation_ratio].copy().reset_index(drop=True)
    else:
        load, pv = source_load.tolist(), source_pv.tolist()
    b = config["battery"]
    charge = config["basic_charge"]
    basic_rate = charge["monthly_yen_per_kW"] * charge["power_factor_multiplier"] * charge["months_per_year"] * (n * dt / charge["hours_per_year"])
    problem = {"time_step_hours": dt, "load_kW": load, "pv_available_kW": pv,
        "price_yen_per_kWh": [float(config["price"]["fixed_yen_per_kWh"])] * n,
        "battery_capacity_kWh": float(b["capacity_kWh"]), "charge_limit_kW_internal": float(b["charge_limit_kW_internal"]),
        "discharge_limit_kW_internal": float(b["discharge_limit_kW_internal"]), "charge_efficiency": float(b["charge_efficiency"]),
        "discharge_efficiency": float(b["discharge_efficiency"]), "soc_min_kWh": b["capacity_kWh"] * b["soc_min_ratio"],
        "soc_max_kWh": b["capacity_kWh"] * b["soc_max_ratio"], "initial_soc_kWh": b["capacity_kWh"] * b["initial_soc_ratio"],
        "terminal_soc_kWh": b["capacity_kWh"] * b["terminal_soc_ratio"], "basic_charge_yen_per_kW": basic_rate}
    return problem, selected, source


def environment(config_path: Path, source: Path, started: datetime) -> dict[str, Any]:
    try:
        import psutil
        mem = psutil.virtual_memory()
        memory = {"total_bytes": mem.total, "available_bytes": mem.available}
    except ImportError:
        memory = {"total_bytes": None, "available_bytes": None}
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
    except Exception:
        commit, dirty = None, None
    try:
        import pyscipopt
        scip = ".".join(map(str, (pyscipopt.scip.get_major_version(), pyscipopt.scip.get_minor_version(), pyscipopt.scip.get_tech_version())))
    except Exception:
        scip = None
    h = hashlib.sha256()
    with source.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return {"run_started_at": started.isoformat(), "git_commit": commit, "git_worktree_dirty": dirty,
        "os": platform.platform(), "machine": platform.machine(), "processor": platform.processor(), "cpu_count": os.cpu_count(),
        "memory": memory, "free_disk_bytes": shutil.disk_usage(ROOT).free, "python_version": platform.python_version(),
        "pandas_version": pd.__version__, "pyscipopt_version": getattr(sys.modules.get("pyscipopt"), "__version__", None),
        "scip_version": scip, "input_path": str(source), "input_sha256": h.hexdigest(), "config_path": str(config_path)}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    else:
        path.write_text("", encoding="utf-8")


def run_one(problem: dict[str, Any], frame: pd.DataFrame, source: Path, config: dict[str, Any], config_path: Path,
            result_root: Path, launch: datetime, method: str, grid: int | None, rep: int, period_label: str,
            experiment_id: str = "E1") -> dict[str, Any]:
    case = f"{experiment_id}-{period_label}-{method}{'-'+str(grid) if grid else ''}-r{rep}"
    phase = "initial" if rep == 0 else "prepared"
    now = datetime.now(JST)
    dest = result_root / f"{experiment_id}_{now.strftime('%Y%m%dT%H%M%S%z')}_{period_label}_{method}{'-'+str(grid) if grid else ''}-r{rep}"
    dest.mkdir(parents=True, exist_ok=False)
    effective = json.loads(json.dumps(config))
    effective["experiment"] = {"case_id": case, "method": method, "soc_grid_count": grid, "replicate": rep, "phase": phase}
    dump(dest / "config.json", effective)
    start_clock = time.perf_counter()
    with PeakRSS() as rss:
      try:
        if method == "dp":
            output = solve_dp(problem, soc_grid_count=grid, time_limit_seconds=config["solver"]["time_limit_seconds_per_case"], case_id=case)
        else:
            output = solve_math_program(problem, method=method, time_limit_seconds=config["solver"]["time_limit_seconds_per_case"],
                threads=config["solver"]["math_program"]["threads"], relative_mip_gap=config["solver"]["math_program"]["relative_mip_gap"], case_id=case)
        summary, trajectory, evaluation = output["summary"], output.get("trajectory"), output.get("evaluation")
        status = summary.get("status", "failed")
        if status == "success" and (not evaluation or evaluation.get("status") != "pass"):
            status = "failed"
            summary["message"] = "Independent evaluation did not pass."
      except Exception as exc:
        summary = {"schema_version": 1, "run_id": case, "experiment_id": "E1_initial", "method": method, "status": "failed",
            "objective_yen": None, "energy_charge_yen": None, "basic_charge_yen": None, "maximum_purchased_power_kW": None,
            "contract_equivalent_power_kW": None, "maximum_constraint_violation": None, "solve_time_seconds": None,
            "total_time_seconds": None, "peak_memory_mib": None, "message": f"{type(exc).__name__}: {exc}"}
        trajectory, evaluation, status = None, None, "failed"
        (dest / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
    elapsed = time.perf_counter() - start_clock
    summary.update({"run_id": case, "experiment_id": experiment_id, "status": status, "total_time_seconds": elapsed,
                    "peak_memory_mib": rss.mib() if rss.mib() is not None else summary.get("peak_memory_mib")})
    dump(dest / "summary.json", summary)
    if evaluation is not None:
        dump(dest / "evaluation.json", evaluation)
    trajectory_rows = []
    if trajectory is not None:
        for i in range(len(problem["load_kW"])):
            trajectory_rows.append({"timestamp": frame["_timestamp"].iloc[i].isoformat()+"+09:00", "load_kW": problem["load_kW"][i],
                "pv_available_kW": problem["pv_available_kW"][i], "price_yen_per_kWh": problem["price_yen_per_kWh"][i],
                "purchased_power_kW": trajectory["purchased_power_kW"][i], "pv_used_kW": trajectory["pv_used_kW"][i],
                "charge_power_kW_internal": trajectory["charge_power_kW_internal"][i], "discharge_power_kW_internal": trajectory["discharge_power_kW_internal"][i],
                "soc_start_kWh": trajectory["soc_kWh"][i], "soc_end_kWh": trajectory["soc_kWh"][i+1]})
    write_csv(dest / "trajectory.csv", trajectory_rows)
    (dest / "run.log").write_text(f"run_id={case}\nstarted_at={now.isoformat()}\nphase={phase}\nmethod={method}\nstatus={status}\nwall_seconds={elapsed:.9f}\nmessage={summary.get('message') or ''}\n", encoding="utf-8")
    dump(dest / "environment.json", environment(config_path, source, launch))
    return {"case_id": case, "method": method, "grid_count": grid, "replicate": rep, "phase": phase, "status": status,
        "solver_status": summary.get("solver_status"), "objective_yen": summary.get("objective_yen"),
        "maximum_purchased_power_kW": summary.get("maximum_purchased_power_kW"), "basic_charge_yen": summary.get("basic_charge_yen"),
        "energy_charge_yen": summary.get("energy_charge_yen"), "solve_time_seconds": summary.get("solve_time_seconds"),
        "total_time_seconds": elapsed, "peak_memory_mib": summary.get("peak_memory_mib"),
        "maximum_constraint_violation": summary.get("maximum_constraint_violation"), "evaluation_status": evaluation.get("status") if evaluation else None,
        "best_bound_yen": summary.get("best_bound_yen"), "relative_gap": summary.get("relative_gap"), "run_id": case,
        "result_directory": str(dest), "message": summary.get("message")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/common_problem.json")
    parser.add_argument("--experiment-id", default="E1")
    parser.add_argument("--identifier", default="day")
    parser.add_argument("--prepared-repeats", type=int, default=3)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--skip-preflight", action="store_true", help="use only with data prepared from the checked source interval")
    parser.add_argument("--only-preflight", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    launch = datetime.now(JST)
    if not args.skip_preflight:
        check = subprocess.run([sys.executable, str(ROOT / "src/check_run_setup.py"), "--config", str(config_path), "--experiment-id", args.experiment_id,
            "--identifier", args.identifier], cwd=ROOT, capture_output=True, text=True)
        if check.returncode:
            sys.stderr.write(check.stdout + check.stderr); return check.returncode
        if args.only_preflight:
            print(check.stdout); return 0
    problem, frame, source = read_problem(config_path, config)
    results_root = (config_path.parent / config["results"]["root_path"]).resolve()
    expdir = ROOT / f"experiments/{args.experiment_id}"; expdir.mkdir(parents=True, exist_ok=True)
    comparison_output = (args.comparison_output or (expdir / "comparison.csv")).resolve()
    report_output = (args.report_output or (expdir / "REPORT.md")).resolve()
    specs = [("lp", None), ("milp", None)] + [("dp", n) for n in config["dp"]["soc_grid_counts"]]
    rows = []
    for method, grid in specs:
        for rep in range(args.prepared_repeats + 1):
            row = run_one(problem, frame, source, config, config_path, results_root, launch, method, grid, rep, args.identifier, args.experiment_id)
            rows.append(row); print(f"{row['case_id']}: {row['status']} ({row['total_time_seconds']:.3f}s)", flush=True)
    costs = [r["objective_yen"] for r in rows if r["status"] == "success" and isinstance(r["objective_yen"], (int, float))]
    reference = min(costs) if costs else None
    idle_buy = [max(0.0, load - min(load, pv)) for load, pv in zip(problem["load_kW"], problem["pv_available_kW"])]
    idle_cost = sum(problem["price_yen_per_kWh"][i] * idle_buy[i] * problem["time_step_hours"] for i in range(len(idle_buy)))
    idle_cost += problem["basic_charge_yen_per_kW"] * max(idle_buy)
    for row in rows:
        value = row["objective_yen"]
        row["cost_difference_yen"] = value - reference if value is not None and reference is not None else None
        row["relative_difference"] = row["cost_difference_yen"] / reference if reference and row["cost_difference_yen"] is not None else None
    comparison_output.parent.mkdir(parents=True, exist_ok=True)
    with comparison_output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    mdrows = []
    for r in rows:
        cells = ["—" if r.get(k) is None else (f"{r[k]:.6g}" if isinstance(r[k], float) else str(r[k]).replace("|", "\\|")) for k in FIELDS]
        mdrows.append("| " + " | ".join(cells) + " |")
    ok, timeout, failed = (sum(r["status"] == s for r in rows) for s in ("success", "time_limit", "failed"))
    table_header = "| " + " | ".join(FIELDS) + " |"
    table_sep = "| " + " | ".join(["---"] * len(FIELDS)) + " |"
    period_start = datetime.fromisoformat(config["period"]["start"]).date().isoformat()
    period_end = (datetime.fromisoformat(config["period"]["end_exclusive"]) - timedelta(seconds=1)).date().isoformat()
    period_hours = len(problem["load_kW"]) * problem["time_step_hours"]
    report = [f"# {args.experiment_id}：{args.identifier}ケース比較", "", f"実行開始: {launch.isoformat()}", "", "## 条件", "",
        f"{period_start}〜{period_end}の{len(problem['load_kW'])}区間（{period_hours:g}時間、{config['period']['time_step_hours']:g}時間値）、固定価格{config['price']['fixed_yen_per_kWh']:g}円/kWh、蓄電池{config['battery']['capacity_kWh']:g} kWh・内部上限{config['battery']['charge_limit_kW_internal']:g} kW、初期/終端SOC {config['battery']['initial_soc_ratio']:.0%}。LP、MILP、{','.join(map(str, config['dp']['soc_grid_counts']))}点DPを各1回の初回実行と準備後{args.prepared_repeats}回で計{len(rows)}回実行した。各求解の上限は{config['solver']['time_limit_seconds_per_case']:g}秒。成功解は独立評価器で全制約と料金内訳を再計算した。", "",
        "## 結果", "", f"差額基準は成功した実行の最小費用 {reference:.6f} 円。基準が0円に近い場合は相対差を空欄とした。MILPの最適性が未確定なら、基準との差は真の最適解からの誤差とは解釈しない。", "", table_header, table_sep, *mdrows, "",
        "## 待機解との照合", "", f"蓄電池を待機させた実行可能解は、最大買電 {max(idle_buy):.6f} kW、電力量料金 {sum(problem['price_yen_per_kWh'][i]*idle_buy[i]*problem['time_step_hours'] for i in range(len(idle_buy))):.6f} 円、基本料金 {problem['basic_charge_yen_per_kW']*max(idle_buy):.6f} 円、合計 {idle_cost:.6f} 円。", "",
        "## 判定", "", f"成功 {ok} / 時間切れ {timeout} / 失敗 {failed}。成功ケースの独立検査合格 {sum(r['evaluation_status']=='pass' for r in rows)}件。各行の `result_directory` に設定・環境・要約・時系列・ログを保存した。", "",
        "## 再現", "", "```bash", f"../.venv/bin/python src/run_experiments.py --config {config_path.relative_to(ROOT)} --experiment-id {args.experiment_id} --identifier {args.identifier} --comparison-output {comparison_output.relative_to(ROOT)} --report-output {report_output.relative_to(ROOT)}", "```", "",
        "## 未確認事項", "", "この期間での初期比較であり、季節・設備条件への一般化は未確認。", ""]
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text("\n".join(report), encoding="utf-8")
    print(f"Comparison: {comparison_output}\nReport: {report_output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
