"""Append verified three-day results to the weekly report without rebuilding it."""
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / 'experiments/R1016_three_days'


def main():
    runs = [json.loads(line) for line in (CAMPAIGN/'runs.jsonl').read_text().splitlines()]
    manifest = json.loads((CAMPAIGN/'manifest.json').read_text())
    for filename, expected in manifest['code_sha256'].items():
        assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest() == expected
    assert len(runs) == 48
    assert len({(r['scenario'],r['method'],r['grid_count'],r['replicate']) for r in runs}) == 48
    summary = list(csv.DictReader((CAMPAIGN/'summary.csv').open(encoding='utf-8-sig')))
    assert len(summary) == 12 and all(int(r['completed']) == 4 for r in summary)
    for run in runs:
        folder = Path(run['result_directory'])
        case = manifest['cases'][run['scenario']]
        environment = json.loads((folder/'environment.json').read_text())
        assert environment['input_sha256'] == case['source_sha256']
        assert run['input_sha256'] == case['input_sha256']
        assert run['config_sha256'] == case['config_sha256']
        assert run['time_limit_seconds'] == 600
        for filename in ('config.json','environment.json','summary.json','trajectory.csv','run.log'):
            assert (folder/filename).is_file()
        assert run['status'] in ('success', 'time_limit')
        if run['status'] == 'success':
            evaluation = json.loads((folder/'evaluation.json').read_text())
            assert evaluation['status'] == 'pass'
            assert evaluation['interval_count'] == case['intervals']
            assert math.isclose(evaluation['recomputed']['objective_yen'],run['objective_yen'],abs_tol=.01)
            saved = json.loads((folder/'summary.json').read_text())
            if run['method'] == 'milp':
                assert saved['relative_gap'] == 0
            if run['method'] == 'lp':
                assert saved['maximum_simultaneous_charge_discharge_kW'] <= 1e-6
    lines = []
    for scenario, interval in (('three_days_30min','30分'),('three_days_60min','60分')):
        group = [r for r in summary if r['scenario'] == scenario]
        lp = next(r for r in group if r['method']=='lp')
        milp = next(r for r in group if r['method']=='milp')
        assert math.isclose(float(lp['mean_cost_yen']),float(milp['mean_cost_yen']),abs_tol=.01)
        successful_dp = [r for r in group if r['method']=='dp' and int(r['successful'])>0]
        costs = [float(r['mean_cost_yen']) for r in successful_dp]
        assert all(a >= b-0.01 for a,b in zip(costs,costs[1:]))
        for i, row in enumerate(group):
            raw = [r for r in runs if r['scenario']==scenario and r['method']==row['method'] and str(r['grid_count'] or '')==row['grid_count'] and r['status']=='success']
            label = row['method'].upper() + (f"-{row['grid_count']}" if row['grid_count'] else '')
            cost = f"{statistics.mean(r['objective_yen'] for r in raw):,.0f}" if raw else '--'
            time = f"{statistics.mean(r['total_time_seconds'] for r in raw):.2f}" if raw else '--'
            lines.append(f"        {interval if i==0 else ''} & {label} & {len(raw)} & {cost} & {time} \\\\")
        if scenario.endswith('30min'):
            lines.append(r'        \midrule')
    success = sum(r['status']=='success' for r in runs)
    timeout = sum(r['status']=='time_limit' for r in runs)
    block = r'''
% BEGIN R1016 THREE DAYS
\clearpage
\section{3日間の追加実験}
2025年7月22～24日の3日間について，30分間隔（144区間）と60分間隔（72区間）で比較した．その他の条件は前回と同じとし，各手法4回，求解の打切り設定600秒で実行した．60分値は隣接する30分値2点の平均電力とし，総電力量を保存した．

\begin{table}[htbp]
    \centering
    \caption{最適化期間3日の費用と処理時間（各手法4回）}
    \label{tab:three-days}
    \begin{tabular}{llrrr}
        \toprule
        時間間隔 & 手法 & 成功/4 & 費用平均値 [円] & 時間平均値 [秒] \\
        \midrule
'''+'\n'.join(lines)+r'''
        \bottomrule
    \end{tabular}
\end{table}

'''+f'追加48件は{success}件成功，{timeout}件時間切れ，失敗0件であり，成功解はすべて独立評価に合格した．費用と時間は成功試行のみの平均値である．60分値との費用差には時間集約による問題条件の変化も含まれる．\n'+r'''

\clearpage
\subsection{3日計画における1日の運用}
3日計画の各条件1回目のLP解から，7月22日の運用を取り出した．両条件の初期SOCは50\%であり，終端SOCは7月25日0時に50\%とする．固定単価では同費用の運用が複数あり得るため，図は各条件の最適解の一例である．

\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.90\textwidth]{../paper_method_comparison/figures/R1016_three_day_operation.png}
    \caption{最適化期間3日の7月22日の運用（LP）．電力は各区間の平均値を区間中央に置き，折れ線で結んだ．充放電は外部側で充電を正，放電を負とした．}
    \label{fig:three-day-operation}
\end{figure}

% END R1016 THREE DAYS
'''
    path = ROOT.parent/'reports/progress_report_1016.tex'
    text = path.read_text()
    text = text.replace('新たな最適化は実行していない．', 'この図には前回の保存済み結果を用いた．')
    start, end = '% BEGIN R1016 THREE DAYS', '% END R1016 THREE DAYS'
    if start in text:
        left, rest = text.split(start,1)
        _, right = rest.split(end,1)
        text = left + block.strip() + right
    else:
        text = text.replace(r'\end{document}',block+'\n'+r'\end{document}')
    path.write_text(text)
    print(f'Appended 12 rows. Successful={success}, time_limit={timeout}; verified all saved results.')


if __name__ == '__main__':
    main()
