# -*- coding: utf-8 -*-
import sys
import os
import argparse
import time
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from fpdf import FPDF
from pyscipopt import Model

# Sharedモジュールのインポート設定
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from Shared import data_loader

start_time = time.perf_counter()
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 処理系に応じたフォント設定
if os.name == 'nt':
    plt.rcParams['font.family'] = 'Meiryo'
elif os.name == 'posix':
    plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# 引数の処理
parser = argparse.ArgumentParser(description='Dynamic LP optimization runner')
parser.add_argument(
    '--config',
    default=os.path.join(PROJECT_ROOT, 'config.json'),
    help='Path to config.json',
)
parser.add_argument('--sheet', default='30分値', help='Excel sheet name for energy data')
parser.add_argument('--objective_mode', default=None, help='Objective mode: minimize_total_cost or minimize_peak (overrides config)')
args, unknown = parser.parse_known_args()

# 設定とデータのロード
config = data_loader.load_config(args.config)
print(f"Loaded config from {args.config}")
print(f"Price plan: {config.get('price_plan', 'fixed_price')}")

df_trend = data_loader.get_simulation_data(args.config, sheet_name=args.sheet)

# 計画期間の設定
K = len(df_trend)
print(f"Total steps (K): {K} ({K * 0.5 / 24:.1f} days)")

# バッテリーパラメータのロード
battery_config = config.get('battery', {})
bF_max = battery_config.get('capacity_kWh', 860.0)
aFC = battery_config.get('charge_limit_kW', 400.0)
aFD = battery_config.get('discharge_limit_kW', 400.0)
alpha_FC = battery_config.get('charge_efficiency', 0.98)
alpha_FD = battery_config.get('discharge_efficiency', 0.98)
initial_soc_ratio = battery_config.get('initial_soc_ratio', 0.5)

bF0 = bF_max * initial_soc_ratio  # バッテリーの初期SOC [kWh]

# 共通データからの物理量マッピング
# 共通データは [kW] 単位の平均電力値
gP1 = df_trend['pv_kW'].values  # 太陽光発電 [kW]
gP1[gP1 < 0] = 0.0

# 既存モデルとの互換性のため消費電力をA, B, Cに分ける（Aにすべて集約し、BとCは0にする）
dA2 = df_trend['consumption_kW'].values.tolist()  # 総消費電力 [kW]
dB2 = [0.0] * K
dC2 = [0.0] * K

# 料金プラン
pBY = df_trend['price_yen_per_kWh'].values.tolist()  # 買電単価 [円/kWh]
pSL = [0.0] * K  # 売電単価 (逆潮流不可のため0円)

# 買電上限（仕様書ベース）
sBYMAX = 1000.0  # 十分に大きな契約電力 [kW]

# 目的関数の重み
pBYMAX_weight = 2829.60 * 0.85 * 12 * (K * 0.5) / (24 * 365)  # 契約電力（基本料金）の按分重み

# 目的関数モードの決定（CLI引数優先、なければconfig.json）
objective_mode = args.objective_mode if args.objective_mode else config.get('objective_mode', 'minimize_total_cost')
print(f"Objective mode: {objective_mode}")

# 最適化モデルの作成
model = Model('PowerOptimization_LP_30min')

# 変数の定義 (30分値に対応)
sBY = {k: model.addVar(vtype='C', name=f'sBY_{k}', lb=0) for k in range(K)}
sSL = {k: model.addVar(vtype='C', name=f'sSL_{k}', lb=0) for k in range(K)}
v = {k: model.addVar(vtype='C', name=f'v_{k}', lb=0) for k in range(K)}

gP2 = {k: model.addVar(vtype='C', name=f'gP2_{k}', lb=0) for k in range(K)}

dA1 = {k: model.addVar(vtype='C', name=f'dA1_{k}', lb=0) for k in range(K)}
dB1 = {k: model.addVar(vtype='C', name=f'dB1_{k}', lb=0) for k in range(K)}
dC1 = {k: model.addVar(vtype='C', name=f'dC1_{k}', lb=0) for k in range(K)}

bF = {k: model.addVar(vtype='C', name=f'bF_{k}', lb=0) for k in range(K)}
xFC1 = {k: model.addVar(vtype='C', name=f'xFC1_{k}', lb=0) for k in range(K)}
xFC2 = {k: model.addVar(vtype='C', name=f'xFC2_{k}', lb=0) for k in range(K)}
xFD1 = {k: model.addVar(vtype='C', name=f'xFD1_{k}', lb=0) for k in range(K)}
xFD2 = {k: model.addVar(vtype='C', name=f'xFD2_{k}', lb=0) for k in range(K)}

sBYMAX_var = model.addVar(vtype='C', name='sBYMAX_var', lb=0)

# 非同時充放電のためのバイナリ変数
z = {k: model.addVar(vtype='B', name=f'z_{k}') for k in range(K)}

# 目的関数の設定
# 30分値のため、電力量 [kWh] への換算として * 0.5 をかける
if objective_mode == 'minimize_peak':
    # 案1：最大買電電力（ピーク）の最小化のみ
    model.setObjective(sBYMAX_var, 'minimize')
