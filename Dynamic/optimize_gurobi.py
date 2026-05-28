from gurobipy import Model, GRB, quicksum
import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
import os
import numpy as np
import matplotlib.dates as mdates

plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# エクセルファイルの読み込み
excel_path = 'test.xlsx'
xls = pd.ExcelFile(excel_path)
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0, skiprows=[1])

# 1列目、2列目を文字列連結後、datetime形式に変換して 'datetime' 列に設定
df_trend['datetime'] = pd.to_datetime(df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str))
# 'datetime' 列をインデックスに設定
df_trend.set_index('datetime', inplace=True)
# 不要な列を削除（０列と１列）
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)

# 計画期間の設定
K = len(df_trend)
J_P = 1
J_DA = 1
J_DB = 1
J_DC = 1
J_FC = 1
J_FD = 1

# 定数の設定
M = 1e6
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
bF_max = 2742
aFC = 450 / 60
aFD = 450 / 60
bF0 = df_trend['蓄電池'].iloc[:K].ffill().iloc[0] * 0.01 * bF_max

# 定数の設定
gP1 = df_trend['太陽光発電電力'].iloc[:K].ffill().values / 60
gP1[gP1 < 0] = 0

dA2 = df_trend['6600/210-105V 75kVA 全体'].iloc[:K].ffill().values / 60
dB2 = df_trend['6600/210V 300kVA 全体'].iloc[:K].ffill().values / 60
dC2 = df_trend['6600/210V 500kVA 全体'].iloc[:K].ffill().values / 60
s_actual = df_trend['系統購入電力'].iloc[:K].ffill().values / 60
xFD1_xFC2_actual = df_trend['蓄電池MegaPower放電電力'].iloc[:K].ffill().values / 60
bF_actual = df_trend['蓄電池'].iloc[:K].ffill().values * 0.01 * bF_max
solar_radiation = df_trend['日射量'].iloc[:K].ffill().values

# 最適化モデルの作成
model = Model('PowerOptimization')

# 変数の定義
s = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f's_{k}', lb=0) for k in range(K)}
v = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'v_{k}', lb=0) for k in range(K)}
gP2 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'gP2_{k}', lb=0) for k in range(K)}
dA1 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'dA1_{k}', lb=0) for k in range(K)}
dB1 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'dB1_{k}', lb=0) for k in range(K)}
dC1 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'dC1_{k}', lb=0) for k in range(K)}
bF = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'bF_{k}', lb=0) for k in range(K)}
xFC1 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'xFC1_{k}', lb=0) for k in range(K)}
xFC2 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'xFC2_{k}', lb=0) for k in range(K)}
xFD1 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'xFD1_{k}', lb=0) for k in range(K)}
xFD2 = {k: model.addVar(vtype=GRB.CONTINUOUS, name=f'xFD2_{k}', lb=0) for k in range(K)}

if J_P > 1:
    yP = {(j, k): model.addVar(vtype=GRB.BINARY, name=f'yP_{j}_{k}') for j in range(J_P) for k in range(K)}
if J_DA > 1:
    yDA = {(j, k): model.addVar(vtype=GRB.BINARY, name=f'yDA_{j}_{k}') for j in range(J_DA) for k in range(K)}
if J_DB > 1:
    yDB = {(j, k): model.addVar(vtype=GRB.BINARY, name=f'yDB_{j}_{k}') for j in range(J_DB) for k in range(K)}
if J_DC > 1:
    yDC = {(j, k): model.addVar(vtype=GRB.BINARY, name=f'yDC_{j}_{k}') for j in range(J_DC) for k in range(K)}
if J_FC > 1:
    yFC = {(j, k): model.addVar(vtype=GRB.BINARY, name=f'yFC_{j}_{k}') for j in range(J_FC) for k in range(K)}
if J_FD > 1:
    yFD = {(j, k): model.addVar(vtype=GRB.BINARY, name=f'yFD_{j}_{k}') for j in range(J_FD) for k in range(K)}

