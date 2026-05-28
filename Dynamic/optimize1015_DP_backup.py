import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import time
import os
import pandas as pd
import unicodedata
import numba

#買電と売電を考慮した電力運用最適化モデル(DP)
start_time = time.perf_counter()

# NumbaのJITデコレータを適用した計算関数
@numba.jit(nopython=True)
def run_dp_calculation(K, B, soc_levels, cost_table, path_table, gP1, dA2, dB2, dC2, pBY,
                       alpha_P, alpha_DA, alpha_DB, alpha_DC, 
                       alpha_FC, alpha_FD, aFC_max, aFD_max): # 修正点: beta変数を削除
    
    # メインのDP計算ループ
    for k in range(1, K):
        # 進行状況の表示（JITコンパイルモードではprintは無視されることが多いですが、デバッグ用に残します）
        #if k % 100 == 0: 
         #   print(str(k) + "/" + str(K))
        
        # 変換前の負荷電力と変換後の発電電力を計算
        load_pre_conversion = (dA2[k] / alpha_DA) + (dB2[k] / alpha_DB) + (dC2[k] / alpha_DC)
        gen_post_conversion = alpha_P * gP1[k] 
        rest = load_pre_conversion - gen_post_conversion
        rest_index = (int) (round((load_pre_conversion - gen_post_conversion)*(B-1)/bF_max))

        for j in range(B):  # 現在の状態インデックス
            b_curr = soc_levels[j]
            

                #2051015追記：放電も辺の数を制限
            step_size = 0.2
            aFD_max2 = 50 / 60
            for i in range(max(0, j - int(aFD_max2 / step_size + 1)+ rest_index), min(B, j + int(aFC_max / step_size) + rest_index) + 1):  # 過去の状態インデックス
                if np.isinf(cost_table[k - 1, i]):
                    continue

                b_prev = soc_levels[i]
                
                # 修正点: PDFの式(5)に従い、単純な引き算で充電/放電量を計算
                x_k_FC2_signed = b_curr - b_prev

                # 修正点: PDFの式(6)に従って系統買電量を計算
                sBY_k = 0.0
                if x_k_FC2_signed >= 0: # 充電時
                    sBY_k = load_pre_conversion + (x_k_FC2_signed / alpha_FC) - gen_post_conversion
                else: # 放電時
                    sBY_k = load_pre_conversion + (alpha_FD * x_k_FC2_signed) - gen_post_conversion
                
                # コスト計算（pBYは正負両方の値を取り、売電も表現）
                current_step_cost = pBY[k] * sBY_k
                #買電の方を重きをおく
                if sBY_k > 0:
                    current_step_cost += current_step_cost * bF_max

                total_cost = cost_table[k - 1, i] + current_step_cost

                if total_cost < cost_table[k, j]:
                    cost_table[k, j] = total_cost
                    path_table[k, j] = i
    
    return cost_table, path_table

# --- メインスクリプト ---

# OSに応じてフォントを設定
if os.name == 'nt':
    plt.rcParams['font.family'] = 'Meiryo'
if os.name == 'posix':
    plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# Excelファイルの読み込み
excel_path = '20250703_20250721テクシード工場トレンドデータ.xlsx'
excel_path = unicodedata.normalize("NFC", excel_path)
xls = pd.ExcelFile(excel_path)
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0, skiprows=[1])


# データの前処理
#df_trend['datetime'] = pd.to_datetime(
#    df_trend.iloc[:, 0].astype(str) + ' ' +
#    pd.to_datetime(df_trend.iloc[:, 1], errors='coerce').dt.strftime('%H:%M:%S'),
#    errors='coerce'
#)
df_trend['datetime'] = pd.to_datetime(
    df_trend['日'].astype(str) + ' ' + df_trend['時間(分刻み)'].astype(str),
    format='%Y-%m-%d %H:%M:%S',
    errors='coerce'
)


df_trend.set_index('datetime', inplace=True)
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)

# 計画期間とパラメータの設定
K = len(df_trend)

