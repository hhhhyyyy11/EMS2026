# 共通実行・結果保存プロトコル

作業ID: T03  
適用範囲: E0〜E5の数理計画法・DP共通実行

## 1. 設定とパスの基準

正本は `config/common_problem.json` とする。設定内の入力パスと結果ルートは、作業ディレクトリではなく、読み込んだ設定ファイルのある `config/` を基準に解決する。このため、どのディレクトリから実行しても同じ入力と保存先を指す。

共通入力は `2026_Research/Data/common_energy_data.xlsx` を読み取り専用で参照する。日時の正規化、kWh/区間からkWへの変換、価格系列などの派生データを保存する場合は、元ファイルを変更せず、この論文フォルダの実行結果内へ保存する。

既定期間は半開区間 `[2025-07-22 00:00+09:00, 2025-07-23 00:00+09:00)` の48区間である。価格は全区間で21.51円/kWhとする。7日ケースなどは、実験別設定として共通設定の期間だけを明示的に上書きし、実行時の有効設定全体を保存する。

## 2. 実行前検査

論文フォルダを起点に、次を実行する。

```bash
../.venv/bin/python src/check_run_setup.py \
  --config config/common_problem.json \
  --experiment-id E1 \
  --identifier preflight
```

この検査は、設定の必須値と範囲、SOC格子への初期・終端SOCの包含、格子の入れ子関係、入力ファイルの存在とSHA-256、必須列、非負値、日時の5 ms補正、重複、30分連続性、利用可能期間17,520点、対象期間48点、および保存先候補を確認する。検査に失敗した場合は求解へ進まない。

`--initialize-output` を付けると保存先を原子的に予約し、有効な共通設定を `config.json` としてコピーする。同名ディレクトリが存在する場合はエラーで終了し、上書きしない。通常の実験ランナーは、この予約処理と同じ排他規則を使う。

## 3. 計算予算

- 1ケースの時間制限: 300秒。
- 1実行のメモリ目安: 2 GiB。
- SCIPの初期設定: 1スレッド、相対MIPギャップ0。終了状態、最良境界、実際のギャップを結果へ記録する。
- 実行直前に空き容量、実メモリ、OS、CPU、Python・主要パッケージ・ソルバーの版を確認して `environment.json` に記録する。
- 予算超過は失敗を隠さず、時間切れまたは資源上限として `summary.json` と `run.log` に残す。

## 4. 保存先と上書き防止

1回の実行を次の1ディレクトリへ保存する。

```text
results/<実験ID>_<YYYYMMDDTHHMMSS+0900>_<識別子>/
```

実験IDと識別子には英数字、ピリオド、アンダースコア、ハイフンだけを使う。日時はAsia/Tokyoの実行開始時刻で、UTCオフセットを含める。例は `results/E1_20260915T103000+0900_milp-day/` である。同名がある場合は新しい日時または識別子を使い、既存ディレクトリを削除・再利用・上書きしない。

各実行ディレクトリには次の5ファイルを必ず置く。

| ファイル | 内容 |
|---|---|
| `config.json` | 共通設定と実験別変更を反映した有効設定。入力パス、対象期間、手法、格子数を含む |
| `environment.json` | 実行日時、Git commitと未完了変更の有無、OS、CPU、メモリ、空き容量、Python・依存パッケージ・ソルバー版 |
| `summary.json` | 終了状態、料金内訳、最大買電、制約違反、時間、メモリ、手法固有指標 |
| `trajectory.csv` | 1行1区間の共通時系列。日時、需要、PV、価格、買電、PV利用、内部充放電、区間始終SOCを含む |
| `run.log` | 実行開始・終了、段階別時間、警告、例外、標準出力・標準エラーの要約 |

JSONはUTF-8、キーは英語、数値は単位をキー名へ含め、NaNやInfinityを保存しない。CSVはUTF-8、日時はUTCオフセット付きISO 8601とする。金額の単位は円、電力はkW、電力量とSOC実体はkWh、時間は秒とする。

## 5. `summary.json` の共通項目

最低限、次の項目を全手法で保存する。

```text
schema_version, run_id, experiment_id, method, status,
objective_yen, energy_charge_yen, basic_charge_yen,
maximum_purchased_power_kW, contract_equivalent_power_kW,
maximum_constraint_violation, solve_time_seconds,
total_time_seconds, peak_memory_mib, message
```

数理計画法は `solver_status`、`best_bound_yen`、`relative_gap`、`model_build_time_seconds` を加える。DPは `soc_grid_count`、`soc_grid_step_kWh`、`transition_count`、`maximum_nondominated_labels`、`initial_compile_time_seconds`、`prepared_solve_time_seconds` を加える。値を取得できない場合は項目を省略せず `null` とし、理由を `message` と `run.log` に記録する。

`objective_yen` は `energy_charge_yen + basic_charge_yen` と一致させる。`maximum_purchased_power_kW` と `contract_equivalent_power_kW` は本研究では同じ対象期間最大買電であり、外生的な買電上限ではない。成功扱いにする前にT04の独立評価処理で料金と全制約を再計算する。

## 6. 実験記録とGit方針

`results/` 以下の数値結果はリポジトリ最上位の `.gitignore` にある `**/results/` によりGit管理対象外とする。実行ログも `*.log` の対象である。実行前には次で除外を確認する。

```bash
git check-ignore -v results/E1_probe/summary.json results/E1_probe/trajectory.csv results/E1_probe/run.log
```

一方、各実験の目的、設定差分、実行コマンド、実行ID、結果ディレクトリへの対応、結果の短い要約は `experiments/E*/` のMarkdownへ残し、Git管理する。再現コマンド自体を `results/` だけに置かない。大きな派生CSVを `experiments/` に複製せず、必要な表はT09以降の規則に従う。

## 7. 実行後の合否

保存前に有限数値と配列長を検査し、一時名で全ファイルを書いた後に1回の実行ディレクトリとして確定する。正常終了時は5ファイルの存在、設定の入力識別子、対象期間、行数、料金内訳、制約検査結果を照合する。途中終了でも取得できた環境・状態・時間・例外を残し、成功と表示しない。

実験レポートには、実行コマンド、使用した `run_id`、成功・時間切れ・失敗、確認済みの事実、未確認事項を記載する。結果の解釈はこの実行記録から元の有効設定と数値ファイルへたどれる場合だけ確定する。
