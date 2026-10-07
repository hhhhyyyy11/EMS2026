#!/usr/bin/env python3
"""Fill only numeric fields of the copied 1008 report from the fresh campaign."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "experiments/R1008_recompute"
REPORT = ROOT.parent / "reports/progress_report_1008.tex"
PERIOD = {"1日・30分": "period_day", "7日・30分": "period_week", "30日・30分": "period_month", "7日・60分": "period_hour"}
SEASON = {"冬": "season_winter", "春": "season_spring", "夏": "season_summer", "秋": "season_autumn"}


def swap_number(cell: str, value: str) -> str:
    match = re.fullmatch(r"(\s*)(?:[\d,.]+|--)(\s*)", cell)
    if not match:
        raise ValueError(f"Not a numeric table cell: {cell!r}")
    return match.group(1) + value + match.group(2)


def main() -> None:
    manifest = json.loads((CAMPAIGN / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (CAMPAIGN / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(rows) != manifest["planned_runs"] or len(rows) != 192:
        raise ValueError(f"Expected 192 completed runs, found {len(rows)}")
    grouped = defaultdict(list)
    unique = set()
    for row in rows:
        scenario, method, grid, rep = (row[k] for k in ("scenario", "method", "grid_count", "replicate"))
        key = (scenario, method, grid, rep)
        if key in unique:
            raise ValueError(f"Duplicate run: {key}")
        unique.add(key)
        if row["input_sha256"] != manifest["cases"][scenario]["converted_input_sha256"]:
            raise ValueError(f"Input hash mismatch: {key}")
        if row["config_sha256"] != manifest["cases"][scenario]["config_sha256"] or row["time_limit_seconds"] != 600:
            raise ValueError(f"Configuration mismatch: {key}")
        result = Path(row["result_directory"])
        if not result.is_dir() or not (result / "summary.json").is_file():
            raise ValueError(f"Missing result: {key}")
        if row["status"] == "success":
            if row["evaluation_status"] != "pass" or not math.isfinite(row["objective_yen"]) or not math.isfinite(row["total_time_seconds"]):
                raise ValueError(f"Invalid successful result: {key}")
        elif row["status"] != "time_limit":
            raise ValueError(f"Unexpected run status: {key}: {row['status']}")
        grouped[(scenario, method, grid)].append(row)
    if len(grouped) != 48 or any(len(group) != 4 for group in grouped.values()):
        raise ValueError("Expected 48 method-condition groups with four runs each")

    summary = {}
    success_total = timeout_total = 0
    for key, group in grouped.items():
        success = [row for row in group if row["status"] == "success"]
        success_total += len(success)
        timeout_total += len(group) - len(success)
        summary[key] = {
            "success": len(success),
            "mean_cost_yen": statistics.mean(row["objective_yen"] for row in success) if success else None,
            "mean_total_seconds": statistics.mean(row["total_time_seconds"] for row in success) if success else None,
        }
        if key[1] == "lp":
            for row in success:
                result = json.loads((Path(row["result_directory"]) / "summary.json").read_text(encoding="utf-8"))
                if result["maximum_simultaneous_charge_discharge_kW"] > 1e-6:
                    raise ValueError("LP simultaneous charge/discharge contradicts existing report text")
    for scenario in (*PERIOD.values(), *SEASON.values()):
        lp, milp = summary[(scenario, "lp", None)], summary[(scenario, "milp", None)]
        if lp["success"] != 4 or milp["success"] != 4 or not math.isclose(lp["mean_cost_yen"], milp["mean_cost_yen"], abs_tol=1e-5):
            raise ValueError(f"LP/MILP result contradicts existing report text: {scenario}")

    original = REPORT.read_text(encoding="utf-8")
    replacements = {
        r"\date{2026年10月2日}": r"\date{2026年10月8日}",
        "300秒": "600秒",
        "本実験で新たに実行した120件は103件成功，17件時間切れ，失敗0件だった．":
            f"本実験で新たに実行した192件は{success_total}件成功，{timeout_total}件時間切れ，失敗0件だった．",
    }
    for old, new in replacements.items():
        if old not in original:
            raise ValueError(f"Expected report text missing: {old}")
        original = original.replace(old, new)
    lines = []
    cases = None
    current = None
    updated = set()
    for line in original.splitlines(keepends=True):
        if r"\label{tab:period}" in line:
            cases, current = PERIOD, None
        elif r"\label{tab:season}" in line:
            cases, current = SEASON, None
        elif r"\end{longtable}" in line:
            cases, current = None, None
        if cases is not None and "&" in line and line.rstrip().endswith(r"\\"):
            cells = line.split("&")
            if len(cells) == 5:
                label = cells[0].strip()
                if label in cases:
                    current = cases[label]
                method_text = cells[1].strip()
                if method_text in ("LP", "MILP") or method_text.startswith("DP-"):
                    if current is None:
                        raise ValueError(f"No report condition for {line!r}")
                    method = method_text.lower().split("-")[0]
                    grid = int(method_text.split("-")[1]) if method == "dp" else None
                    key = (current, method, grid)
                    if key in updated:
                        raise ValueError(f"Duplicate report row: {key}")
                    updated.add(key)
                    data = summary[key]
                    cells[2] = swap_number(cells[2], str(data["success"]))
                    cells[3] = swap_number(cells[3], f"{data['mean_cost_yen']:,.0f}" if data["success"] else "--")
                    tail = cells[4]
                    position = tail.index(r"\\")
                    cells[4] = swap_number(tail[:position], f"{data['mean_total_seconds']:.2f}" if data["success"] else "--") + tail[position:]
                    line = "&".join(cells)
        lines.append(line)
    if len(updated) != 48:
        raise ValueError(f"Expected to update 48 table rows, updated {len(updated)}")
    report_text = "".join(lines)
    REPORT.write_text(report_text, encoding="utf-8")
    summary_path = CAMPAIGN / "report_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(("scenario", "method", "grid_count", "runs_successful", "mean_cost_yen", "mean_total_seconds"))
        for (scenario, method, grid), data in summary.items():
            writer.writerow((scenario, method, grid or "", data["success"], data["mean_cost_yen"], data["mean_total_seconds"]))
    print(f"Updated {REPORT}; success={success_total}, time_limit={timeout_total}")


if __name__ == "__main__":
    main()
