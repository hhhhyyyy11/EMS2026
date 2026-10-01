# E1：1日・1週間の初期比較

LPとMILPの連続SOC結果を基準候補とし、DPは格子点数別に比較した。差額は各期間の最小成功費用との差であり、数理計画法が最適と確認された場合に限り最適解との差と解釈できる。成功結果はすべて独立評価器で制約と費用を再計算した。

## 条件

| 期間 | 入力 | 時間刻み | 価格 | 設備 | 試行 |
|---|---:|---:|---:|---|---:|
| 1日 | 48区間（2025-07-22） | 30分 | 21.51円/kWh固定 | 860 kWh・内部400 kW | 24 |
| 1週間 | 336区間（2025-07-22〜28） | 30分 | 21.51円/kWh固定 | 860 kWh・内部400 kW | 24 |

両期間とも初期・終端SOCは50%、基本料金は期間長で按分した。LP、MILP、DP19/37/73/145点について、初回1回と準備後3回を実行した。各ケースの時間上限は300秒。元の全試行と結果フォルダは [`E1_comparison.csv`](../../tables/E1_comparison.csv) の `result_directory` から参照できる。週次設定は [`e1_week.json`](../../config/e1_week.json)、日次・週次の生比較は `comparison.csv` と `comparison_week.csv` に保存した。

## 確認できたこと

1. 日次は24/24件、週次は20/24件が成功し、成功した44解すべてが独立評価に合格した。週次のDP145点4件はすべて300秒で時間切れとなり、失敗解を費用比較へ含めていない。
2. 両期間でDP格子を19→37→73点へ細かくすると、成功費用差が小さくなった。1日ではDP145点も成功して基準との差がさらに縮まった。週次のDP145点は上限内に完了せず、精度を評価できない。
3. 週次の成功最小費用は270,019.91円、蓄電池待機解は288,781.69円だった。週次DP19/37/73点の中央値費用はそれぞれ285,007.91 / 281,046.97 / 275,698.68円。DP73点の全処理時間中央値は約53.6秒、ピークRSS中央値は約21.5 MiB。

## 図表

- [`E1_comparison.csv`](../../tables/E1_comparison.csv)：日次・週次の全48試行、成功状態、費用、時間、メモリ、評価状態、元結果へのパス。
- [`E1_summary.csv`](../../tables/E1_summary.csv)：成功試行の中央値と独立評価の集計。
- [`E1_cost_time.png`](../../figures/E1_cost_time.png)：費用差と計算時間。
- [`E1_soc_operation.png`](../../figures/E1_soc_operation.png)：SOC、充放電、買電の時系列。
- [`E1_inputs.png`](../../figures/E1_inputs.png)：価格、PV、需要の時系列。

## 再現コマンド

日次の試行：

```bash
../.venv/bin/python src/run_experiments.py --config config/common_problem.json --experiment-id E1 --identifier day
```

週次の試行：

```bash
../.venv/bin/python src/run_experiments.py --config config/e1_week.json --experiment-id E1 --identifier week --comparison-output experiments/E1_initial/comparison_week.csv --report-output experiments/E1_initial/REPORT_week.md
```

両結果を統合して表・図・本報告を再生成：

```bash
../.venv/bin/python src/summarize_e1.py
```

## 未確認事項

この比較は2025-07-22開始の1日・1週間に限られ、季節、設備容量・出力、時間刻みへの一般化は未確認。固定価格条件のため、価格変動の効果も扱っていない。週次DP145点は300秒上限で完了せず、より大きい予算での目的値と必要時間は不明。

## 次の実験条件（T10への入力）

週次のDP145点はE2の初期計画から除外せず、300秒・2 GiBの共通予算で再確認する対象とする。最初に1/7/30日の期間×19/37/73点を同じ30分刻み・固定価格・設備条件で比較し、145点は1日・1週間の追加確認枠に分ける。季節ケースと30/60分の時間刻み、設備条件の変更は要因を混ぜず、期間選定と総計算量をT10で確定する。
