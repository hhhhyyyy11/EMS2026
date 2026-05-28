from pyscipopt import Model
import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
import os
import numpy as np
import matplotlib.dates as mdates
import unicodedata

# フォント設定
if os.name == 'nt':
    plt.rcParams['font.family'] = 'Meiryo'
if os.name == 'posix':
    plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# エクセルファイルの読み込み
excel_path = '20250203_20250216テクシード石井工場_計測データ（項目変更）.xlsx'
excel_path = unicodedata.normalize("NFD", excel_path)
xls = pd.ExcelFile(excel_path)
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0, skiprows=[1])

# 'datetime' 列の作成
df_trend['datetime'] = pd.to_datetime(df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str))
df_trend.set_index('datetime', inplace=True)
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)

#全体
K = len(df_trend)
#一日分
#K = 1443

J_P = 1  # 太陽光発電の変換効率区分
J_DA = 1  # 消費電力Aの変換効率区分
J_DB = 1  # 消費電力Bの変換効率区分
J_DC = 1  # 消費電力Cの変換効率区分
J_FC = 1  # バッテリー充電の変換効率区分
J_FD = 1  # バッテリー放電の変換効率区分  # 変換効率の区分数を統一

# 定数の設定
M = 1e6  # 大きな定数
alpha_P = {j: 0.98 for j in range(J_P)}
beta_P = {j: 0.00 for j in range(J_P)}
alpha_DA = {j: 0.98 for j in range(J_DA)}
beta_DA = {j: 0.00 for j in range(J_DA)}
alpha_DB = {j: 0.98 for j in range(J_DB)}
beta_DB = {j: 0.00 for j in range(J_DB)}
alpha_DC = {j: 0.98 for j in range(J_DC)}
beta_DC = {j: 0.00 for j in range(J_DC)}
alpha_FC = {j: 0.98 for j in range(J_FC)}
beta_FC = {j: 0.00 for j in range(J_FC)}
alpha_FD = {j: 0.98 for j in range(J_FD)}
beta_FD = {j: 0.00 for j in range(J_FD)}
bF_max = 2742  # バッテリー容量の上限
aFC = 450/60  # 最大充電量
aFD = 450/60  # 最大放電量
bF0 = df_trend['蓄電池'].iloc[:K].ffill().iloc[0]*0.01*bF_max  # バッテリーの初期SOC
scales = [0.5, 1.0, 1.5,]

# 定数の設定
gP1_original = df_trend['太陽光発電電力'].iloc[:K].ffill()
gP1_original = gP1_original.values/60
gP1_original[gP1_original < 0] = 0  # 負の値を0に変換

dA2 = df_trend['6600/210-105V 75kVA 全体'].iloc[:K].ffill()
dA2 = dA2.values/60
dA2 = dA2.tolist()

dB2 = df_trend['6600/210V 300kVA 全体'].iloc[:K].ffill()
dB2 = dB2.values/60
dB2 = dB2.tolist()

dC2 = df_trend['6600/210V 500kVA 全体'].iloc[:K].ffill()
dC2 = dC2.values/60
dC2 = dC2.tolist()

s_actual = df_trend['系統購入電力'].iloc[:K].ffill()
s_actual = s_actual.values/60

xFD1_xFC2_actual = df_trend['蓄電池MegaPower放電電力'].iloc[:K].ffill()
xFD1_xFC2_actual = xFD1_xFC2_actual.values/60

bF_actual = df_trend['蓄電池'].iloc[:K].ffill()
bF_actual = bF_actual.values*0.01*bF_max

solar_radiation = df_trend['日射量'].iloc[:K].ffill()

