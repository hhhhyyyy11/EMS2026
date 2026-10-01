# 実験記録

各実験の目的、入力期間、設定、実行方法、コード版、環境、結果への参照を保存する。

- `E0_validation/`: 実装の正しさ
- `E1_initial/`: 最初の実データ比較
- `E2_period_grid/`: 30日、60分集約の追加結果。1日・7日30分はE1結果を再利用。
- `E3_season/`: 冬・春・秋の追加週。夏週はE1週次結果を再利用。
- `E4_battery/`: 低・高出力の追加結果。基準出力はE1週次を再利用。
- `T11_REPORT.md`: E2〜E5の統合解釈、RQ別の図表、限界、追加実験判断。
- E5の選択表と全条件の集約は `../tables/E5_selection.csv`、`../tables/T11_medians.csv`、生試行表は `../tables/T11_all_runs.csv`。
