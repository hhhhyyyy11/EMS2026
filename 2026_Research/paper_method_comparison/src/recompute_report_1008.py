#!/usr/bin/env python3
"""Run every case in the 1008 report from fresh inputs, with resumable results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from run_experiments import read_problem, run_one


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "experiments/R1008_recompute"
JST = timezone(timedelta(hours=9))
CASES = (
    ("period_day", "common_problem.json"),
    ("period_week", "e1_week.json"),
    ("period_month", "e2_d30.json"),
    ("period_hour", "e2_t60.json"),
    ("season_winter", "e3_winter.json"),
    ("season_spring", "e3_spring.json"),
    ("season_summer", "e1_week.json"),
    ("season_autumn", "e3_autumn.json"),
)
METHODS = (("lp", None), ("milp", None), *(("dp", n) for n in (19, 37, 73, 145)))
CODE_FILES = (
    "src/recompute_report_1008.py",
    "src/run_experiments.py",
    "src/check_run_setup.py",
    "src/solve_math_program.py",
    "src/solve_dp.py",
    "src/evaluate_solution.py",
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_sha(value: object) -> str:
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def equal_series(left: list[float], right: list[float], label: str) -> None:
    if len(left) != len(right) or any(not math.isclose(a, b, rel_tol=0, abs_tol=1e-9) for a, b in zip(left, right)):
        raise ValueError(f"Converted input mismatch: {label}")


def prepare() -> tuple[dict, dict]:
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    prepared = {}
    records = {}
    for name, original in CASES:
        source_config = ROOT / "config" / original
        config = json.loads(source_config.read_text(encoding="utf-8"))
        if config["input"]["source_energy_unit"] != "kWh_per_interval":
            raise ValueError(f"Unexpected source unit in {source_config}")
        config["solver"]["time_limit_seconds_per_case"] = 600
        config_path = ROOT / "config" / f"r1008_{name}.json"
        expected = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        if config_path.exists():
            if config_path.read_text(encoding="utf-8") != expected:
                raise ValueError(f"Campaign config changed: {config_path}")
        else:
            config_path.write_text(expected, encoding="utf-8")
        check = subprocess.run(
            [sys.executable, str(ROOT / "src/check_run_setup.py"), "--config", str(config_path),
             "--experiment-id", "R1008", "--identifier", name],
            cwd=ROOT, capture_output=True, text=True,
        )
        if check.returncode:
            raise RuntimeError(f"Preflight failed for {name}: {check.stdout}{check.stderr}")
        problem, frame, source = read_problem(config_path, config)
        dt = problem["time_step_hours"]
        if dt == 0.5:
            for field, column in (("load_kW", "load_energy"), ("pv_available_kW", "pv_energy")):
                raw = frame[config["input"]["value_columns"][column]].astype(float).tolist()
                equal_series([value * dt for value in problem[field]], raw, f"{name}: {field} vs raw kWh")
        prepared[name] = (config, config_path, problem, frame, source)
        records[name] = {
            "config_path": str(config_path.relative_to(ROOT)),
            "config_sha256": sha_file(config_path),
            "source_sha256": sha_file(source),
            "converted_input_sha256": canonical_sha(problem),
            "time_step_hours": dt,
            "intervals": len(problem["load_kW"]),
            "first_load_kW": problem["load_kW"][0],
        }
    for short, long in (("period_day", "period_week"), ("period_week", "period_month")):
        a, b = prepared[short][2], prepared[long][2]
        for field in ("load_kW", "pv_available_kW"):
            equal_series(a[field], b[field][:len(a[field])], f"{short} vs {long}: {field}")
    if prepared["season_summer"][2] != prepared["period_week"][2]:
        raise ValueError("Summer and seven-day period have different converted inputs")
    week, hourly = prepared["period_week"][2], prepared["period_hour"][2]
    for field in ("load_kW", "pv_available_kW"):
        expected = [(week[field][2*i] + week[field][2*i+1]) / 2 for i in range(len(hourly[field]))]
        equal_series(hourly[field], expected, f"60-minute energy conservation: {field}")
    if prepared["period_day"][2]["load_kW"][0] != 98.0 or hourly["load_kW"][0] != 103.0:
        raise ValueError("Known 49 kWh / 30-minute conversion example failed")
    manifest = {
        "campaign": "R1008_recompute",
        "planned_runs": len(CASES) * len(METHODS) * 4,
        "replicates_per_method": 4,
        "time_limit_seconds": 600,
        "code_sha256": {file: sha_file(ROOT / file) for file in CODE_FILES},
        "cases": records,
    }
    manifest_path = CAMPAIGN / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Campaign manifest changed; refusing to combine incompatible results")
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return prepared, manifest


def ledger_rows(path: Path) -> dict[tuple[str, str, int | None, int], dict]:
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["scenario"], row["method"], row["grid_count"], row["replicate"])
        if key in rows:
            raise ValueError(f"Duplicate campaign run: {key}")
        rows[key] = row
    return rows


def export_csv(rows: dict, path: Path) -> None:
    if not rows:
        return
    fields = list(next(iter(rows.values())).keys())
    temp = path.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows.values())
    temp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    prepared, manifest = prepare()
    print(f"Input checks passed for {len(prepared)} conditions; {manifest['planned_runs']} fresh runs planned", flush=True)
    if args.prepare_only:
        return
    ledger = CAMPAIGN / "runs.jsonl"
    rows = ledger_rows(ledger)
    for method, grid in METHODS:
        for scenario, _ in CASES:
            config, config_path, problem, frame, source = prepared[scenario]
            for rep in range(4):
                key = (scenario, method, grid, rep)
                if key in rows:
                    continue
                row = run_one(problem, frame, source, config, config_path, ROOT / "results",
                              datetime.now(JST), method, grid, rep, scenario, "R1008")
                row.update({
                    "scenario": scenario,
                    "input_sha256": manifest["cases"][scenario]["converted_input_sha256"],
                    "config_sha256": manifest["cases"][scenario]["config_sha256"],
                    "time_limit_seconds": 600,
                })
                with ledger.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                rows[key] = row
                export_csv(rows, CAMPAIGN / "all_runs.csv")
                print(f"{len(rows)}/{manifest['planned_runs']} {scenario} {method} {grid or ''} r{rep}: {row['status']} ({row['total_time_seconds']:.2f}s)", flush=True)
                if row["status"] == "failed":
                    raise RuntimeError(f"Run failed; inspect {row['result_directory']}")
    print("Campaign complete", flush=True)


if __name__ == "__main__":
    main()