# 最適化ロジック
def optimize_power(gP1_scaled):
    model = Model('PowerOptimization')

    s = {k: model.addVar(vtype='C', name=f's_{k}', lb=0) for k in range(K)}
    v = {k: model.addVar(vtype='C', name=f'v_{k}', lb=0) for k in range(K)}
    gP2 = {k: model.addVar(vtype='C', name=f'gP2_{k}', lb=0) for k in range(K)}
    dA1 = {k: model.addVar(vtype='C', name=f'dA1_{k}', lb=0) for k in range(K)}
    dB1 = {k: model.addVar(vtype='C', name=f'dB1_{k}', lb=0) for k in range(K)}
    dC1 = {k: model.addVar(vtype='C', name=f'dC1_{k}', lb=0) for k in range(K)}
    xFC1 = {k: model.addVar(vtype='C', name=f'xFC1_{k}', lb=0) for k in range(K)}
    xFC2 = {k: model.addVar(vtype='C', name=f'xFC2_{k}', lb=0) for k in range(K)}
    xFD1 = {k: model.addVar(vtype='C', name=f'xFD1_{k}', lb=0) for k in range(K)}
    xFD2 = {k: model.addVar(vtype='C', name=f'xFD2_{k}', lb=0) for k in range(K)}
    bF = {k: model.addVar(vtype='C', name=f'bF_{k}', lb=0) for k in range(K)}

    if J_P > 1:
       yP = {(j, k): model.addVar(vtype='B', name=f'yP_{j}_{k}') for j in range(J_P) for k in range(K)}
    if J_DA > 1:
       yDA = {(j, k): model.addVar(vtype='B', name=f'yDA_{j}_{k}') for j in range(J_DA) for k in range(K)}
    if J_DB > 1:
       yDB = {(j, k): model.addVar(vtype='B', name=f'yDB_{j}_{k}') for j in range(J_DB) for k in range(K)}
    if J_DC > 1:
       yDC = {(j, k): model.addVar(vtype='B', name=f'yDC_{j}_{k}') for j in range(J_DC) for k in range(K)}
    if J_FC > 1:
       yFC = {(j, k): model.addVar(vtype='B', name=f'yFC_{j}_{k}') for j in range(J_FC) for k in range(K)}
    if J_FD > 1:
       yFD = {(j, k): model.addVar(vtype='B', name=f'yFD_{j}_{k}') for j in range(J_FD) for k in range(K)}

    # 目的関数の設定 
    model.setObjective(sum(s[k] + 0.001 * v[k] + 0.01 * xFC1[k] for k in range(K)) - bF[K-1], 'minimize')

    for k in range(K):
        # 電力バランス制約
        model.addCons(-v[k] + gP2[k] + s[k] - xFC1[k] + xFD2[k] - dA1[k] - dB1[k] - dC1[k] == 0)
        if J_P > 1:
            for j in range(J_P):
                model.addCons(gP2[k] <= alpha_P[j] * gP1_scaled[k] + beta_P[j] + M * (1 - yP[j, k]))
        else:
            model.addCons(gP2[k] == alpha_P[0] * gP1_scaled[k] + beta_P[0])
        if J_DA > 1:
            for j in range(J_DA):
                model.addCons(dA2[k] <= alpha_DA[j] * dA1[k] + beta_DA[j] + M * (1 - yDA[j, k]))
        else:
            model.addCons(dA2[k] == alpha_DA[0] * dA1[k] + beta_DA[0])
        if J_DB > 1:
           for j in range(J_DB):
               model.addCons(dB2[k] <= alpha_DB[j] * dB1[k] + beta_DB[j] + M * (1 - yDB[j, k]))
        else:
            model.addCons(dB2[k] == alpha_DB[0] * dB1[k] + beta_DB[0])
        if J_DC > 1:
           for j in range(J_DC):
               model.addCons(dC2[k] <= alpha_DC[j] * dC1[k] + beta_DC[j] + M * (1 - yDC[j, k]))
        else:
            model.addCons(dC2[k] == alpha_DC[0] * dC1[k] + beta_DC[0])
        # バッテリーSOC更新式
        model.addCons(bF[k] == (bF[k-1] + xFC2[k] - xFD1[k]) if k > 0 else bF[k] ==  (bF0 + xFC2[k] - xFD1[k]))

        # バッテリー最大容量制約
        model.addCons(bF[k] <= bF_max)

        # 充放電効率制約
        if J_FC > 1:
            for j in range(J_FC):
                model.addCons(xFC2[k] <= alpha_FC[j] * xFC1[k] + beta_FC[j] + M * (1 - yFC[j, k]))
        else:
            model.addCons(xFC2[k] == alpha_FC[0] * xFC1[k] + beta_FC[0])
        if J_FD > 1:
            for j in range(J_FC):
                model.addCons(xFD2[k] <= alpha_FD[j] * xFD1[k] + beta_FD[j] + M * (1 - yFD[j, k]))
        else:
            model.addCons(xFD2[k] == alpha_FD[0] * xFD1[k] + beta_FD[0])
    
        # バイナリ選択制約
        if J_P > 1:
            model.addCons(sum(yP[j, k] for j in range(J_P)) == 1)
        if J_DA > 1:
            model.addCons(sum(yDA[j, k] for j in range(J_DA)) == 1)
        if J_DB > 1:    
            model.addCons(sum(yDB[j, k] for j in range(J_DB)) == 1)
        if J_DC > 1:
            model.addCons(sum(yDC[j, k] for j in range(J_DC)) == 1)
        if J_FC > 1:
            model.addCons(sum(yFC[j, k] for j in range(J_FC)) == 1)
        if J_FD > 1:
            model.addCons(sum(yFD[j, k] for j in range(J_FD)) == 1)
        model.addCons(bF[k] <= bF_max)
        model.addCons(xFC2[k] <= aFC)
        model.addCons(xFD1[k] <= aFD)

    # 最適化の実行
    model.optimize()

    # 結果の取得
    results = []
    for k in range(K):
        results.append([
        k, 
        gP1_scaled[k]*60, 
        model.getVal(gP2[k])*60,
        model.getVal(dA1[k])*60,
        dA2[k]*60, 
        model.getVal(dB1[k])*60, 
        dB2[k]*60,
        model.getVal(dC1[k])*60, 
        dC2[k]*60, 
        model.getVal(s[k])*60, 
        model.getVal(v[k])*60, 
        model.getVal(xFC1[k])*60,
        model.getVal(xFC2[k])*60,
        model.getVal(xFD1[k])*60,
        model.getVal(xFD2[k])*60, 
        model.getVal(bF[k]),
        bF_actual[k],
        s_actual[k]*60,
        model.getVal(xFD1[k])*60 - model.getVal(xFC2[k])*60,
        xFD1_xFC2_actual[k]*60,
        solar_radiation[k]
        ])

    # 🔥 この部分を追加（行を列に変換する処理）
    transposed_results = list(map(list, zip(*results)))

    # スケールごとのCSV出力
    scale_value = gP1_scaled[0] / gP1_original[0] if gP1_original[0] > 0 else 1.0
    csv_results = []
    for k in range(K):
        csv_results.append([
            k,
            gP1_scaled[k],  # 単位を合わせるために60を掛ける
            results[k][0],  # gP2
            results[k][1],  # dA1
            dA2[k],         # dA2
            results[k][3],  # dB1
            dB2[k],         # dB2
            results[k][5],  # dC1
            dC2[k],         # dC2
            results[k][7],  # s
            results[k][8],  # v
            results[k][9],  # xFC1
            results[k][10], # xFC2
            results[k][11], # xFD1
            results[k][12], # xFD2
            results[k][13],    # bF (kWh単位なので60を掛けない)
            bF_actual[k],      # 実際のバッテリーSOC
            s_actual[k],    # 実際の系統買電
            results[k][11] - results[k][10],  # xFD1-xFC2
            xFD1_xFC2_actual[k],  # 実際のバッテリー放電量/充電量
            solar_radiation[k]        # 日射量
        ])
        
    columns = ['k', 'gP1', 'gP2', 'dA1', 'dA2', 'dB1', 'dB2', 'dC1', 'dC2', 's', 'v', 'xFC1', 'xFC2', 'xFD1', 'xFD2', 'bF', 'bF_actual', 's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual', 'solar_radiation']
    df_csv = pd.DataFrame(csv_results, columns=columns)
    df_csv.index = pd.Index(df_trend.index[:K], name='Datetime')
    #CSVファイルを保存
    df_csv.to_csv(f'optimization_results_scale_{scale_value}.csv', index=True)

    # 🔥 これを返す
    return transposed_results

