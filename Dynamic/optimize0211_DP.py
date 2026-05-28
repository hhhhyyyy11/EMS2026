from math import floor
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import time
import os
import pandas as pd
import unicodedata
import numba
from fpdf import FPDF

# 買電と売電を考慮した電力運用最適化モデル(DP)
start_time = time.perf_counter()

# フォント設定
if os.name == 'nt':
    plt.rcParams['font.family'] = 'Meiryo'
elif os.name == 'posix':
    plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# NumbaのJITデコレータを適用した計算関数
# K: データの期間数 (intervals)
@numba.jit(nopython=True)
def run_dp_calculation(K, B, soc_levels, cost_table, path_table, gP1, dA2, dB2, dC2, pBY,
                       alpha_P, alpha_DA, alpha_DB, alpha_DC,alpha_FC, alpha_FD,
                       aFC_max, aFD_max, sBY_max, step_size
                       ): 
    
    # メインのDP計算ループ
    # k は「時点」を表すインデックス。
    # k=0: 初期状態(期0始), k=1: 期0末, ..., k=K: 期(K-1)末
    for k in range(1, K + 1):
        # データ(gP1, dA2等)は 0〜K-1 のインデックスなので k-1 を参照
        data_idx = k - 1
        
        # 変換前の負荷電力と変換後の発電電力を計算
        load_pre_conversion = (dA2[data_idx] / alpha_DA) + (dB2[data_idx] / alpha_DB) + (dC2[data_idx] / alpha_DC)
        gen_post_conversion = alpha_P * gP1[data_idx] 
        rest = -load_pre_conversion + gen_post_conversion

        for j in range(B):  # 現在の状態インデックス (時点 k)
            b_curr = soc_levels[j]

            # 遷移可能な過去の状態インデックス (時点 k-1) の範囲を計算
            # 数式制約から探索範囲を絞る
            min_i = j - int(alpha_FC * (sBY_max + rest) / step_size)
            max_i = j + int(aFD_max / step_size)
            
            # インデックス境界のチェック
            start_i = max(0, min_i)
            end_i = min(B, max_i + 1) # rangeは未満なので+1

            for i in range(start_i, end_i):  
                if np.isinf(cost_table[k - 1, i]):
                    continue

                b_prev = soc_levels[i]
                
                # PDFの式(5)に従い、単純な引き算で充電/放電量を計算
                x_k_FC2_signed = b_curr - b_prev

                # PDFの式(6)に従って系統買電量を計算
                sBY_k = 0.0
                if x_k_FC2_signed >= 0: # 充電時 (b_curr >= b_prev)
                    sBY_k = (x_k_FC2_signed / alpha_FC) - rest
                else: # 放電時 (b_curr < b_prev)
                    sBY_k = (alpha_FD * x_k_FC2_signed) - rest

                # 制約チェック
                if sBY_k > sBY_max: # 買電制約 (50kW)
                    continue
                if sBY_k < -450.0 / 60.0: # 売電制約
                    continue 

                # コスト計算（pBYは正負両方の値を取り、売電も表現）
                current_step_cost = pBY[data_idx] * sBY_k
               
                # 売電についてはペナルティを付す(微小値)
                if sBY_k < 0:
                    current_step_cost -= pBY[data_idx] * sBY_k * 0.00001

                total_cost = cost_table[k - 1, i] + current_step_cost

                if total_cost < cost_table[k, j]:
                    cost_table[k, j] = total_cost
                    path_table[k, j] = i
    
    return cost_table, path_table

# --- メインスクリプト ---

# Excelファイルの読み込み
excel_path = '20250703_20250721テクシード工場トレンドデータ.xlsx'
excel_path = unicodedata.normalize("NFC", excel_path)
xls = pd.ExcelFile(excel_path)
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0, skiprows=[1])

# データの前処理
df_trend['datetime'] = pd.to_datetime(
    df_trend['日'].astype(str) + ' ' + df_trend['時間(分刻み)'].astype(str),
    format='%Y-%m-%d %H:%M:%S',
    errors='coerce'
)

df_trend.set_index('datetime', inplace=True)
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)

# 計画期間とパラメータの設定
K = len(df_trend) # データの行数（期間数）

# 定数の定義
bF_max = 2742
aFC_max = 450.0 / 60.0
aFD_max = 450.0 / 60.0
bF0 = df_trend['蓄電池'].iloc[:K].ffill().iloc[0] * 0.01 * bF_max
sBY_max = 50.0 / 60.0

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
step_size = 0.05
B = int(np.ceil(bF_max / step_size)) + 1
soc_levels = np.linspace(0, bF_max, B)

# DPテーブルの初期化
# サイズを K+1 に変更 (0:期0始, 1:期0末/期1始, ..., K:期K-1末)
cost_table = np.full((K + 1, B), np.inf)
path_table = np.zeros((K + 1, B), dtype=np.int64)

# 初期状態の設定 (インデックス0 = 期0始)
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
    0.94, 0.94, 0.94, 0.94, 0.94, 0.94, 
    aFC_max, aFD_max, sBY_max, step_size
)

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"DP計算に要した時間: {elapsed_time:.5f}秒")

# バックトラッキングによる最適経路の探索
# サイズは K+1
optimal_path_indices = np.zeros(K + 1, dtype=np.int64)
# 最終時点 K における最小コストのインデックスを取得
optimal_path_indices[K] = np.argmin(cost_table[K, :])

