# E1：weekケース比較

実行開始: 2026-09-23T22:19:30.261499+09:00

## 条件

2025-07-22〜2025-07-28の336区間（168時間、30分値）、固定価格21.51円/kWh、蓄電池860 kWh・内部400 kW、初期/終端SOC 50%。LP、MILP、19/37/73/145点DPを各1回の初回実行と準備後3回で計24回実行した。各求解の上限は300秒。成功解は独立評価器で全制約と料金内訳を再計算した。

## 結果

差額基準は成功した実行の最小費用 270019.913008 円。基準が0円に近い場合は相対差を空欄とした。MILPの最適性が未確定なら、基準との差は真の最適解からの誤差とは解釈しない。

| case_id | method | grid_count | replicate | phase | status | solver_status | objective_yen | maximum_purchased_power_kW | basic_charge_yen | energy_charge_yen | cost_difference_yen | relative_difference | solve_time_seconds | total_time_seconds | peak_memory_mib | maximum_constraint_violation | evaluation_status | best_bound_yen | relative_gap | run_id | result_directory | message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1-week-lp-r0 | lp | — | 0 | initial | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 5.82077e-11 | 2.15568e-16 | 0.068538 | 0.200323 | 0.982082 | 2.73559e-13 | pass | 270020 | 0 | E1-week-lp-r0 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221934+0900_lp-r0 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-lp-r1 | lp | — | 1 | prepared | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 5.82077e-11 | 2.15568e-16 | 0.043534 | 0.113267 | 0.907887 | 2.73559e-13 | pass | 270020 | 0 | E1-week-lp-r1 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221935+0900_lp-r1 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-lp-r2 | lp | — | 2 | prepared | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 5.82077e-11 | 2.15568e-16 | 0.0682593 | 0.332035 | 0.87566 | 2.73559e-13 | pass | 270020 | 0 | E1-week-lp-r2 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221935+0900_lp-r2 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-lp-r3 | lp | — | 3 | prepared | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 5.82077e-11 | 2.15568e-16 | 0.328092 | 0.842533 | 0.883549 | 2.73559e-13 | pass | 270020 | 0 | E1-week-lp-r3 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221935+0900_lp-r3 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-milp-r0 | milp | — | 0 | initial | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 0 | 0 | 1.32885 | 1.44868 | 1.06593 | 1.94067e-13 | pass | 270020 | 0 | E1-week-milp-r0 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221937+0900_milp-r0 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-milp-r1 | milp | — | 1 | prepared | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 0 | 0 | 0.655148 | 0.748272 | 1.10472 | 1.94067e-13 | pass | 270020 | 0 | E1-week-milp-r1 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221938+0900_milp-r1 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-milp-r2 | milp | — | 2 | prepared | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 0 | 0 | 0.484143 | 0.554129 | 1.08593 | 1.94067e-13 | pass | 270020 | 0 | E1-week-milp-r2 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221939+0900_milp-r2 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-milp-r3 | milp | — | 3 | prepared | success | optimal | 270020 | 69.5848 | 38516.3 | 231504 | 0 | 0 | 0.367501 | 0.473679 | 1.10897 | 1.94067e-13 | pass | 270020 | 0 | E1-week-milp-r3 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221940+0900_milp-r3 | SCIP returned a feasible solution and independent evaluation passed. |
| E1-week-dp-19-r0 | dp | 19 | 0 | initial | success | optimal | 285008 | 98 | 54244.6 | 230763 | 14988 | 0.055507 | 0.63237 | 0.637371 | 1.40091 | 0 | pass | 285008 | 0 | E1-week-dp-19-r0 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221940+0900_dp-19-r0 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-19-r1 | dp | 19 | 1 | prepared | success | optimal | 285008 | 98 | 54244.6 | 230763 | 14988 | 0.055507 | 0.321391 | 0.325795 | 1.38242 | 0 | pass | 285008 | 0 | E1-week-dp-19-r1 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221941+0900_dp-19-r1 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-19-r2 | dp | 19 | 2 | prepared | success | optimal | 285008 | 98 | 54244.6 | 230763 | 14988 | 0.055507 | 0.310065 | 0.314687 | 1.38262 | 0 | pass | 285008 | 0 | E1-week-dp-19-r2 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221941+0900_dp-19-r2 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-19-r3 | dp | 19 | 3 | prepared | success | optimal | 285008 | 98 | 54244.6 | 230763 | 14988 | 0.055507 | 0.307223 | 0.315292 | 1.38246 | 0 | pass | 285008 | 0 | E1-week-dp-19-r3 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221942+0900_dp-19-r3 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-37-r0 | dp | 37 | 0 | initial | success | optimal | 281047 | 90 | 49816.5 | 231231 | 11027.1 | 0.0408379 | 6.17161 | 6.18312 | 6.03838 | 0 | pass | 281047 | 0 | E1-week-dp-37-r0 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221942+0900_dp-37-r0 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-37-r1 | dp | 37 | 1 | prepared | success | optimal | 281047 | 90 | 49816.5 | 231231 | 11027.1 | 0.0408379 | 6.80768 | 6.81912 | 6.01091 | 0 | pass | 281047 | 0 | E1-week-dp-37-r1 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221948+0900_dp-37-r1 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-37-r2 | dp | 37 | 2 | prepared | success | optimal | 281047 | 90 | 49816.5 | 231231 | 11027.1 | 0.0408379 | 6.30221 | 6.31653 | 6.01049 | 0 | pass | 281047 | 0 | E1-week-dp-37-r2 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T221955+0900_dp-37-r2 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-37-r3 | dp | 37 | 3 | prepared | success | optimal | 281047 | 90 | 49816.5 | 231231 | 11027.1 | 0.0408379 | 6.64309 | 6.65643 | 6.01017 | 0 | pass | 281047 | 0 | E1-week-dp-37-r3 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222002+0900_dp-37-r3 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-73-r0 | dp | 73 | 0 | initial | success | optimal | 275699 | 80 | 44281.3 | 231417 | 5678.77 | 0.0210309 | 54.6992 | 54.7583 | 21.5528 | 0 | pass | 275699 | 0 | E1-week-dp-73-r0 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222008+0900_dp-73-r0 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-73-r1 | dp | 73 | 1 | prepared | success | optimal | 275699 | 80 | 44281.3 | 231417 | 5678.77 | 0.0210309 | 53.2088 | 53.2531 | 21.4685 | 0 | pass | 275699 | 0 | E1-week-dp-73-r1 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222103+0900_dp-73-r1 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-73-r2 | dp | 73 | 2 | prepared | success | optimal | 275699 | 80 | 44281.3 | 231417 | 5678.77 | 0.0210309 | 53.8337 | 53.879 | 21.4685 | 0 | pass | 275699 | 0 | E1-week-dp-73-r2 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222156+0900_dp-73-r2 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-73-r3 | dp | 73 | 3 | prepared | success | optimal | 275699 | 80 | 44281.3 | 231417 | 5678.77 | 0.0210309 | 50.6022 | 50.6629 | 21.468 | 0 | pass | 275699 | 0 | E1-week-dp-73-r3 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222250+0900_dp-73-r3 | DP found an optimal grid path and independent evaluation passed. |
| E1-week-dp-145-r0 | dp | 145 | 0 | initial | time_limit | time_limit | — | — | — | — | — | — | 300.116 | 300.192 | 94.7923 | — | — | — | — | E1-week-dp-145-r0 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222341+0900_dp-145-r0 | DP reached the time limit before completing all intervals. |
| E1-week-dp-145-r1 | dp | 145 | 1 | prepared | time_limit | time_limit | — | — | — | — | — | — | 300.12 | 300.191 | 94.7924 | — | — | — | — | E1-week-dp-145-r1 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T222841+0900_dp-145-r1 | DP reached the time limit before completing all intervals. |
| E1-week-dp-145-r2 | dp | 145 | 2 | prepared | time_limit | time_limit | — | — | — | — | — | — | 300.116 | 300.218 | 94.7924 | — | — | — | — | E1-week-dp-145-r2 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T223342+0900_dp-145-r2 | DP reached the time limit before completing all intervals. |
| E1-week-dp-145-r3 | dp | 145 | 3 | prepared | time_limit | time_limit | — | — | — | — | — | — | 300.194 | 300.273 | 95.5444 | — | — | — | — | E1-week-dp-145-r3 | /Users/yzhy/Documents/大学関係/2026前期/EMS/2026_Research/paper_method_comparison/results/E1_20260923T223842+0900_dp-145-r3 | DP reached the time limit before completing all intervals. |

## 待機解との照合

蓄電池を待機させた実行可能解は、最大買電 105.000000 kW、電力量料金 230662.485000 円、基本料金 58119.208767 円、合計 288781.693767 円。最も費用が高いDP19点でも 285007.913462 円で待機解を下回り、待機経路を含むモデルであることを確認した。

## 判定

成功 20 / 時間切れ 4 / 失敗 0。成功ケースの独立検査合格 20件。各行の `result_directory` に設定・環境・要約・時系列・ログを保存した。

## 再現

```bash
../.venv/bin/python src/run_experiments.py --config config/e1_week.json --experiment-id E1 --identifier week --comparison-output experiments/E1_initial/comparison_week.csv --report-output experiments/E1_initial/REPORT_week.md
```

## 未確認事項

この期間での初期比較であり、季節・設備条件への一般化は未確認。
