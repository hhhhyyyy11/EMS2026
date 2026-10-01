# 論文用実装

数理計画法、DP、共通モデル、共通評価処理、実験実行処理を保存する。過去実装は `../../src/` を参照し、今回の変更はこのディレクトリ内に作成する。

- `check_run_setup.py`: 共通設定、実データの利用可能期間、対象期間、結果保存先を求解前に検査する。対象時間刻みは元データ間隔の整数倍を扱う。
- `evaluate_solution.py`: 求解器から独立して、正規化した問題と時系列から料金・最大買電を再計算し、共通モデルの全制約と報告値を検査する。
- `solve_math_program.py`: 共通モデルを基準MILPまたは診断用LPとしてSCIPで解き、共通要約、時系列、独立評価結果をJSONで返す。`--soc-grid-count` を指定したMILPでは、全SOC境界をDPと同じ格子に制限する。LPでは同時充放電の区間数と最大値も記録する。
- `solve_dp.py`: 初期・終端SOCを厳密に含む一様格子上でDPを行い、SOCごとに累積最大買電と累積電力量料金の非劣ラベルを保持する。終端で基本料金を加え、共通要約、時系列、独立評価結果をJSONで返す。
- `run_e0_validation.py`: T04の3人工ケースについてDP、同一格子MILP、連続SOC MILPを実行し、共通許容差によるE0比較JSONを生成する。
- `run_experiments.py`: 共通設定と実入力からE1/E2/E3/E4ケースを実行する。元30分値より粗い刻みは連続値の平均電力へ集約し、各実行の設定、環境、要約、時系列、ログを保存する。成功ケースは独立評価に合格してから比較表へ記録する。
- `summarize_e1.py`: 日次・週次の試行CSVを統合し、中央値表、3種類の図、確認事項・未確認事項を含むE1報告書を再生成する。
- `summarize_t11.py`: E2〜E4と再利用したE1結果を統合し、E5選択表、条件別中央値表、RQ別の図、T11統合報告を生成する。

T04の人工ケースを数理計画で解く例：

```bash
../.venv/bin/python src/solve_math_program.py tests/small_cases/case_b_arbitrage.json --method milp
../.venv/bin/python src/solve_math_program.py tests/small_cases/case_b_arbitrage.json --method lp
```

同じケースを3点SOC格子のDPで解く例：

```bash
../.venv/bin/python src/solve_dp.py tests/small_cases/case_b_arbitrage.json --soc-grid-count 3
```

同じ3点SOC格子へ制限したMILPで解く例：

```bash
../.venv/bin/python src/solve_math_program.py tests/small_cases/case_b_arbitrage.json --method milp --soc-grid-count 3
```

純Python実装のため初回コンパイルは発生せず、共通要約には `initial_compile_time_seconds: 0.0` と、補足として非該当状態を記録する。格子遷移の準備時間と、その後のラベル更新による `prepared_solve_time_seconds` は別々に記録する。