# 目的関数の設定
model.setObjective(quicksum(s[k] + 0.001 * v[k] + 0.01 * xFC1[k] for k in range(K)) - bF[K-1], GRB.MINIMIZE)

# 制約の追加
for k in range(K):
    model.addConstr(-v[k] + gP2[k] + s[k] - xFC1[k] + xFD2[k] - dA1[k] - dB1[k] - dC1[k] == 0)
    if J_P > 1:
        for j in range(J_P):
            model.addConstr(gP2[k] <= alpha_P[j] * gP1[k] + beta_P[j] + M * (1 - yP[j, k]))
    else:
        model.addConstr(gP2[k] == alpha_P[0] * gP1[k] + beta_P[0])
    if J_DA > 1:
        for j in range(J_DA):
            model.addConstr(dA2[k] <= alpha_DA[j] * dA1[k] + beta_DA[j] + M * (1 - yDA[j, k]))
    else:
        model.addConstr(dA2[k] == alpha_DA[0] * dA1[k] + beta_DA[0])
    if J_DB > 1:
        for j in range(J_DB):
            model.addConstr(dB2[k] <= alpha_DB[j] * dB1[k] + beta_DB[j] + M * (1 - yDB[j, k]))
    else:
        model.addConstr(dB2[k] == alpha_DB[0] * dB1[k] + beta_DB[0])
    if J_DC > 1:
        for j in range(J_DC):
            model.addConstr(dC2[k] <= alpha_DC[j] * dC1[k] + beta_DC[j] + M * (1 - yDC[j, k]))
    else:
        model.addConstr(dC2[k] == alpha_DC[0] * dC1[k] + beta_DC[0])
    model.addConstr(bF[k] == (bF[k-1] + xFC2[k] - xFD1[k]) if k > 0 else bF[k] == (bF0 + xFC2[k] - xFD1[k]))
    model.addConstr(bF[k] <= bF_max)
    if J_FC > 1:
        for j in range(J_FC):
            model.addConstr(xFC2[k] <= alpha_FC[j] * xFC1[k] + beta_FC[j] + M * (1 - yFC[j, k]))
    else:
        model.addConstr(xFC2[k] == alpha_FC[0] * xFC1[k] + beta_FC[0])
    if J_FD > 1:
        for j in range(J_FD):
            model.addConstr(xFD2[k] <= alpha_FD[j] * xFD1[k] + beta_FD[j] + M * (1 - yFD[j, k]))
    else:
        model.addConstr(xFD2[k] == alpha_FD[0] * xFD1[k] + beta_FD[0])
    if J_P > 1:
        model.addConstr(quicksum(yP[j, k] for j in range(J_P)) == 1)
    if J_DA > 1:
        model.addConstr(quicksum(yDA[j, k] for j in range(J_DA)) == 1)
    if J_DB > 1:
        model.addConstr(quicksum(yDB[j, k] for j in range(J_DB)) == 1)
    if J_DC > 1:
        model.addConstr(quicksum(yDC[j, k] for j in range(J_DC)) == 1)
    if J_FC > 1:
        model.addConstr(quicksum(yFC[j, k] for j in range(J_FC)) == 1)
    if J_FD > 1:
        model.addConstr(quicksum(yFD[j, k] for j in range(J_FD)) == 1)
    model.addConstr(bF[k] <= bF_max)
    model.addConstr(xFC2[k] <= aFC)
    model.addConstr(xFD1[k] <= aFD)

# 最適化の実行
model.optimize()

# 結果の取得とCSV出力
results = []
for k in range(K):
    results.append([
        k,
        gP1[k] * 60,
        gP2[k].X * 60,
        dA1[k].X * 60,
        dA2[k] * 60,
        dB1[k].X * 60,
        dB2[k] * 60,
        dC1[k].X * 60,
        dC2[k] * 60,
        s[k].X * 60,
        v[k].X * 60,
        xFC1[k].X * 60,
        xFC2[k].X * 60,
        xFD1[k].X * 60,
        xFD2[k].X * 60,
        bF[k].X,
        bF_actual[k],
        s_actual[k] * 60,
        xFD1[k].X * 60 - xFC2[k].X * 60,
        xFD1_xFC2_actual[k] * 60,
        solar_radiation[k]
    ])

