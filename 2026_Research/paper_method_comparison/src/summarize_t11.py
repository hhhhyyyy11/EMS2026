#!/usr/bin/env python3
"""Combine the fixed E2-E5 campaign, make selection tables, and render figures."""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments"
TABLES = ROOT / "tables"
FIGURES = ROOT / "figures"


def read_case(path: Path, experiment: str, scenario: str, axis: str, level: str) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame.insert(0, "level", level)
    frame.insert(0, "axis", axis)
    frame.insert(0, "scenario", scenario)
    frame.insert(0, "experiment", experiment)
    return frame


def load_all() -> pd.DataFrame:
    parts = [
        read_case(EXP / "E1_initial/comparison.csv", "E2", "1day-30min", "period", "1 day"),
        read_case(EXP / "E1_initial/comparison_week.csv", "E2", "7day-30min", "period", "7 days"),
        read_case(EXP / "E2_period_grid/D30/comparison.csv", "E2", "30day-30min", "period", "30 days"),
        read_case(EXP / "E2_period_grid/T60/comparison.csv", "E2", "7day-60min", "time_step", "60 min"),
        read_case(EXP / "E3_season/Winter/comparison.csv", "E3", "winter", "season", "Winter"),
        read_case(EXP / "E3_season/Spring/comparison.csv", "E3", "spring", "season", "Spring"),
        read_case(EXP / "E1_initial/comparison_week.csv", "E3", "summer", "season", "Summer"),
        read_case(EXP / "E3_season/Autumn/comparison.csv", "E3", "autumn", "season", "Autumn"),
        read_case(EXP / "E4_battery/Low/comparison.csv", "E4", "low-output", "battery_power_ratio", "0.25 h^-1"),
        read_case(EXP / "E1_initial/comparison_week.csv", "E4", "base-output", "battery_power_ratio", "0.4651 h^-1"),
        read_case(EXP / "E4_battery/High/comparison.csv", "E4", "high-output", "battery_power_ratio", "0.75 h^-1"),
    ]
    all_rows = pd.concat(parts, ignore_index=True)
    for col in ["grid_count", "replicate", "objective_yen", "solve_time_seconds", "total_time_seconds", "peak_memory_mib", "relative_gap"]:
        all_rows[col] = pd.to_numeric(all_rows[col], errors="coerce")
    return all_rows


def summarise(all_rows: pd.DataFrame) -> pd.DataFrame:
    groups = []
    for (exp, scenario, axis, level, method, grid), rows in all_rows.groupby(
            ["experiment", "scenario", "axis", "level", "method", "grid_count"], dropna=False, sort=False):
        ok = rows[rows.status == "success"]
        diagnostics_list = []
        for result_dir in ok.result_directory:
            try:
                diagnostics_list.append(pd.read_json(Path(result_dir) / "summary.json", typ="series"))
            except (OSError, ValueError):
                pass
        dp_diagnostics = diagnostics_list if method == "dp" else []
        milp = all_rows[(all_rows.scenario == scenario) & (all_rows.method == "milp") &
                        (all_rows.status == "success")]
        milp_gaps = pd.to_numeric(milp.relative_gap, errors="coerce")
        optimal_milp = milp[milp_gaps.fillna(float("inf")) <= 1e-12]
        baseline = pd.to_numeric(optimal_milp.objective_yen, errors="coerce").median() if len(optimal_milp) else np.nan
        cost = pd.to_numeric(ok.objective_yen, errors="coerce").median()
        gap_pct = (cost - baseline) / baseline * 100 if pd.notna(cost) and pd.notna(baseline) and baseline > 1e-9 else np.nan
        groups.append({
            "experiment": exp, "scenario": scenario, "axis": axis, "level": level,
            "method": method, "grid_count": int(grid) if pd.notna(grid) else "",
            "runs_planned": len(rows), "runs_successful": len(ok),
            "runs_time_limited": int((rows.status == "time_limit").sum()),
            "runs_failed": int((rows.status == "failed").sum()),
            "all_successful_evaluations_pass": bool(len(ok) and (ok.evaluation_status == "pass").all()),
            "milp_optimal_reference_yen": baseline,
            "median_cost_yen": cost,
            "median_cost_gap_yen": cost - baseline if pd.notna(cost) and pd.notna(baseline) else np.nan,
            "median_cost_gap_pct": gap_pct,
            "median_total_seconds": pd.to_numeric(ok.total_time_seconds, errors="coerce").median(),
            "median_peak_memory_mib": pd.to_numeric(ok.peak_memory_mib, errors="coerce").median(),
            "max_successful_total_seconds": pd.to_numeric(ok.total_time_seconds, errors="coerce").max(),
            "max_successful_peak_memory_mib": pd.to_numeric(ok.peak_memory_mib, errors="coerce").max(),
            "median_feasible_state_transitions": pd.to_numeric(pd.Series([d.get("transition_count") for d in dp_diagnostics]), errors="coerce").median() if dp_diagnostics else np.nan,
            "median_max_nondominated_labels_per_state": pd.to_numeric(pd.Series([d.get("maximum_nondominated_labels") for d in dp_diagnostics]), errors="coerce").median() if dp_diagnostics else np.nan,
            "maximum_simultaneous_charge_discharge_kW": pd.to_numeric(pd.Series([d.get("maximum_simultaneous_charge_discharge_kW") for d in diagnostics_list]), errors="coerce").max() if diagnostics_list else np.nan,
            "milp_reference_status": "optimal_gap_0" if len(optimal_milp) == 4 else ("unconfirmed" if len(milp) else "missing"),
        })
    return pd.DataFrame(groups)


