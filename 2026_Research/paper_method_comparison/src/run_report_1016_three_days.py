"""Resumable three-day comparison at 30 and 60 minute resolution."""
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
from datetime import datetime

from recompute_report_1008 import (ROOT, JST, METHODS, CODE_FILES, canonical_sha,
                                  sha_file, equal_series, ledger_rows, export_csv)
from run_experiments import read_problem, run_one

CAMPAIGN = ROOT / 'experiments/R1016_three_days'
CASES = (('three_days_30min', .5), ('three_days_60min', 1.0))


def prepare():
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    prepared, records = {}, {}
    for name, dt in CASES:
        config = json.loads((ROOT / 'config/r1008_period_week.json').read_text())
        config['period'].update(end_exclusive='2025-07-25T00:00:00+09:00', time_step_hours=dt)
        path = ROOT / f'config/r1016_{name}.json'
        content = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
        if path.exists():
            assert path.read_text() == content, 'Existing configuration differs'
        else:
            path.write_text(content)
        check = subprocess.run([sys.executable, str(ROOT / 'src/check_run_setup.py'),
                                '--config', str(path), '--experiment-id', 'R1016',
                                '--identifier', name], cwd=ROOT, capture_output=True, text=True)
        (CAMPAIGN / f'{name}_preflight.log').write_text(check.stdout + check.stderr)
        if check.returncode:
            raise RuntimeError(check.stdout + check.stderr)
        problem, frame, source = read_problem(path, config)
        assert len(problem['load_kW']) == int(72 / dt)
        prepared[name] = config, path, problem, frame, source
        records[name] = {'config_sha256': sha_file(path), 'source_sha256': sha_file(source),
                         'input_sha256': canonical_sha(problem), 'intervals': len(problem['load_kW']),
                         'time_step_hours': dt}
    half, hour = (prepared[name][2] for name, _ in CASES)
    for field in ('load_kW', 'pv_available_kW'):
        equal_series(hour[field], [(half[field][2*i] + half[field][2*i+1])/2 for i in range(72)], field)
        assert math.isclose(sum(half[field])*.5, sum(hour[field]), abs_tol=1e-7)
    assert half['load_kW'][0] == 98.0 and hour['load_kW'][0] == 103.0
    manifest = {'campaign': 'R1016_three_days', 'planned_runs': 48,
                'replicates': 4, 'time_limit_seconds': 600, 'execution': 'sequential',
                'cases': records, 'code_sha256': {file: sha_file(ROOT/file) for file in (*CODE_FILES, 'src/run_report_1016_three_days.py')}}
    path = CAMPAIGN / 'manifest.json'
    if path.exists():
        assert json.loads(path.read_text()) == manifest, 'Manifest changed'
    else:
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return prepared, manifest


def summarize(rows):
    summary = []
    for scenario, _ in CASES:
        for method, grid in METHODS:
            group = [r for r in rows.values() if (r['scenario'], r['method'], r['grid_count']) == (scenario, method, grid)]
            success = [r for r in group if r['status'] == 'success']
            summary.append({'scenario': scenario, 'method': method, 'grid_count': grid,
                            'completed': len(group), 'successful': len(success),
                            'time_limit': sum(r['status'] == 'time_limit' for r in group),
                            'failed': sum(r['status'] == 'failed' for r in group),
                            'mean_cost_yen': statistics.mean(r['objective_yen'] for r in success) if success else None,
                            'mean_total_seconds': statistics.mean(r['total_time_seconds'] for r in success) if success else None})
    with (CAMPAIGN/'summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    lines = ['# 3日間・30分／60分間隔の比較', '',
             '対象：2025年7月22日00:00～7月25日00:00直前（72時間）。',
             'LP・MILP・DP19/37/73/145点、各4回、各600秒上限。既存の共通モデルと独立評価器を使用。',
             '30分値は144区間、60分値は隣接2点の平均電力による72区間。需要・PVの総電力量保存を事前確認。', '',
             '| 間隔 | 手法 | 成功/完了 | 時間切れ | 費用平均 [円] | 時間平均 [秒] |',
             '|---|---|---:|---:|---:|---:|']
    for r in summary:
        label = r['method'].upper() + (f"-{r['grid_count']}" if r['grid_count'] else '')
        cost = f"{r['mean_cost_yen']:,.2f}" if r['mean_cost_yen'] is not None else '--'
        elapsed = f"{r['mean_total_seconds']:.2f}" if r['mean_total_seconds'] is not None else '--'
        lines.append(f"| {'30分' if r['scenario'].endswith('30min') else '60分'} | {label} | {r['successful']}/{r['completed']} | {r['time_limit']} | {cost} | {elapsed} |")
    lines += ['', '平均は成功試行のみ。時間切れは費用を推定しない。全処理時間は既存実験と同じ run_one の計測区間。',
              '元結果は all_runs.csv の result_directory に保存。設定と入力・コードのハッシュは manifest.json に保存。',
              '', '再実行：`../.venv/bin/python src/run_report_1016_three_days.py`（完了済み試行を再利用）。', '']
    (CAMPAIGN/'REPORT.md').write_text('\n'.join(lines))


def main():
    prepared, manifest = prepare()
    ledger = CAMPAIGN / 'runs.jsonl'
    rows = ledger_rows(ledger)
    print(f'Preflight passed: 144/72 intervals, energy conserved. {len(rows)}/48 already completed.', flush=True)
    for method, grid in METHODS:
        for scenario, _ in CASES:
            config, path, problem, frame, source = prepared[scenario]
            for rep in range(4):
                key = scenario, method, grid, rep
                if key in rows:
                    continue
                row = run_one(problem, frame, source, config, path, ROOT/'results',
                              datetime.now(JST), method, grid, rep, scenario, 'R1016')
                row.update(scenario=scenario, input_sha256=manifest['cases'][scenario]['input_sha256'],
                           config_sha256=manifest['cases'][scenario]['config_sha256'], time_limit_seconds=600)
                with ledger.open('a') as f:
                    f.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
                    f.flush()
                    os.fsync(f.fileno())
                rows[key] = row
                export_csv(rows, CAMPAIGN/'all_runs.csv')
                summarize(rows)
                print(f"{len(rows)}/48 {row['case_id']}: {row['status']}, {row['total_time_seconds']:.2f}s", flush=True)
                if row['status'] == 'failed':
                    raise RuntimeError(row['message'])
    assert len(rows) == 48
    for row in rows.values():
        if row['status'] == 'success':
            assert row['evaluation_status'] == 'pass'
            assert json.loads((Path(row['result_directory'])/'evaluation.json').read_text())['status'] == 'pass'
    print('Complete: 48 trials; all successful solutions independently evaluated.', flush=True)


if __name__ == '__main__':
    main()