# 定数の定義
bF_max = 2742
aFC_max = 450 / 60
aFD_max = 450 / 60
bF0 = df_trend['蓄電池'].iloc[:K].ffill().iloc[0] * 0.01 * bF_max

# 入力データベクトルの準備
gP1 = (df_trend['太陽光発電電力'].iloc[:K].ffill().values / 60)
gP1[gP1 < 0] = 0
dA2 = (df_trend['6600/210-105V 75kVA 全体'].iloc[:K].ffill().values) / 60
dB2 = (df_trend['6600/210V 300kVA 全体'].iloc[:K].ffill().values) / 60
dC2 = (df_trend['6600/210V 500kVA 全体'].iloc[:K].ffill().values) / 60
pBY = df_trend['売買電単価'].iloc[:K].ffill().values

s_actual = (df_trend['系統購入電力'].iloc[:K].ffill().values) / 60
xFD1_xFC2_actual = (df_trend['蓄電池MegaPower放電電力'].iloc[:K].ffill().values) / 60
bF_actual = df_trend['蓄電池'].iloc[:K].ffill().values * 0.01 * bF_max
solar_radiation = df_trend['日射量'].iloc[:K].ffill().values

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"データの読み込みに要した時間: {elapsed_time:.5f}秒")
start_time = time.perf_counter()

# バッテリー状態（SOC）の離散化
#20251015 step_sizeを0.4から0.2に変更
step_size = 0.2
B = int(np.ceil(bF_max / step_size)) + 1
soc_levels = np.linspace(0, bF_max, B)

# DPテーブルの初期化
cost_table = np.full((K, B), np.inf)
path_table = np.zeros((K, B), dtype=np.int64)

# 初期状態の設定
initial_soc_idx = np.argmin(np.abs(soc_levels - bF0))
cost_table[0, initial_soc_idx] = 0

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"多段ネットワークの構成に要した時間: {elapsed_time:.5f}秒")
start_time = time.perf_counter()

print("Numbaによる高速計算を開始します...")
# 高速化された関数を呼び出し
cost_table, path_table = run_dp_calculation(
    K, B, soc_levels, cost_table, path_table, gP1, dA2, dB2, dC2, pBY,
    0.94, 0.94, 0.94, 0.94, 0.94, 0.94, aFC_max, aFD_max # 修正点: beta変数を削除し、alphaのみに
)

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"DP計算に要した時間: {elapsed_time:.5f}秒")

# バックトラッキングによる最適経路の探索
optimal_path_indices = np.zeros(K, dtype=np.int64)
optimal_path_indices[K - 1] = np.argmin(cost_table[K - 1, :])
for k in range(K - 1, 0, -1):
    optimal_path_indices[k - 1] = path_table[k, optimal_path_indices[k]]

# 最適経路に基づいた解の再構築
results = []
bF_prev = bF0
# 修正点: beta変数を削除
aP, aDA, aDB, aDC, aFC, aFD = 0.94, 0.94, 0.94, 0.94, 0.94, 0.94

for k in range(K):
    optimal_idx = optimal_path_indices[k]
    bF_k = soc_levels[optimal_idx]

    gP2_k = aP * gP1[k]
    dA1_k = dA2[k] / aDA if aDA != 0 else 0
    dB1_k = dB2[k] / aDB if aDB != 0 else 0
    dC1_k = dC2[k] / aDC if aDC != 0 else 0
    
    # 修正点: PDFの式(5)に従う
    net_charge_required = bF_k - bF_prev
    xFC2_k, xFD1_k_pre = (net_charge_required, 0) if net_charge_required >= 0 else (0, -net_charge_required)
    
    xFC1_k = xFC2_k / aFC if aFC != 0 else 0
    xFD2_k = aFD * xFD1_k_pre

    # 修正点: PDFの式(6)に従う
    load_pre = dA1_k + dB1_k + dC1_k
    sBY_k = 0.0
    if net_charge_required >= 0:
        sBY_k = load_pre + xFC1_k - gP2_k
    else:
        sBY_k = load_pre - xFD2_k - gP2_k 

    results.append([
        k, 
        gP1[k] * 60, gP2_k * 60, dA1_k * 60, dA2[k] * 60, dB1_k * 60,
        dB2[k] * 60, dC1_k * 60, dC2[k] * 60, sBY_k * 60, xFC1_k * 60,
        xFC2_k * 60, xFD1_k_pre * 60, xFD2_k * 60, bF_k, bF_actual[k],
        s_actual[k] * 60, (xFD1_k_pre * 60 - xFC2_k * 60), xFD1_xFC2_actual[k] * 60,solar_radiation[k], pBY[k]
    ])
    bF_prev = bF_k