# PDF作成準備
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.set_font('Arial', size=12)
pdf.add_page()
pdf.cell(200, 10, 'Optimization Results - Multi-Scale Comparison', ln=True, align='C')

# グラフ用の列名と設定
columns = ['k', 'gP1', 'gP2', 'dA1', 'dA2', 'dB1', 'dB2', 'dC1', 'dC2', 's', 'v', 'xFC1', 'xFC2', 'xFD1', 'xFD2', 'bF', 'bF_actual', 's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual','solar_radiation']
units = ['[kW]', '[kW]', '[kW]',  '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kWh]', '[kWh]', '[kW]', '[kW]', '[kW]', '[kW]','[W/m2]']
names = ['時刻インデックス','太陽光発電電力量(変換前)', '太陽光発電電力量(変換後)', '消費電力A(変換前)', '消費電力A(変換後)', '消費電力B(変換前)', '消費電力B(変換後)', '消費電力C(変換前)', '消費電力C(変換後)', '系統買電', 'ムダ電力量', 'バッテリー充電量(変換前)', 'バッテリー充電量(変換後)', 'バッテリー放電量(変換前)', 'バッテリー放電量(変換後)','バッテリーSOC', '実際のバッテリーSOC', '実際の系統買電', 'バッテリー放電量/充電量', '実際のバッテリー放電量/充電量','日射量']
ymin = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -250, -250, -250, 0]
ymax = [250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 500, 500, 500, 500, bF_max, bF_max, 250, 250 ,250, 1400]
# print(f"names の長さ: {len(names)}")
# print(f"columns の長さ: {len(columns)}")

