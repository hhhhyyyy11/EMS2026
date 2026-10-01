# 共通設定

数理計画法とDPの両方が読む共通設定を保存する。

- `common_problem.json`: T01・T02で確定した入力期間、固定価格、設備、SOC格子、基本料金、計算予算、結果保存規則の正本。
- `e1_week.json`: E1/T09の2025-07-22開始7日間。
- `e2_d30.json`, `e2_t60.json`: E2の30日30分値と7日60分集約。
- `e3_winter.json`, `e3_spring.json`, `e3_autumn.json`: E3の事前指定季節週。夏週は `e1_week.json` を再利用。
- `e4_low.json`, `e4_high.json`: E4の内部出力上限215 kW、645 kW。基準400 kWは `e1_week.json` を再利用。
- 設定内の相対パスは、設定ファイルがあるこのディレクトリを基準に解決する。
- 読込みと入力期間・保存先の事前検査は `../src/check_run_setup.py` を使う。