def make_selection(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scenario in summary.scenario.unique():
        options = summary[(summary.scenario == scenario) & summary.milp_reference_status.eq("optimal_gap_0")]
        for tolerance in (0.1, 0.5, 1.0):
            for seconds in (1, 10, 60, 300):
                for memory in (64, 512, 2048):
                    feasible = options[
                        (options.runs_successful == 4) & options.all_successful_evaluations_pass &
                        (options.median_cost_gap_pct <= tolerance) &
                        (options.median_total_seconds <= seconds) &
                        (options.median_peak_memory_mib <= memory) &
                        (options.maximum_simultaneous_charge_discharge_kW.fillna(0) <= 1e-6)
                    ].sort_values(["median_total_seconds", "median_peak_memory_mib"])
                    if len(feasible):
                        chosen = feasible.iloc[0]
                        label = "LP" if chosen.method == "lp" else ("MILP" if chosen.method == "milp" else f"DP-{int(chosen.grid_count)}")
                        gap, elapsed, rss = chosen.median_cost_gap_pct, chosen.median_total_seconds, chosen.median_peak_memory_mib
                        evidence = "4/4 success; independent evaluation pass; no simultaneous charge/discharge; MILP gap 0"
                    else:
                        label, gap, elapsed, rss = "No method meets all limits", np.nan, np.nan, np.nan
                        evidence = "No 4/4 reproducible option meets all three limits, or MILP reference is unconfirmed"
                    rows.append({"scenario": scenario, "allowed_cost_increase_pct": tolerance,
                        "time_limit_seconds": seconds, "memory_limit_mib": memory,
                        "selected_method": label, "observed_median_cost_increase_pct": gap,
                        "observed_median_total_seconds": elapsed, "observed_median_peak_memory_mib": rss,
                        "evidence": evidence})
    return pd.DataFrame(rows)


def configure_japanese_font() -> None:
    path = Path("/Users/yzhy/Library/Fonts/NotoSansJP-Regular.ttf")
    if path.exists():
        font_manager.fontManager.addfont(str(path))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def accuracy_time_figure(summary: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    xvals = [19, 37, 73, 145]
    scenarios = [
        ("1day-30min", "1日・30分", "#2878b5", "-"),
        ("7day-30min", "7日・30分", "#39a85a", "-"),
        ("30day-30min", "30日・30分", "#d1495b", "-"),
        ("7day-60min", "7日・60分", "#8055a5", "--"),
    ]
    all_gaps = summary[(summary.scenario.isin([s[0] for s in scenarios])) & (summary.method == "dp")].median_cost_gap_pct.dropna()
    timeout_y = max(12, float(all_gaps.max()) + 2)
    for scenario, label, color, style in scenarios:
        subset = summary[(summary.scenario == scenario) & (summary.method == "dp")].set_index("grid_count")
        ys = [subset.loc[x, "median_cost_gap_pct"] if x in subset.index else np.nan for x in xvals]
        axes[0].plot(xvals, ys, marker="o", color=color, linestyle=style, label=label)
        for x, y in zip(xvals, ys):
            if pd.isna(y):
                axes[0].scatter([x], [timeout_y], marker="x", color=color, s=55)
    axes[0].set_ylim(0, timeout_y + 2)
    axes[0].set_xticks(xvals); axes[0].set_xlabel("DPのSOC格子点数")
    axes[0].set_ylabel("MILP基準からの費用増加率（%）")
    axes[0].set_title("費用差（×は300秒以内に未完了）"); axes[0].grid(True, axis="y", alpha=.25)
    axes[0].legend(fontsize=8)
    for scenario, label, color, style in scenarios:
        subset = summary[(summary.scenario == scenario) & (summary.method == "dp")].set_index("grid_count")
        ys = [subset.loc[x, "median_total_seconds"] if x in subset.index else np.nan for x in xvals]
        axes[1].plot(xvals, ys, marker="o", color=color, linestyle=style, label=label)
        for x in xvals:
            if x in subset.index and pd.isna(subset.loc[x, "median_total_seconds"]):
                axes[1].scatter([x], [300], marker="x", color=color, s=55)
    axes[1].set_xticks(xvals); axes[1].set_yscale("log"); axes[1].set_ylim(.1, 500)
    axes[1].axhline(300, color="#555555", linewidth=.8, linestyle=":")
    axes[1].set_xlabel("DPのSOC格子点数"); axes[1].set_ylabel("全処理時間中央値（秒、対数軸）")
    axes[1].set_title("計算時間（点線は300秒上限）"); axes[1].grid(True, which="both", alpha=.25)
    fig.suptitle("E2：期間・時間刻みとDPの費用差/計算時間")
    fig.tight_layout(); fig.savefig(FIGURES / "T11_E2_accuracy_time.png", dpi=180, bbox_inches="tight"); plt.close(fig)


def season_figure(summary: pd.DataFrame) -> None:
    order = ["winter", "spring", "summer", "autumn"]
    labels = ["冬", "春", "夏", "秋"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    data = summary[(summary.axis == "season") & summary.method.eq("dp")]
    width = .18
    for gi, grid in enumerate((19, 37, 73, 145)):
        vals = []
        for scenario in order:
            row = data[(data.scenario == scenario) & (data.grid_count == grid)]
            vals.append(float(row.median_cost_gap_pct.iloc[0]) if len(row) and pd.notna(row.median_cost_gap_pct.iloc[0]) else np.nan)
        positions = np.arange(4) + (gi - 1.5) * width
        axes[0].bar(positions, vals, width=width, label=f"DP {grid}点")
        for x, scenario in enumerate(order):
            row = data[(data.scenario == scenario) & (data.grid_count == grid)]
            if len(row) and row.runs_successful.iloc[0] < 4:
                axes[0].scatter([x + (gi - 1.5) * width], [95], marker="x", color="#222222", s=40)
    axes[0].set_xticks(np.arange(4), labels); axes[0].set_ylim(bottom=0, top=105); axes[0].set_ylabel("MILP基準からの費用増加率（%）")
    axes[0].set_title("季節別の費用差（×は一部時間切れ）"); axes[0].legend(fontsize=8); axes[0].grid(True, axis="y", alpha=.25)
    for grid in (19, 37, 73, 145):
        vals = []
        for scenario in order:
            row = data[(data.scenario == scenario) & (data.grid_count == grid)]
            vals.append(float(row.median_total_seconds.iloc[0]) if len(row) and pd.notna(row.median_total_seconds.iloc[0]) else np.nan)
        axes[1].plot(labels, vals, marker="o", label=f"DP {grid}点")
        for i, scenario in enumerate(order):
            row = data[(data.scenario == scenario) & (data.grid_count == grid)]
            if len(row) and row.runs_successful.iloc[0] < 4:
                axes[1].scatter([labels[i]], [300], marker="x", color="#222222", s=40)
    axes[1].set_yscale("log"); axes[1].set_ylabel("全処理時間中央値（秒、対数軸）")
    axes[1].set_title("季節別の計算時間"); axes[1].legend(fontsize=8); axes[1].grid(True, which="both", alpha=.25)
    fig.suptitle("E3：季節週の比較")
    fig.tight_layout(); fig.savefig(FIGURES / "T11_E3_season.png", dpi=180, bbox_inches="tight"); plt.close(fig)


def battery_figure(summary: pd.DataFrame) -> None:
    order = ["low-output", "base-output", "high-output"]
    labels = ["0.25", "0.4651", "0.75"]
    data = summary[(summary.axis == "battery_power_ratio") & summary.method.eq("dp")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for grid in (19, 37, 73, 145):
        sub = data[data.grid_count == grid]
        vals = [float(sub[sub.scenario == s].median_cost_gap_pct.iloc[0]) if len(sub[sub.scenario == s]) and pd.notna(sub[sub.scenario == s].median_cost_gap_pct.iloc[0]) else np.nan for s in order]
        axes[0].plot(labels, vals, marker="o", label=f"DP {grid}点")
        times = [float(sub[sub.scenario == s].median_total_seconds.iloc[0]) if len(sub[sub.scenario == s]) and pd.notna(sub[sub.scenario == s].median_total_seconds.iloc[0]) else np.nan for s in order]
        axes[1].plot(labels, times, marker="o", label=f"DP {grid}点")
    axes[0].set_ylabel("MILP基準からの費用増加率（%）"); axes[0].set_xlabel("出力/容量比（h^-1）")
    axes[0].set_title("費用差"); axes[0].grid(True, alpha=.25)
    axes[1].set_yscale("log"); axes[1].set_ylabel("全処理時間中央値（秒、対数軸）"); axes[1].set_xlabel("出力/容量比（h^-1）")
    axes[1].set_title("計算時間"); axes[1].grid(True, which="both", alpha=.25)
    axes[1].legend(fontsize=8)
    fig.suptitle("E4：蓄電池出力/容量比")
    fig.tight_layout(); fig.savefig(FIGURES / "T11_E4_battery.png", dpi=180, bbox_inches="tight"); plt.close(fig)


def write_reports(summary: pd.DataFrame, selection: pd.DataFrame) -> None:
    e2 = summary[summary.experiment.eq("E2")]
    e3 = summary[summary.experiment.eq("E3")]
    e4 = summary[summary.experiment.eq("E4")]
    d30 = e2[e2.scenario.eq("30day-30min")]
    t60 = e2[e2.scenario.eq("7day-60min")]
    winter = e3[e3.scenario.eq("winter")]
    spring = e3[e3.scenario.eq("spring")]
    summer = e3[e3.scenario.eq("summer")]
    autumn = e3[e3.scenario.eq("autumn")]
    def gridrow(frame, grid): return frame[(frame.method == "dp") & (frame.grid_count == grid)].iloc[0]
    def table(headers: list[str], rows: list[list[str]]) -> str:
        return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"] +
                         ["| " + " | ".join(row) + " |" for row in rows])
    def metrics_table(frame: pd.DataFrame) -> str:
        rows = []
        for _, item in frame[frame.method.eq("dp")].sort_values("grid_count").iterrows():
            cost = f"{item.median_cost_gap_pct:.3g}%" if pd.notna(item.median_cost_gap_pct) else "未評価"
            elapsed = f"{item.median_total_seconds:.1f}" if pd.notna(item.median_total_seconds) else "300秒超"
            memory = f"{item.median_peak_memory_mib:.1f}" if pd.notna(item.median_peak_memory_mib) else "—"
            rows.append([f"DP {int(item.grid_count)}", f"{int(item.runs_successful)}/4", cost, elapsed, memory])
        return table(["手法", "成功/4", "MILP比の費用差中央値", "全処理時間中央値（秒）", "ピークRSS中央値（MiB）"], rows)
    d30_37, d30_73 = gridrow(d30, 37), gridrow(d30, 73)
    s_t60_73 = gridrow(t60, 73)
    w145, sp145, su145, a145 = [gridrow(f, 145) for f in (winter, spring, summer, autumn)]
    low, base, high = [gridrow(e4[e4.scenario.eq(s)], 73) for s in ("low-output", "base-output", "high-output")]
    report = [
        "# T11：本実験の結果と考察", "",
        "全条件は `EXPERIMENT_MATRIX.md` に固定した通り実行した。E1で実測済みの1日・7日、夏週、基準設備の結果を再利用し、新規168実行を追加した。各成功解は独立評価に合格し、時間切れは目的値未評価として残した。比較基準は同ケースの最適性ギャップ0の連続SOC MILP中央値。",
        "", "## E2：期間・格子・時間刻み", "",
        f"30日ではDP37点の費用差が {d30_37.median_cost_gap_pct:.4g}%、時間中央値 {d30_37.median_total_seconds:.1f}秒だった。DP73点は{int(d30_73.runs_successful)}/4回成功（300秒以内に完了した試行のみ費用を集計）、DP145点は4/4回時間切れとなった。",
        f"7日60分ではDP73点が{int(s_t60_73.runs_successful)}/4回成功し、成功試行の費用差中央値は{s_t60_73.median_cost_gap_pct:.4g}%、時間{s_t60_73.median_total_seconds:.1f}秒だった。30分から60分への集約で区間数は半減したが、費用差は時間分解能を含む別問題の比較であり、30分解の単純な誤差とは解釈しない。",
        "30日DP145点と7日DP145点は300秒で全試行が時間切れ。格子細分化が費用差を縮める一方、期間が伸びると実用時間内に評価できない場合がある。",
        "", "### E2の格子別集計", "",
        "| ケース | 格子 | 成功/4 | MILP比の費用差中央値 | 全処理時間中央値（秒） | ピークRSS中央値（MiB） |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {row.scenario} | {int(row.grid_count)} | {int(row.runs_successful)}/4 | {row.median_cost_gap_pct:.3g}% | {row.median_total_seconds:.1f} | {row.median_peak_memory_mib:.1f} |" if pd.notna(row.median_cost_gap_pct) else f"| {row.scenario} | {int(row.grid_count)} | {int(row.runs_successful)}/4 | 未評価 | 300秒超 | — |" for _, row in e2[e2.method.eq("dp")].iterrows()],
        "", "## E3：季節", "",
        f"DP145点は冬{int(w145.runs_successful)}/4、春{int(sp145.runs_successful)}/4、夏{int(su145.runs_successful)}/4、秋{int(a145.runs_successful)}/4回成功した。冬は全4回が約{w145.median_total_seconds:.1f}秒、春は約{sp145.median_total_seconds:.1f}秒で完了したが、夏・秋は全て上限に達した。実測したDP73点の最大非劣ラベル数中央値は冬{gridrow(winter, 73).median_max_nondominated_labels_per_state:.0f}、春{gridrow(spring, 73).median_max_nondominated_labels_per_state:.0f}、夏{gridrow(summer, 73).median_max_nondominated_labels_per_state:.0f}、秋{gridrow(autumn, 73).median_max_nondominated_labels_per_state:.0f}で、季節週の入力系列と保持ラベルの増加が計算負荷に関係している。",
        "E3は各季節1週の事前指定ケースであり、季節内変動や年ごとの差は推定しない。",
        "", "### E3の季節別格子集計", "",
        *[f"### {season.title()}\n\n{metrics_table(e3[e3.scenario.eq(season)])}" for season in ("winter", "spring", "summer", "autumn")],
        "", "## E4：設備出力/容量比", "",
        f"DP73点では出力/容量比0.25、0.4651、0.75 h^-1の費用差中央値が{low.median_cost_gap_pct:.4g}%、{base.median_cost_gap_pct:.4g}%、{high.median_cost_gap_pct:.4g}%、全処理時間が{low.median_total_seconds:.1f}、{base.median_total_seconds:.1f}、{high.median_total_seconds:.1f}秒だった。実測遷移数中央値は{low.median_feasible_state_transitions:.0f}、{base.median_feasible_state_transitions:.0f}、{high.median_feasible_state_transitions:.0f}、最大保持ラベル数中央値は{low.median_max_nondominated_labels_per_state:.0f}、{base.median_max_nondominated_labels_per_state:.0f}、{high.median_max_nondominated_labels_per_state:.0f}だった。低出力は遷移数が少ない一方、保持ラベルが基準設備より多く処理時間も長かった。高出力では遷移数が最大となり最も時間を要した。実測範囲では遷移数と非劣ラベル数の両方が負荷に関係し、時間は出力/容量比だけでは単調に決まらない。",
        "基準設備はE1週次を再利用した。DP145点は低・基準・高の全てで300秒上限を超えた。",
        "", "### E4の出力/容量比別格子集計", "",
        *[f"### {scenario.replace('-', ' ').title()}\n\n{metrics_table(e4[e4.scenario.eq(scenario)])}" for scenario in ("low-output", "base-output", "high-output")],
        "", "## E5：費用・時間・メモリによる選択", "",
        f"[`../tables/E5_selection.csv`](../tables/E5_selection.csv) は各シナリオについて費用増加許容幅0.1/0.5/1.0%、全処理時間1/10/60/300秒、ピークRSS 64/512/2048 MiBを照合する。選択には4/4回の成功、全独立評価pass、同時充放電なし、最適性ギャップ0のMILP基準を要求した。条件を満たさない組合せは空欄にせず「No method meets all limits」と記録した。中央値による資源判定であり、最悪値保証ではない。",
        f"固定した全11シナリオ中、成功LPは44/44回で目的値がMILP基準と一致し、同時充放電は0 kWだった。この観測範囲ではLPが実行可能な最短候補として選ばれた。7日60分の1秒上限では全ての費用許容幅・メモリ水準で条件を満たさず、残る387/396組合せではLPが選択された。これは本研究の固定正価格・単一設備条件の結果で、一般のMILP排他制約を外せる根拠ではない。",
        "選択はこのモデル、入力データ、固定価格、ハードウェア、300秒上限に限定する。未測定資源水準へ外挿しない。",
        "", "## 図表", "",
        "- [`../figures/T11_E2_accuracy_time.png`](../figures/T11_E2_accuracy_time.png)：期間・時間刻み・格子と費用差/時間。",
        "- [`../figures/T11_E3_season.png`](../figures/T11_E3_season.png)：季節週の費用差と計算時間。",
        "- [`../figures/T11_E4_battery.png`](../figures/T11_E4_battery.png)：出力/容量比と費用差・計算時間。",
        "- [`../tables/T11_medians.csv`](../tables/T11_medians.csv)：全条件の成功数・中央値・時間切れ数。",
        "- [`../tables/T11_all_runs.csv`](../tables/T11_all_runs.csv)：全実行と再利用結果への参照。",
        "", "## 主な限界と追加実験", "",
        "固定価格のため価格裁定の影響を評価していない。E3は季節ごとに1週だけで、E2の30日も1期間だけである。DP145点の時間切れ後に必要時間や高精度解を推定していない。現在の代表週に範囲を限るなら追加実験は不要。季節一般化を主張する場合は、結果を見ずに選ぶ各季節の追加週で季節内変動を検証する必要がある。",
        "", "## RQと図表の対応", "",
        "- RQ1（格子細分化と費用差）：E2図と `T11_medians.csv` の格子別費用差。",
        "- RQ2（期間・格子・計算負荷）：E2図、E3季節図、E4設備図の処理時間・ピークRSS。",
        "- RQ3（季節・設備条件）：E3季節図、E4出力/容量比図と対応する条件表。",
        "- RQ4（要求精度・資源からの手法選択）：`E5_selection.csv`。",
        "", "## 再現", "",
        "各条件の `config/*.json`、試行CSV、`results/` 以下の個別記録を参照する。E2の60分ケースは元30分値2点の平均電力に集約し、電力量を保存した。統合表・図・本報告は次で再生成する：",
        "", "```bash", "../.venv/bin/python src/summarize_t11.py", "```", "",
    ]
    (EXP / "T11_REPORT.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    TABLES.mkdir(exist_ok=True); FIGURES.mkdir(exist_ok=True)
    configure_japanese_font()
    all_rows = load_all()
    summary = summarise(all_rows)
    selection = make_selection(summary)
    all_rows.to_csv(TABLES / "T11_all_runs.csv", index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    summary.to_csv(TABLES / "T11_medians.csv", index=False, encoding="utf-8-sig")
    selection.to_csv(TABLES / "E5_selection.csv", index=False, encoding="utf-8-sig")
    accuracy_time_figure(summary)
    season_figure(summary)
    battery_figure(summary)
    write_reports(summary, selection)
    print(f"raw_runs={len(all_rows)} scenarios={all_rows.scenario.nunique()} summary_rows={len(summary)} selection_rows={len(selection)}")
    print(all_rows.groupby(["experiment", "scenario", "status"]).size().to_string())
    print("written: tables/T11_all_runs.csv, tables/T11_medians.csv, tables/E5_selection.csv, figures/T11_*.png, experiments/T11_REPORT.md")


if __name__ == "__main__":
    main()