columns = ['k', 'gP1', 'gP2', 'dA1', 'dA2', 'dB1', 'dB2', 'dC1', 'dC2', 's', 'v', 'xFC1', 'xFC2', 'xFD1', 'xFD2', 'bF', 'bF_actual', 's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual', 'solar_radiation']
unit = ['[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kWh]', '[kWh]', '[kW]', '[kW]', '[kW]', '[kW]', '[W/m2]']
name = ['太陽光発電電力量(変換前)', '太陽光発電電力量(変換後)', '消費電力A(変換前)', '消費電力A(変換後)', '消費電力B(変換前)', '消費電力B(変換後)', '消費電力C(変換前)', '消費電力C(変換後)', '系統買電', 'ムダ電力量', 'バッテリー充電量(変換前)', 'バッテリー充電量(変換後)', 'バッテリー放電量(変換前)', 'バッテリー放電量(変換後)', 'バッテリーSOC', '実際のバッテリーSOC', '実際の系統買電', 'バッテリー放電量/充電量', '実際のバッテリー放電量/充電量', '日射量']
ymin = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -250, -250, -250, 0]
ymax = [250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 500, 500, 500, 500, bF_max, bF_max, 250, 250, 250, 1400]
color = ['green', 'blue', 'blue', 'green', 'blue', 'green', 'blue', 'green', 'blue', 'blue', 'red', 'blue', 'blue', 'red', 'blue', 'green', 'green', 'blue', 'green', 'green']
df_results = pd.DataFrame(results, columns=columns)
df_results.index = df_trend.index
df_results.to_csv('optimization_results.csv', index=False)
df_trend.to_csv('trend.csv', index=False)

# PDFの作成
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_font('Arial', style='', size=12)
pdf.cell(200, 10, 'Optimization Results - Time Series Graphs', ln=True, align='C')

# 各変数の時系列グラフを作成
variables = df_results.columns[1:]  # 'k' を除く全変数
figures = []

os.makedirs('png', exist_ok=True)

for i, var in enumerate(variables):
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(df_results.index, df_results[var])

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M'))

    plt.xlabel('')
    plt.ylabel(f'{var}: {unit[i]}')
    plt.legend()
    plt.grid()
    y_min = ymin[i]
    y_max = ymax[i]

    # 2025/2/10の範囲のみを表示
    ax.set_xlim(pd.Timestamp('2025-02-10 00:00:00'), pd.Timestamp('2025-02-11 00:00:00'))

    margin = (y_max - y_min) * 0.05
    ax.set_ylim(y_min - margin, y_max + margin)
    ax.plot(df_results.index, df_results[var], color=color[i])

    # 図の下部にタイトル（説明テキスト）を追加
    fig.text(0.5, 0.00, f'{var}: {name[i]}', ha='center', va='bottom', fontsize=16)

    img_path = f'png/{var}.png'
    plt.savefig(img_path, dpi=300)
    plt.close()

    figures.append(img_path)

# 画像をPDFに追加（1ページに8個のグラフを4x2で配置）
images_per_page = 8
img_w, img_h = 90, 60  # 画像の幅と高さ
x_positions = [10, 100]  # 左と右の位置
y_positions = [20, 90, 160, 230]  # 上からの位置

for i, img in enumerate(figures):
    if i % images_per_page == 0 and i != 0:
        pdf.add_page()
    x_idx = (i % images_per_page) % 2  # 左(0)か右(1)
    y_idx = (i % images_per_page) // 2  # 縦の位置
    pdf.image(img, x=x_positions[x_idx], y=y_positions[y_idx], w=img_w, h=img_h)

# PDFを保存
pdf_output_path = 'Optimization_Results.pdf'
pdf.output(pdf_output_path)

