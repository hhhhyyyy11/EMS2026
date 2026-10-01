#!/usr/bin/env python3
"""Combine E1 day/week results and render the comparison figures/report."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/E1_initial"
RESULTS = ROOT / "results"


def read_comparison(path: Path, period: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.insert(0, "period", period)
    return frame


def median_table(all_rows: pd.DataFrame) -> pd.DataFrame:
    good = all_rows[all_rows.status == "success"].copy()
    good["grid_label"] = good.grid_count.fillna(0).astype(int).astype(str).replace("0", "—")
    return (good.groupby(["period", "method", "grid_label"], sort=False)
            .agg(successes=("status", "size"), median_cost_yen=("objective_yen", "median"),
                 median_difference_yen=("cost_difference_yen", "median"),
                 median_solve_seconds=("solve_time_seconds", "median"),
                 median_total_seconds=("total_time_seconds", "median"),
                 median_peak_memory_mib=("peak_memory_mib", "median"),
                 all_independent_checks_pass=("evaluation_status", lambda s: bool((s == "pass").all())))
            .reset_index())


def fig_cost_time(summary: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5), sharey=False)
    colors = {"day": "#2463a6", "week": "#c05621"}
    for ax, period in zip(axes, ("day", "week")):
        subset = summary[summary.period == period]
        for _, row in subset.iterrows():
            x, y = row.median_total_seconds, max(0, row.median_difference_yen)
            ax.scatter(x, y, s=55, color=colors[period], edgecolor="white", linewidth=.6)
            label = row.method.upper() if row.method != "dp" else f"DP {row.grid_label}"
            ax.annotate(label, (x, y), xytext=(5, 4), textcoords="offset points", fontsize=8)
        ax.set_xscale("log")
        ax.set_title("1日（48区間）" if period == "day" else "1週間（336区間）")
        ax.set_xlabel("準備後を含む全処理時間の中央値（秒、対数軸）")
        ax.grid(True, which="both", alpha=.25)
        if period == "week":
            ax.text(.98, .95, "DP145：300秒で時間切れ\n費用未評価", transform=ax.transAxes,
                    ha="right", va="top", fontsize=9,
                    bbox={"boxstyle": "round,pad=.3", "facecolor": "white", "alpha": .9, "edgecolor": ".7"})
    axes[0].set_ylabel("期間内最小成功費用からの差（円）")
    fig.suptitle("E1：費用差と計算時間（成功したケース）")
    fig.tight_layout()
    fig.savefig(ROOT / "figures/E1_cost_time.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def read_trajectory(row: pd.Series) -> pd.DataFrame:
    return pd.read_csv(Path(row.result_directory) / "trajectory.csv", parse_dates=["timestamp"])


def fig_operation(all_rows: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=False)
    for ax, period in zip(axes, ("day", "week")):
        row = all_rows[(all_rows.period == period) & (all_rows.method == "milp") &
                       (all_rows.replicate == 0) & (all_rows.status == "success")].iloc[0]
        traj = read_trajectory(row)
        x = traj.timestamp
        ax.plot(x, traj.soc_start_kWh, color="#2463a6", label="SOC (kWh)", linewidth=1.5)
        ax.set_ylabel("SOC (kWh)", color="#2463a6")
        ax.tick_params(axis="y", labelcolor="#2463a6")
        right = ax.twinx()
        right.plot(x, traj.purchased_power_kW, color="#c05621", label="買電 (kW)", alpha=.8, linewidth=1)
        right.step(x, traj.charge_power_kW_internal, where="post", color="#238636", label="充電 (kW)", alpha=.8, linewidth=.9)
        right.step(x, -traj.discharge_power_kW_internal, where="post", color="#8b5cf6", label="放電 (負値表示, kW)", alpha=.8, linewidth=.9)
        right.set_ylabel("電力（買電・充放電、kW）")
        ax.set_title("1日" if period == "day" else "1週間")
        ax.grid(True, axis="y", alpha=.25)
        handles, labels = ax.get_legend_handles_labels()
        h2, l2 = right.get_legend_handles_labels()
        ax.legend(handles + h2, labels + l2, loc="upper right", ncol=4, fontsize=8)
    axes[-1].set_xlabel("日時（JST）")
    fig.suptitle("E1：SOC・充放電・買電（MILP、初回実行）")
    fig.tight_layout()
    fig.savefig(ROOT / "figures/E1_soc_operation.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def fig_inputs(all_rows: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 6.7), sharex=False)
    for ax, period in zip(axes, ("day", "week")):
        row = all_rows[(all_rows.period == period) & (all_rows.method == "milp") &
                       (all_rows.replicate == 0) & (all_rows.status == "success")].iloc[0]
        traj = read_trajectory(row)
        x = traj.timestamp
        ax.plot(x, traj.load_kW, color="#333333", label="需要 (kW)", linewidth=1)
        ax.plot(x, traj.pv_available_kW, color="#e3a008", label="PV (kW)", linewidth=1)
        ax.set_ylabel("需要・PV（kW）")
        ax.set_title("1日" if period == "day" else "1週間")
        ax.grid(True, alpha=.25)
        price_ax = ax.twinx()
        price_ax.plot(x, traj.price_yen_per_kWh, color="#2463a6", linestyle="--", label="固定価格 (円/kWh)", linewidth=1)
        price_ax.set_ylabel("価格（円/kWh）")
        handles, labels = ax.get_legend_handles_labels()
        h2, l2 = price_ax.get_legend_handles_labels()
        ax.legend(handles + h2, labels + l2, loc="upper right", ncol=3, fontsize=8)
    axes[-1].set_xlabel("日時（JST）")
    fig.suptitle("E1：価格・PV・需要")
    fig.tight_layout()
    fig.savefig(ROOT / "figures/E1_inputs.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    japanese_font = Path("/Users/yzhy/Library/Fonts/NotoSansJP-Regular.ttf")
    if japanese_font.exists():
        font_manager.fontManager.addfont(str(japanese_font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(japanese_font)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    all_rows = pd.concat([
        read_comparison(EXP / "comparison.csv", "day"),
        read_comparison(EXP / "comparison_week.csv", "week"),
    ], ignore_index=True)
    all_rows.to_csv(ROOT / "tables/E1_comparison.csv", index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    summary = median_table(all_rows)
    summary.to_csv(ROOT / "tables/E1_summary.csv", index=False, encoding="utf-8-sig")
    fig_cost_time(summary)
    fig_operation(all_rows)
    fig_inputs(all_rows)

    lines = [
        "# E1：1日・1週間の初期比較", "",
        "LPとMILPの連続SOC結果を基準候補とし、DPは格子点数別に比較した。差額は各期間の最小成功費用との差であり、数理計画法が最適と確認された場合に限り最適解との差と解釈できる。成功結果はすべて独立評価器で制約と費用を再計算した。",
        "", "## 条件", "",
        "| 期間 | 入力 | 時間刻み | 価格 | 設備 | 試行 |", "|---|---:|---:|---:|---|---:|",
        "| 1日 | 48区間（2025-07-22） | 30分 | 21.51円/kWh固定 | 860 kWh・内部400 kW | 24 |",
        "| 1週間 | 336区間（2025-07-22〜28） | 30分 | 21.51円/kWh固定 | 860 kWh・内部400 kW | 24 |",
        "", "両期間とも初期・終端SOCは50%、基本料金は期間長で按分した。LP、MILP、DP19/37/73/145点について、初回1回と準備後3回を実行した。各ケースの時間上限は300秒。元の全試行と結果フォルダは [`E1_comparison.csv`](../../tables/E1_comparison.csv) の `result_directory` から参照できる。週次設定は [`e1_week.json`](../../config/e1_week.json)、日次・週次の生比較は `comparison.csv` と `comparison_week.csv` に保存した。",
        "", "## 確認できたこと", "",
        "1. 日次は24/24件、週次は20/24件が成功し、成功した44解すべてが独立評価に合格した。週次のDP145点4件はすべて300秒で時間切れとなり、失敗解を費用比較へ含めていない。",
        "2. 両期間でDP格子を19→37→73点へ細かくすると、成功費用差が小さくなった。1日ではDP145点も成功して基準との差がさらに縮まった。週次のDP145点は上限内に完了せず、精度を評価できない。",
        "3. 週次の成功最小費用は270,019.91円、蓄電池待機解は288,781.69円だった。週次DP19/37/73点の中央値費用はそれぞれ285,007.91 / 281,046.97 / 275,698.68円。DP73点の全処理時間中央値は約53.6秒、ピークRSS中央値は約21.5 MiB。",
        "", "## 図表", "",
        "- [`E1_comparison.csv`](../../tables/E1_comparison.csv)：日次・週次の全48試行、成功状態、費用、時間、メモリ、評価状態、元結果へのパス。",
        "- [`E1_summary.csv`](../../tables/E1_summary.csv)：成功試行の中央値と独立評価の集計。",
        "- [`E1_cost_time.png`](../../figures/E1_cost_time.png)：費用差と計算時間。",
        "- [`E1_soc_operation.png`](../../figures/E1_soc_operation.png)：SOC、充放電、買電の時系列。",
        "- [`E1_inputs.png`](../../figures/E1_inputs.png)：価格、PV、需要の時系列。",
        "", "## 再現コマンド", "",
        "日次の試行：", "", "```bash", "../.venv/bin/python src/run_experiments.py --config config/common_problem.json --experiment-id E1 --identifier day", "```",
        "", "週次の試行：", "", "```bash", "../.venv/bin/python src/run_experiments.py --config config/e1_week.json --experiment-id E1 --identifier week --comparison-output experiments/E1_initial/comparison_week.csv --report-output experiments/E1_initial/REPORT_week.md", "```",
        "", "両結果を統合して表・図・本報告を再生成：", "", "```bash", "../.venv/bin/python src/summarize_e1.py", "```",
        "", "## 未確認事項", "",
        "この比較は2025-07-22開始の1日・1週間に限られ、季節、設備容量・出力、時間刻みへの一般化は未確認。固定価格条件のため、価格変動の効果も扱っていない。週次DP145点は300秒上限で完了せず、より大きい予算での目的値と必要時間は不明。",
        "", "## 次の実験条件（T10への入力）", "",
        "週次のDP145点はE2の初期計画から除外せず、300秒・2 GiBの共通予算で再確認する対象とする。最初に1/7/30日の期間×19/37/73点を同じ30分刻み・固定価格・設備条件で比較し、145点は1日・1週間の追加確認枠に分ける。季節ケースと30/60分の時間刻み、設備条件の変更は要因を混ぜず、期間選定と総計算量をT10で確定する。"
    ]
    (EXP / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {ROOT / 'tables/E1_comparison.csv'} ({len(all_rows)} runs)")
    print(f"Wrote figures and {EXP / 'REPORT.md'}")


if __name__ == "__main__":
    main()