# (結果の出力とグラフ作成部分は変更ありません)
columns = ['k', 
           'gP1', 'gP2', 'dA1', 'dA2','dB1', 
           'dB2', 'dC1', 'dC2', 'sBY','xFC1', 
           'xFC2', 'xFD1', 'xFD2', 'bF','bF_actual', 
           's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual', 'solar_radiation','pBY']
unit = ['[kW]', '[kW]', '[kW]', '[kW]', '[kW]', 
        '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', 
        '[kW]', '[kW]', '[kW]','[kWh]', '[kWh]', 
        '[kW]', '[kW]', '[kW]', '[W/m2]', '[yen/kWh]']

name = [
    'Solar PV Generation (Before Conversion)', 'Solar PV Generation (After Conversion)', 
    'Power Consumption A (Before Conversion)', 'Power Consumption A (After Conversion)',
    'Power Consumption B (Before Conversion)', 'Power Consumption B (After Conversion)', 
    'Power Consumption C (Before Conversion)', 'Power Consumption C (After Conversion)', 
    'Grid Power Purchase', 'Battery Charge Amount (Before Conversion)', 
    'Battery Charge Amount (After Conversion)', 'Battery Discharge Amount (Before Conversion)', 
    'Battery Discharge Amount (After Conversion)','Battery State of Charge', 
    'Actual Battery State of Charge', 'Actual Grid Power Purchase', 
    'Battery Discharge/Charge Amount','Actual Battery Discharge/Charge Amount', 
    'Solar Radiation','Electricity Purchase Unit Price',
]

ymin = [0, 0, 0, 0, 0,
        0, 0, 0, -500, 0,
        0, 0, 0, 0, 0, 
        -500, -500, -500, 0, 0]
ymax = [250, 250, 250, 250, 250, 
        250, 250, 250, 250, 500, 
        500, 500, 500, bF_max, bF_max, 
        250, 500, 500, 1400, 50]
color = ['green', 'blue', 'blue', 'green', 'blue', 
         'green', 'blue', 'green', 'blue', 'blue', 
         'blue', 'blue','blue', 'red', 'green', 
         'green', 'blue', 'green', 'green','green']

df_results = pd.DataFrame(results, columns=columns)
df_results.index = df_trend.index
csv_output_path = 'optimization_results_DP.csv'
df_results.to_csv(csv_output_path, index=False)

png_output_dir = 'png_DP'
os.makedirs(png_output_dir, exist_ok=True)
variables = df_results.columns[1:]

for i, var in enumerate(variables):
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(df_results.index, df_results[var], label=var, color=color[i])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M'))
    plt.xlabel('')
    plt.ylabel(f'{var}: {unit[i]}')
    plt.legend()
    plt.grid()
    y_min, y_max = ymin[i], ymax[i]
    margin = (y_max - y_min) * 0.05 if (y_max - y_min) > 0 else 1
    ax.set_ylim(y_min - margin, y_max + margin)
    fig.text(0.5, 0.00, 'time', ha='center', va='bottom', fontsize=16)
    img_path = os.path.join(png_output_dir, f'{var}.png')
    plt.savefig(img_path, dpi=300)
    plt.close()

print(f"スクリプトの準備ができました。結果は {csv_output_path} に保存されます。")
print(f"グラフは {png_output_dir} ディレクトリに保存されます。")