#--最適目的関数値の表示--
final_min_cost = cost_table[K, optimal_path_indices[K]]
print(f"最適解が見つかりました。")
print(f"最適目的関数値: {final_min_cost:.2f}")
#-----

# K から 1 まで戻りながら経路を復元
for k in range(K, 0, -1):
    optimal_path_indices[k - 1] = path_table[k, optimal_path_indices[k]]

# 最適経路に基づいた解の再構築
results = []
aP, aDA, aDB, aDC, aFC, aFD = 0.94, 0.94, 0.94, 0.94, 0.94, 0.94

# データフレーム作成用ループ (0 から K-1)
for k in range(K):
    # k はデータのインデックス。
    # DPの状態としては、k=始点、k+1=終点 を使用する。
    idx_prev = optimal_path_indices[k]
    idx_curr = optimal_path_indices[k + 1]
    
    bF_prev_val = soc_levels[idx_prev]
    bF_curr_val = soc_levels[idx_curr] # これが期0末、期1末...の値

    gP2_k = aP * gP1[k]
    dA1_k = dA2[k] / aDA if aDA != 0 else 0
    dB1_k = dB2[k] / aDB if aDB != 0 else 0
    dC1_k = dC2[k] / aDC if aDC != 0 else 0
    
    # 状態の差分から充放電量を計算
    net_charge_required = bF_curr_val - bF_prev_val
    xFC2_k, xFD1_k_pre = (net_charge_required, 0) if net_charge_required >= 0 else (0, -net_charge_required)
    
    xFC1_k = xFC2_k / aFC if aFC != 0 else 0
    xFD2_k = aFD * xFD1_k_pre

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
        xFC2_k * 60, xFD1_k_pre * 60, xFD2_k * 60, bF_curr_val, bF_actual[k], # bFは期末値を使用
        s_actual[k] * 60, (xFD1_k_pre * 60 - xFC2_k * 60), xFD1_xFC2_actual[k] * 60, solar_radiation[k], pBY[k]
    ])

columns = ['k', 
           'gP1', 'gP2', 'dA1', 'dA2','dB1', 
           'dB2', 'dC1', 'dC2', 'sBY','xFC1', 
           'xFC2', 'xFD1', 'xFD2', 'bF','bF_actual', 
           's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual', 'solar_radiation','pBY']
unit = ['[kW]', '[kW]', '[kW]', '[kW]', '[kW]', 
        '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', 
        '[kW]', '[kW]', '[kW]','[kWh]', '[kWh]', 
        '[kW]', '[kW]', '[kW]', '[W/m2]', '[yen/kWh]']

# グラフ描画とPDF生成処理は基本的に同じ（結果配列が正しくなっていればそのまま動作します）
# ... (以下、元のコードと同じグラフ描画・PDF生成部分)

df_results = pd.DataFrame(results, columns=columns)
df_results.index = df_trend.index
csv_output_path = 'optimization_results_DP.csv'
df_results.to_csv(csv_output_path, index=False)

# PDFの作成
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_font('Arial', style='', size=12)
pdf.cell(200, 10, ln=True, align='C')

variables = df_results.columns[1:]
figures = []

os.makedirs('png_DP', exist_ok=True)
color = ['green', 'blue', 'blue', 'green', 'blue', 
         'green', 'blue', 'green', 'blue', 'blue', 
         'blue', 'blue','blue', 'blue', 'green', 
         'green', 'blue', 'green', 'green','green']
ymin = [0, 0, 0, 0, 0,
        0, 0, 0, -500, 0,
        0, 0, 0, 0, 0, 
        -500, -500, -500, 0, 0]
ymax = [250, 250, 250, 250, 250, 
        250, 250, 250, 250, 500, 
        500, 500, 500, bF_max, bF_max, 
        250, 500, 500, 1400, 50]

for i, var in enumerate(variables):
    fig, ax = plt.subplots(figsize=(9, 6))
    
    # データをプロット
    ax.plot(df_results.index.to_pydatetime(), df_results[var].values, color=color[i], linewidth=1.5)

    # X軸のフォーマット設定
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M'))
    
    plt.ylabel(f'{var}: {unit[i]}')
    plt.grid(True)
    
    y_min_val, y_max_val = ymin[i], ymax[i]
    margin = (y_max_val - y_min_val) * 0.05 if y_max_val != y_min_val else 1.0
    ax.set_ylim(y_min_val - margin, y_max_val + margin)

    fig.text(0.5, 0.02, 'time', ha='center', va='bottom', fontsize=12)
    plt.tight_layout(rect=[0, 0.05, 1, 1]) 

    img_path = f'png_DP/{var}.png'
    plt.savefig(img_path, dpi=300)
    plt.close(fig)

    figures.append(img_path)

images_per_page = 8
img_w, img_h = 90, 60
x_positions = [10, 100]
y_positions = [20, 90, 160, 230]

for i, img in enumerate(figures):
    if i % images_per_page == 0 and i != 0:
        pdf.add_page()
    x_idx = (i % images_per_page) % 2
    y_idx = (i % images_per_page) // 2
    pdf.image(img, x=x_positions[x_idx], y=y_positions[y_idx], w=img_w, h=img_h)
    
pdf_output_path = 'Optimization_Results_DP.pdf'
pdf.output(pdf_output_path)

print(f"スクリプトの準備ができました。結果は {csv_output_path} に保存されます。")
print(f"PDFは {pdf_output_path} に保存されます。")