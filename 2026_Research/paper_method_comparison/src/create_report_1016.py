"""Create the October 16 report from the previous report and saved LP runs."""
from pathlib import Path
import csv
import hashlib
import json
import os
import re
import sys

os.environ.setdefault('MPLCONFIGDIR', '/tmp/ems-mpl-1016')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT.parent / 'reports'
OUT = ROOT / 'experiments/R1016_operation'
FIG = ROOT / 'figures/R1016_daily_operation.png'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.parent.mkdir(exist_ok=True)
    for name in ('Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'IPAexGothic'):
        if name in {f.name for f in font_manager.fontManager.ttflist}:
            plt.rcParams['font.family'] = name
            break
    plt.rcParams.update({'font.size': 10, 'axes.unicode_minus': False})
    runs = [json.loads(s) for s in (ROOT / 'experiments/R1008_recompute/runs.jsonl').read_text().splitlines()]
    fig, axes = plt.subplots(3, 3, figsize=(11, 8), sharex=True, sharey='row')
    metrics, provenance, inputs = [], [], []
    hours = np.arange(49) / 2
    for col, (scenario, days) in enumerate((('period_day', 1), ('period_week', 7), ('period_month', 30))):
        selected = [r for r in runs if r['scenario'] == scenario and r['method'] == 'lp' and r['replicate'] == 0]
        assert len(selected) == 1
        run = selected[0]
        folder = Path(run['result_directory'])
        assert run['status'] == 'success'
        assert json.loads((folder / 'evaluation.json').read_text())['status'] == 'pass'
        with (folder / 'trajectory.csv').open(encoding='utf-8-sig') as f:
            full = list(csv.DictReader(f))
        assert len(full) == days * 48
        rows = full[:48]
        assert all(r['timestamp'].startswith('2025-07-22T') for r in rows)
        values = lambda key: np.array([float(r[key]) for r in rows])
        load, pv, buy = (values(k) for k in ('load_kW', 'pv_available_kW', 'purchased_power_kW'))
        charge = values('charge_power_kW_internal') / .98
        discharge = values('discharge_power_kW_internal') * .98
        soc = np.r_[values('soc_start_kWh'), float(rows[-1]['soc_end_kWh'])] / 860 * 100
        assert np.isclose(soc[0], 50)
        assert np.allclose(values('soc_end_kWh')[:-1], values('soc_start_kWh')[1:])
        inputs.append(np.c_[load, pv])
        ax = axes[0, col]
        for data, label, color, style in ((load, '需要', '#303b48', '-'), (pv, '利用可能PV', '#d99800', '-'), (buy, '買電', '#0072b2', '-')):
            ax.plot(hours[:-1] + .25, data, label=label, color=color, linestyle=style, linewidth=1.4)
        ax.set_title(f'最適化期間：{days}日', fontsize=12, pad=10)
        ax = axes[1, col]
        ax.plot(hours[:-1] + .25, charge, label='充電（外部側）', color='#009e73', linewidth=1.5)
        ax.plot(hours[:-1] + .25, -discharge, label='放電（外部側）', color='#cc6677', linewidth=1.5)
        ax.axhline(0, color='#888888', linewidth=.5)
        ax = axes[2, col]
        ax.plot(hours, soc, color='#0072b2', linewidth=1.7, label='SOC')
        ax.axhline(50, color='#999999', linestyle='--', linewidth=.8, label='初期SOC 50%')
        ax.set_ylim(0, 100)
        ax.set_xlabel('7月22日の時刻 [時]')
        metric = {'horizon_days': days, 'first_day_peak_kW': float(max(buy)), 'first_day_purchase_kWh': float(sum(buy)*.5), 'soc_at_24h_percent': float(soc[-1]), 'horizon_peak_kW': run['maximum_purchased_power_kW']}
        metrics.append(metric)
        provenance.append({'scenario': scenario, 'run_id': run['run_id'], 'result_directory': str(folder), 'trajectory_sha256': hashlib.sha256((folder / 'trajectory.csv').read_bytes()).hexdigest(), 'evaluation': 'pass'})
    assert all(np.array_equal(inputs[0], other) for other in inputs[1:])
    assert np.isclose(metrics[0]['soc_at_24h_percent'], 50)
    for row, label in enumerate(('電力 [kW]', '充電 + / 放電 − [kW]', 'SOC [%]')):
        axes[row, 0].set_ylabel(label)
        axes[row, 0].legend(loc='upper left', fontsize=8, framealpha=.9)
        for ax in axes[row]:
            ax.set_xlim(0, 24)
            ax.set_xticks([0, 6, 12, 18, 24])
            ax.grid(alpha=.18)
            ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout(pad=1.4, w_pad=1.0, h_pad=1.4)
    fig.savefig(FIG, dpi=230, facecolor='white')
    plt.close(fig)
    if '--figure-only' in sys.argv:
        from plot_daily_methods_1016 import main as update_methods_figure
        update_methods_figure()
        return
    with (OUT / 'daily_metrics.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(metrics[0]))
        w.writeheader()
        w.writerows(metrics)
    (OUT / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2)+'\n')
    old = (REPORTS / 'progress_report_1008.tex').read_text()
    text = old.replace(r'\date{2026年10月8日}', r'\date{2026年10月16日}')
    text = text.replace(r'\usepackage{longtable}', r'\usepackage{longtable}'+'\n'+r'\usepackage{graphicx}'+r'''
\ifdefined\XeTeXversion
  \setCJKmainfont{HaranoAjiMincho-Regular.otf}
  \setCJKsansfont{HaranoAjiGothic-Medium.otf}
\fi
''')
    text = text.replace(r'{p{50mm}p{103mm}}', r'{p{46mm}p{91mm}}')
    text = text.replace('論文に向けた準備と実験結果}', '比較実験結果と最適化期間による運用の違い}')
    text = text.replace('本報告では，モデルの整理，比較実験，研究方針の検討をまとめる．', '本報告では，前回までの比較実験結果を再掲し，最適化期間による1日の蓄電池運用の違いを示す．')
    text = text.replace('本実験で新たに実行した192件は', '前回報告した192件は')
    text = text.replace('季節比較には冬（1月14～20日），春（4月15～21日），夏（7月22～28日），秋（10月14～20日）の各1週間を用いた．', '異なる入力条件の4例として，冬（1月14～20日），春（4月15～21日），夏（7月22～28日），秋（10月14～20日）の各1週間を用いた．')
    text = text.replace('4回の内訳は初回1回と準備後3回である．', '4回とも事前準備後に実行した．')
    text = text.replace('季節別1週間の費用と処理時間（30分刻み，各手法4回）', '異なる入力条件4例の費用と処理時間（各1週間，30分刻み，各手法4回）')
    text = text.replace('\\end{longtable}\n\\endgroup\n\n\\begingroup', '\\end{longtable}\n\\endgroup\n\n\\clearpage\n\\begingroup')
    table_rows = '\n'.join(f"        {m['horizon_days']}日 & {m['first_day_peak_kW']:.2f} & {m['soc_at_24h_percent']:.2f} \\\\" for m in metrics)
    added = r'''
\clearpage
\section{最適化期間による1日の運用の違い}
LPの1日・7日・30日計画から，共通する2025年7月22日の48区間を取り出した．入力と初期SOCは同じであり，各条件の1回目の最適解を用いた．この図には前回の保存済み結果を用いた．

\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.90\textwidth]{../paper_method_comparison/figures/R1016_daily_operation.png}
    \caption{最適化期間別の7月22日の運用（LP，30分刻み）．電力は各30分区間の平均値を区間中央に置き，折れ線で結んだ．充放電は外部側で充電を正，放電を負とした．}
    \label{fig:daily-operation}
\end{figure}

\begin{table}[htbp]
    \centering
    \caption{7月22日の最大買電と24時のSOC}
    \begin{tabular}{lrr}
        \toprule
        最適化期間 & 当日の最大買電 [kW] & 当日24時のSOC [\%] \\
        \midrule
''' + table_rows + r'''
        \bottomrule
    \end{tabular}
\end{table}

1日計画では日内の買電を平準化し，7日・30日計画では当日の充放電が少なくなった．1日計画のみ当日24時のSOCが50\%に固定される．先の需要・PV，終端条件，基本料金の期間按分が異なる条件での比較であり，図は各条件の最適解の一例である．
'''
    text = text.replace(r'\end{document}', added+'\n'+r'\end{document}'+'\n')
    assert re.findall(r'\\begin\{longtable\}.*?\\end\{longtable\}', old, re.S)[0] == re.findall(r'\\begin\{longtable\}.*?\\end\{longtable\}', text, re.S)[0]
    # Both previous result tables retain all numeric entries.
    numeric_rows = lambda s: [line for line in s.splitlines() if '&' in line and re.search(r'&\s*(LP|MILP|DP-\d+)\s*&', line)]
    assert numeric_rows(old) == numeric_rows(text)
    report_path = REPORTS / 'progress_report_1016.tex'
    start, end = '% BEGIN R1016 THREE DAYS', '% END R1016 THREE DAYS'
    if report_path.exists() and start in report_path.read_text():
        appendix = report_path.read_text().split(start, 1)[1].split(end, 1)[0]
        text = text.replace(r'\end{document}', start + appendix + end + '\n' + r'\end{document}')
    report_path.write_text(text)
    from plot_daily_methods_1016 import main as update_methods_figure
    update_methods_figure()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