else:
    # 案2（既存）：基本料金 + 電力量料金のトータルコスト最小化
    model.setObjective(
        pBYMAX_weight * sBYMAX_var +
        sum(pBY[k] * sBY[k] * 0.5 - (pSL[k] - 1e-9) * sSL[k] * 0.5 for k in range(K)),
        'minimize'
    )

# 制約の追加
M = 1e6  # 大きな定数

for k in range(K):
    # 電力バランス制約: PV発電 + 買電 - 売電 - 充電 + 放電 - 需要 - 無駄電力 == 0
    model.addCons(gP2[k] + sBY[k] - sSL[k] - xFC1[k] + xFD2[k] - dA1[k] - dB1[k] - dC1[k] - v[k] == 0)

    # PV発電量の制約 (変換ロスを考慮しない簡易版、または効率1.0)
    model.addCons(gP2[k] <= gP1[k])

    # 需要データのマッピング
    model.addCons(dA1[k] == dA2[k])
    model.addCons(dB1[k] == dB2[k])
    model.addCons(dC1[k] == dC2[k])

    # バッテリーSOC更新式 (30分ステップなので 0.5 を乗算)
    if k > 0:
        model.addCons(bF[k] == bF[k - 1] + 0.5 * xFC2[k] - 0.5 * xFD1[k])
    else:
        model.addCons(bF[k] == bF0 + 0.5 * xFC2[k] - 0.5 * xFD1[k])

    # バッテリー容量・SOCの上下限 (5%〜95%)
    model.addCons(bF[k] <= bF_max * 0.95)
    model.addCons(bF[k] >= bF_max * 0.05)

    # 充放電変換効率制約
    model.addCons(xFC2[k] == alpha_FC * xFC1[k])
    model.addCons(xFD2[k] == alpha_FD * xFD1[k])

    # 充放電電力上限
    model.addCons(xFC2[k] <= aFC)
    model.addCons(xFD1[k] <= aFD)

    # 非同時充放電制約 (充電 xFC1 と 放電 xFD1 が同時に行われない)
    model.addCons(xFC1[k] <= M * z[k])
    model.addCons(xFD1[k] <= M * (1 - z[k]))

    # 最大買電電力（デマンド）制約
    model.addCons(sBY[k] <= sBYMAX_var)

# 最適化の実行
print("最適化計算を実行中 (SCIP)...")
model.setParam('limits/time', 1800)  # 制限時間を30分に設定
model.optimize()

status = model.getStatus()
if status in ("optimal", "timelimit") and model.getNSols() > 0:
    if status == "optimal":
        print("最適解が見つかりました。")
    else:
        print(f"制限時間内に最適解は確定しませんでしたが、実行可能解が見つかりました (Gap: {model.getGap()*100:.4f}%)。")
    print(f"最適目的関数値: {model.getObjVal():.2f}")
    
    # 共通結果集計
    peak_demand = model.getVal(sBYMAX_var)
    energy_cost = sum(pBY[k] * model.getVal(sBY[k]) * 0.5 for k in range(K))
    # 基本料金の事後計算: 基本料金単価 2,829.60 円/kW × 力率割引 0.85 × 12ヶ月
    annual_basic_cost = peak_demand * 2829.60 * 0.85 * 12
    total_cost = annual_basic_cost + energy_cost
    
    print(f"=== 結果サマリ ({objective_mode}) ===")
    print(f"最大買電電力 (ピークデマンド): {peak_demand:.2f} kW")
    print(f"年間電力量料金: {energy_cost:.0f} 円")
    print(f"年間基本料金 (事後計算): {annual_basic_cost:.0f} 円")
    print(f"年間トータルコスト: {total_cost:.0f} 円")
else:
    print(f"最適解が見つかりませんでした。ステータス: {model.getStatus()}")

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"処理時間: {elapsed_time:.3f}秒")

# 結果の取得とCSV出力
results = []
for k in range(K):
    results.append([
        k,
        gP1[k], model.getVal(gP2[k]), model.getVal(dA1[k]), dA2[k],
        model.getVal(sBY[k]) - model.getVal(sSL[k]), model.getVal(xFC1[k]),
        model.getVal(xFC2[k]), model.getVal(xFD1[k]), model.getVal(xFD2[k]), model.getVal(bF[k]),
        model.getVal(sBY[k]), model.getVal(sSL[k]), pBY[k]
    ])

columns = [
    'k', 'pv_available', 'pv_used', 'demand_staged', 'demand_actual',
    'net_grid_flow', 'charge_input', 'charge_stored', 'discharge_output', 'discharge_used',
    'bF_soc', 'sBY', 'sSL', 'electricity_price'
]

df_results = pd.DataFrame(results, columns=columns)
df_results.index = df_trend.index

output_dir = os.path.join(PROJECT_ROOT, 'results', 'lp_baseline')
os.makedirs(output_dir, exist_ok=True)
output_filename = os.path.join(output_dir, f'dynamic_lp_results_{objective_mode}.csv')
df_results.to_csv(output_filename, index=True)
print(f"結果を '{output_filename}' に保存しました。")