# 出力ディレクトリの作成
os.makedirs('multi_scale_png', exist_ok=True)

# スケールごとの色指定
scale_colors = {
    0.5: 'blue',
    1.0: 'green',
    1.5: 'orange',
}

# スケールごとに結果を保存する辞書
scale_results = {}

# スケールごとの最適化（全体先にやっておく）
for scale in reversed(scales):
    gP1_scaled = gP1_original * scale
    gP1_scaled[gP1_scaled < 0] = 0
    gP1_scaled = gP1_scaled[:K]
    opt_results = optimize_power(gP1_scaled)
    scale_results[scale] = opt_results

# プロット用ループ（columnsの長さだけ繰り返す）
for i, var in enumerate(columns):
    fig, ax = plt.subplots(figsize=(9, 6))
    for scale in scales:
        ax.plot(df_trend.index[:K], scale_results[scale][i], label=f'Scale {scale}', color=scale_colors[scale])
    
    ax.set_title(f'{names[i]} - Scale Comparison')
    ax.set_xlabel('Datetime')
    ax.set_ylabel(f'{names[i]} {units[i]}')
    ax.set_ylim(ymin[i], ymax[i])
    ax.set_xlim(pd.Timestamp('2025-02-03 00:00:00'), pd.Timestamp('2025-02-16 23:59:00'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    fig.autofmt_xdate()
    ax.legend()

    # 保存
    img_path = f'multi_scale_png/{var}_comparison.png'
    plt.savefig(img_path, dpi=300)
    plt.close()

# === PDFに画像を追加（1ページに最大8個、4x2配置） ===
images_per_page = 8
img_w, img_h = 90, 60  # 画像の幅と高さ（mm）
x_positions = [10, 100]  # 左・右
y_positions = [20, 90, 160, 230]  # 上からの位置（mm）

# 保存された画像ファイル一覧（順番に注意）
figures = [f"multi_scale_png/{var}_comparison.png" for var in columns]

# ページ追加・配置
for i, img_path in enumerate(figures):
    if i % images_per_page == 0:
        if i != 0:
            pdf.add_page()
    x_idx = (i % images_per_page) % 2  # 0か1 → 左/右
    y_idx = (i % images_per_page) // 2  # 0〜3 → 縦の位置
    try:
        pdf.image(img_path, x=x_positions[x_idx], y=y_positions[y_idx], w=img_w, h=img_h)
    except Exception as e:
        print(f"画像追加エラー: {img_path}, 理由: {e}")

# # 実際のデータと比較するための追加グラフ
# additional_data = [
#     ('bF_actual', 'バッテリーSOC(実測値)', '[kWh]', 0, bF_max, 'red'),
#     ('s_actual', '系統買電(実測値)', '[kW]', -250, 250, 'red'),
#     ('xFD1_xFC2_actual', 'バッテリー放電量/充電量(実測値)', '[kW]', -250, 250, 'red'),
#     ('solar_radiation', '日射量', '[W/m²]', 0, 1400, 'orange')
#     ] 

# for var_name, title, unit, y_min, y_max, color in additional_data:
#     fig, ax = plt.subplots(figsize=(9, 6))
    
#     if var_name == 'bF_actual':
#         ax.plot(df_trend.index[:K], bF_actual, label=title, color=color)
#     elif var_name == 's_actual':
#          ax.plot(df_trend.index[:K], s_actual * 60, label=title, color=color)
#     elif var_name == 'xFD1_xFC2_actual':
#          ax.plot(df_trend.index[:K], xFD1_xFC2_actual * 60, label=title, color=color)
#     elif var_name == 'solar_radiation':
#          ax.plot(df_trend.index[:K], solar_radiation, label=title, color=color)
   
#     ax.set_xlabel('Datetime')
#     ax.set_ylabel(f'{title} {unit}')
#     ax.set_ylim(y_min, y_max)
#     ax.legend()
#     ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
#     fig.autofmt_xdate()
#     ax.set_xlim(pd.Timestamp('2025-02-10 00:00:00'), pd.Timestamp('2025-02-11 00:00:00'))
#     plt.title(title)
    
#     img_path = f'multi_scale_png/{var_name}.png'
#     plt.savefig(img_path)
#     plt.close()
    
#     pdf.add_page()  #
#     pdf.image(img_path, x=10, y=20, w=180, h=120)


# PDFを保存
pdf_output_path = 'Optimization_Results_Complete.pdf'
pdf.output(pdf_output_path)
print(f'PDF saved at: {pdf_output_path}')