#!/usr/bin/env python3
"""Validate the shared EMS configuration, input interval, and result destination."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


JST = timezone(timedelta(hours=9))
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def fail(message: str) -> None:
    raise ValueError(message)


def require_number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{name} must be a finite number")
    number = float(value)
    if positive and number <= 0:
        fail(f"{name} must be greater than zero")
    return number


def parse_iso(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        fail(f"{name} must be an ISO 8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        fail(f"{name} must include a UTC offset")
    return parsed


def time_offset(value: Any) -> timedelta:
    if isinstance(value, time):
        return timedelta(
            hours=value.hour,
            minutes=value.minute,
            seconds=value.second,
            microseconds=value.microsecond,
        )
    if isinstance(value, datetime):
        return time_offset(value.time())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return timedelta(days=float(value))
    fail(f"unsupported time value in energy input: {value!r}")


def normalized_timestamp(date_value: Any, time_value: Any) -> datetime:
    parsed_date = pd.to_datetime(date_value, errors="raise").date()
    return datetime.combine(parsed_date, time.min) + time_offset(time_value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_config(config: dict[str, Any]) -> tuple[datetime, datetime, int]:
    if config.get("schema_version") != 1:
        fail("schema_version must be 1")
    if config.get("timezone") != "Asia/Tokyo":
        fail("timezone must be Asia/Tokyo")

    period = config["period"]
    start = parse_iso(period["start"], "period.start")
    end = parse_iso(period["end_exclusive"], "period.end_exclusive")
    step_hours = require_number(period["time_step_hours"], "period.time_step_hours", positive=True)
    interval_count_float = (end - start).total_seconds() / (step_hours * 3600)
    interval_count = round(interval_count_float)
    if end <= start or not math.isclose(interval_count_float, interval_count, abs_tol=1e-9):
        fail("period must be positive and exactly divisible by time_step_hours")

    source_step = require_number(
        config["input"]["source_interval_hours"],
        "input.source_interval_hours",
        positive=True,
    )
    aggregation_ratio = step_hours / source_step
    if aggregation_ratio < 1 or not math.isclose(aggregation_ratio, round(aggregation_ratio), abs_tol=1e-9):
        fail("period.time_step_hours must be an integer multiple of the source interval")
    available_start = parse_iso(config["input"]["available_start"], "input.available_start")
    available_end = parse_iso(
        config["input"]["available_end_exclusive"],
        "input.available_end_exclusive",
    )
    if not (available_start <= start < end <= available_end):
        fail("requested period is outside the declared available input period")

    price = config["price"]
    if price.get("mode") != "fixed":
        fail("the main experiment price mode must be fixed")
    require_number(price["fixed_yen_per_kWh"], "price.fixed_yen_per_kWh", positive=True)

    battery = config["battery"]
    require_number(battery["capacity_kWh"], "battery.capacity_kWh", positive=True)
    require_number(battery["charge_limit_kW_internal"], "battery.charge_limit_kW_internal", positive=True)
    require_number(battery["discharge_limit_kW_internal"], "battery.discharge_limit_kW_internal", positive=True)
    for key in ("charge_efficiency", "discharge_efficiency"):
        value = require_number(battery[key], f"battery.{key}", positive=True)
        if value > 1:
            fail(f"battery.{key} must not exceed 1")
    ratios = [
        require_number(battery[key], f"battery.{key}")
        for key in ("soc_min_ratio", "initial_soc_ratio", "terminal_soc_ratio", "soc_max_ratio")
    ]
    if not (0 <= ratios[0] <= ratios[1] <= ratios[3] <= 1):
        fail("initial SOC must lie inside the SOC bounds")
    if not (ratios[0] <= ratios[2] <= ratios[3]):
        fail("terminal SOC must lie inside the SOC bounds")

    grid_counts = config["dp"]["soc_grid_counts"]
    if not isinstance(grid_counts, list) or not grid_counts:
        fail("dp.soc_grid_counts must be a non-empty list")
    previous_intervals = None
    for count in grid_counts:
        if isinstance(count, bool) or not isinstance(count, int) or count < 2:
            fail("every SOC grid count must be an integer of at least 2")
        intervals = count - 1
        for label, ratio in (("initial", ratios[1]), ("terminal", ratios[2])):
            position = (ratio - ratios[0]) / (ratios[3] - ratios[0]) * intervals
            if not math.isclose(position, round(position), abs_tol=1e-9):
                fail(f"{label} SOC is absent from the {count}-point grid")
        if previous_intervals is not None and intervals % previous_intervals != 0:
            fail("SOC grids are not nested")
        previous_intervals = intervals

    basic = config["basic_charge"]
    require_number(basic["monthly_yen_per_kW"], "basic_charge.monthly_yen_per_kW", positive=True)
    require_number(basic["power_factor_multiplier"], "basic_charge.power_factor_multiplier", positive=True)
    if basic.get("proration") != "study_hours_over_8760":
        fail("basic charge proration must be study_hours_over_8760")
    if basic.get("hours_per_year") != 8760:
        fail("basic_charge.hours_per_year must be 8760")

    solver = config["solver"]
    require_number(solver["time_limit_seconds_per_case"], "solver.time_limit_seconds_per_case", positive=True)
    require_number(solver["memory_budget_gib_per_run"], "solver.memory_budget_gib_per_run", positive=True)
    results = config["results"]
    if results.get("overwrite_existing_directory") is not False:
        fail("results.overwrite_existing_directory must be false")
    expected_files = {"config.json", "environment.json", "summary.json", "trajectory.csv", "run.log"}
    if set(results.get("required_files", [])) != expected_files:
        fail("results.required_files does not match the T03 artifact set")
    return start, end, interval_count


def inspect_energy_input(
    config: dict[str, Any], config_path: Path, start: datetime, end: datetime, expected_count: int
) -> dict[str, Any]:
    input_config = config["input"]
    input_path = (config_path.parent / input_config["energy_excel_path"]).resolve()
    if not input_path.is_file():
        fail(f"energy input does not exist: {input_path}")
    frame = pd.read_excel(input_path, sheet_name=input_config["energy_sheet"])
    date_column = input_config["timestamp_columns"]["date"]
    time_column = input_config["timestamp_columns"]["time"]
    load_column = input_config["value_columns"]["load_energy"]
    pv_column = input_config["value_columns"]["pv_energy"]
    missing_columns = {date_column, time_column, load_column, pv_column} - set(frame.columns)
    if missing_columns:
        fail(f"energy input is missing columns: {sorted(missing_columns)}")

    load = pd.to_numeric(frame[load_column], errors="coerce")
    pv = pd.to_numeric(frame[pv_column], errors="coerce")
    numeric = load.notna() & pv.notna()
    frame = frame.loc[numeric].copy()
    frame[load_column] = load.loc[numeric]
    frame[pv_column] = pv.loc[numeric]
    if frame.empty or (frame[[load_column, pv_column]] < 0).any().any():
        fail("energy input is empty or contains negative energy values")

    raw_timestamps = [
        normalized_timestamp(d, t)
        for d, t in zip(frame[date_column], frame[time_column])
    ]
    tolerance_ms = require_number(
        input_config["timestamp_snap_tolerance_milliseconds"],
        "input.timestamp_snap_tolerance_milliseconds",
    )
    step_seconds = input_config["source_interval_hours"] * 3600
    epoch = datetime(1970, 1, 1)
    timestamps: list[datetime] = []
    max_snap_ms = 0.0
    for timestamp in raw_timestamps:
        step = round((timestamp - epoch).total_seconds() / step_seconds)
        snapped = epoch + timedelta(seconds=step * step_seconds)
        deviation_ms = abs((timestamp - snapped).total_seconds() * 1000)
        max_snap_ms = max(max_snap_ms, deviation_ms)
        if deviation_ms > tolerance_ms + 1e-9:
            fail(f"timestamp exceeds snap tolerance: {timestamp.isoformat()}")
        timestamps.append(snapped.replace(tzinfo=JST))

    if len(set(timestamps)) != len(timestamps):
        fail("energy input contains duplicate timestamps after snapping")
    timestamps.sort()
    source_step = timedelta(hours=input_config["source_interval_hours"])
    if any(right - left != source_step for left, right in zip(timestamps, timestamps[1:])):
        fail("energy input is not continuous at the declared source interval")
    if len(timestamps) != input_config["expected_available_intervals"]:
        fail("available input interval count differs from configuration")
    requested = [timestamp for timestamp in timestamps if start <= timestamp < end]
    expected_source_count = expected_count * round(
        config["period"]["time_step_hours"] / input_config["source_interval_hours"]
    )
    if len(requested) != expected_source_count:
        fail(f"requested period has {len(requested)} source rows; expected {expected_source_count}")

    return {
        "path": str(input_path),
        "sha256": sha256(input_path),
        "available_start": timestamps[0].isoformat(),
        "available_end_exclusive": (timestamps[-1] + source_step).isoformat(),
        "available_intervals": len(timestamps),
        "requested_source_intervals": len(requested),
        "requested_intervals": expected_count,
        "maximum_timestamp_snap_milliseconds": round(max_snap_ms, 6),
    }


def safe_component(value: str, label: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        fail(f"{label} must match {SAFE_NAME.pattern}")
    return value


def output_destination(
    config: dict[str, Any],
    config_path: Path,
    experiment_id: str,
    identifier: str,
    timestamp: datetime,
    output_root_override: Path | None,
) -> Path:
    root = output_root_override.resolve() if output_root_override else (
        config_path.parent / config["results"]["root_path"]
    ).resolve()
    stamp = timestamp.astimezone(JST).strftime("%Y%m%dT%H%M%S%z")
    return root / f"{safe_component(experiment_id, 'experiment_id')}_{stamp}_{safe_component(identifier, 'identifier')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/common_problem.json"))
    parser.add_argument("--experiment-id", default="E1")
    parser.add_argument("--identifier", default="setup-check")
    parser.add_argument("--timestamp", help="fixed ISO timestamp for a reproducible destination check")
    parser.add_argument("--output-root", type=Path, help="override result root (useful for tests)")
    parser.add_argument(
        "--initialize-output",
        action="store_true",
        help="atomically reserve the destination and copy the effective config",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    with config_path.open(encoding="utf-8") as source:
        config = json.load(source)
    start, end, expected_count = validate_config(config)
    input_summary = inspect_energy_input(config, config_path, start, end, expected_count)
    run_timestamp = parse_iso(args.timestamp, "--timestamp") if args.timestamp else datetime.now(JST)
    destination = output_destination(
        config,
        config_path,
        args.experiment_id,
        args.identifier,
        run_timestamp,
        args.output_root,
    )
    existed_before = destination.exists()
    if args.initialize_output:
        destination.mkdir(parents=True, exist_ok=False)
        shutil.copy2(config_path, destination / "config.json")

    study_hours = expected_count * config["period"]["time_step_hours"]
    basic = config["basic_charge"]
    annual_basic = (
        basic["monthly_yen_per_kW"]
        * basic["power_factor_multiplier"]
        * basic["months_per_year"]
    )
    report = {
        "status": "ok",
        "config_path": str(config_path),
        "input": input_summary,
        "period": {
            "start": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "intervals": expected_count,
            "hours": study_hours,
        },
        "fixed_price_yen_per_kWh": config["price"]["fixed_yen_per_kWh"],
        "prorated_basic_charge_yen_per_kW": annual_basic * study_hours / basic["hours_per_year"],
        "result_destination": str(destination),
        "destination_existed_before_check": existed_before,
        "destination_initialized": args.initialize_output,
        "required_result_files": config["results"]["required_files"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
