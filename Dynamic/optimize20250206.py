from pyscipopt import Model
import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
import os
import numpy as np
import matplotlib.dates as mdates

plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'
# import seaborn as sns

# sns.set_theme()

# エクセルファイルの読み込み
excel_path = '20241216-20テクシード石井工場_計測データ（項目変更）.xlsx'
xls = pd.ExcelFile(excel_path)
# df_accumulated = pd.read_excel(xls, sheet_name='積算値')
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0,skiprows=[1])

# df_trend['datetime'] = df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str)
# print(df_trend['datetime'])
# 2列目、3列目を文字列連結後、datetime形式に変換して 'datetime' 列に設定
df_trend['datetime'] = pd.to_datetime(df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str))
# 'datetime' 列をインデックスに設定
df_trend.set_index('datetime', inplace=True)
# 不要な列を削除（０列と１列）
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)


print(len(df_trend))
print(df_trend.head())

# 計画期間の設定 (10秒単位で7200期間)
# K = min(len(df_trend) - 4, 7200)  # データ数に基づく期間設定
K = len(df_trend)
J_P = 1  # 太陽光発電の変換効率区分
J_DA = 1  # 消費電力Aの変換効率区分
J_DB = 1  # 消費電力Bの変換効率区分
J_DC = 1  # 消費電力Cの変換効率区分
J_FC = 1  # バッテリー充電の変換効率区分
J_FD = 1  # バッテリー放電の変換効率区分  # 変換効率の区分数を統一

# 定数の設定
M = 1e6  # 大きな定数
# alpha_P = {j: 0.94 for j in range(J_P)}
# beta_P = {j: -0.24 for j in range(J_P)}
alpha_P = {j: 0.95 for j in range(J_P)}
beta_P = {j: 0.00 for j in range(J_P)}
alpha_DA = {j: 0.95 for j in range(J_DA)}
beta_DA = {j: 0.00 for j in range(J_DA)}
alpha_DB = {j: 0.95 for j in range(J_DB)}
beta_DB = {j: 0.00 for j in range(J_DB)}
alpha_DC = {j: 0.95 for j in range(J_DC)}
beta_DC = {j: 0.00 for j in range(J_DC)}
alpha_FC = {j: 0.95 for j in range(J_FC)}
beta_FC = {j: 0.00 for j in range(J_FC)}
alpha_FD = {j: 0.95 for j in range(J_FD)}
beta_FD = {j: 0.00 for j in range(J_FD)}
bF_max = 2742  # バッテリー容量の上限
aFC = 450/60  # 最大充電量
aFD = 450/60  # 最大放電量
bF0 = 0  # バッテリーの初期SOC


# 定数の設定
gP1 = df_trend['太陽光発電電力'].iloc[:K].ffill()
gP1 = gP1.values/60
gP1[gP1 < 0] = 0  # 負の値を0に変換

dA2 = df_trend['6600/210-105V 75kVA 全体'].iloc[:K].ffill()
dA2 = dA2.values/60

dB2 = df_trend['6600/210V 300kVA 全体'].iloc[:K].ffill()
dB2 = dB2.values/60

dC2 = df_trend['6600/210V 500kVA 全体'].iloc[:K].ffill()
dC2 = dC2.values/60

s_actual = df_trend['系統購入電力'].iloc[:K].ffill()
s_actual = s_actual.values/60

xFD1_xFC2_actual = df_trend['蓄電池MegaPower放電電力'].iloc[:K].ffill()
xFD1_xFC2_actual = xFD1_xFC2_actual.values/60




# 最適化モデルの作成
model = Model('PowerOptimization')

# 変数の定義
s = {k: model.addVar(vtype='C', name=f's_{k}', lb=0) for k in range(K)}
v = {k: model.addVar(vtype='C', name=f'v_{k}', lb=0) for k in range(K)}

# gP1 = {k: model.addVar(vtype='C', name=f'gP1_{k}', lb=0) for k in range(K)}
gP2 = {k: model.addVar(vtype='C', name=f'gP2_{k}', lb=0) for k in range(K)}

dA1 = {k: model.addVar(vtype='C', name=f'dA1_{k}', lb=0) for k in range(K)}
# dA2 = {k: model.addVar(vtype='C', name=f'dA2_{k}', lb=0) for k in range(K)}

dB1 = {k: model.addVar(vtype='C', name=f'dB1_{k}', lb=0) for k in range(K)}
# dB2 = {k: model.addVar(vtype='C', name=f'dB2_{k}', lb=0) for k in range(K)}

dC1 = {k: model.addVar(vtype='C', name=f'dC1_{k}', lb=0) for k in range(K)}
# dC2 = {k: model.addVar(vtype='C', name=f'dC2_{k}', lb=0) for k in range(K)}

bF = {k: model.addVar(vtype='C', name=f'bF_{k}', lb=0) for k in range(K)}
xFC1 = {k: model.addVar(vtype='C', name=f'xFC1_{k}', lb=0) for k in range(K)}
xFC2 = {k: model.addVar(vtype='C', name=f'xFC2_{k}', lb=0) for k in range(K)}
xFD1 = {k: model.addVar(vtype='C', name=f'xFD1_{k}', lb=0) for k in range(K)}
xFD2 = {k: model.addVar(vtype='C', name=f'xFD2_{k}', lb=0) for k in range(K)}

yP = {(j, k): model.addVar(vtype='B', name=f'yP_{j}_{k}') for j in range(J_P) for k in range(K)}
yDA = {(j, k): model.addVar(vtype='B', name=f'yDA_{j}_{k}') for j in range(J_DA) for k in range(K)}
yDB = {(j, k): model.addVar(vtype='B', name=f'yDB_{j}_{k}') for j in range(J_DB) for k in range(K)}
yDC = {(j, k): model.addVar(vtype='B', name=f'yDC_{j}_{k}') for j in range(J_DC) for k in range(K)}
yFC = {(j, k): model.addVar(vtype='B', name=f'yFC_{j}_{k}') for j in range(J_FC) for k in range(K)}
yFD = {(j, k): model.addVar(vtype='B', name=f'yFD_{j}_{k}') for j in range(J_FD) for k in range(K)}

# 目的関数の設定
model.setObjective(sum(s[k] + v[k] for k in range(K)), 'minimize')

# 制約の追加（17本すべてをPDFの順序通りに）
for k in range(K):
    # 電力バランス制約
    model.addCons(-v[k] + gP2[k] + s[k] - xFC1[k] + xFD2[k] - dA1[k] - dB1[k] - dC1[k] == 0)
    for j in range(J_P):
        model.addCons(gP2[k] <= alpha_P[j] * gP1[k] + beta_P[j] + M * (1 - yP[j, k]))
        # model.addCons(gP2[k] <= alpha_P[j] * gP1[k])
    for j in range(J_DA):
        model.addCons(dA2[k] <= alpha_DA[j] * dA1[k] + beta_DA[j] + M * (1 - yDA[j, k]))
        # model.addCons(dA2[k] <= alpha_DA[j] * dA1[k])
    for j in range(J_DB):
        model.addCons(dB2[k] <= alpha_DB[j] * dB1[k] + beta_DB[j] + M * (1 - yDB[j, k]))
        # model.addCons(dB2[k] <= alpha_DB[j] * dB1[k])
    for j in range(J_DC):
        model.addCons(dC2[k] <= alpha_DC[j] * dC1[k] + beta_DC[j] + M * (1 - yDC[j, k]))
        # model.addCons(dC2[k] <= alpha_DC[j] * dC1[k])
        # バッテリーSOC更新式
    model.addCons(bF[k] == (bF[k-1] + xFC2[k] - xFD1[k]) if k > 0 else bF[k] ==  (bF0 + xFC2[k] - xFD1[k]))

    # バッテリー最大容量制約
    model.addCons(bF[k] <= bF_max)

    # 充放電効率制約
    for j in range(J_FC):
        model.addCons(xFC2[k] <= alpha_FC[j] * xFC1[k] + beta_FC[j] + M * (1 - yFC[j, k]))
        model.addCons(xFD2[k] <= alpha_FD[j] * xFD1[k] + beta_FD[j] + M * (1 - yFD[j, k]))

    # バイナリ選択制約
    model.addCons(sum(yP[j, k] for j in range(J_P)) == 1)
    model.addCons(sum(yDA[j, k] for j in range(J_DA)) == 1)
    model.addCons(sum(yDB[j, k] for j in range(J_DB)) == 1)
    model.addCons(sum(yDC[j, k] for j in range(J_DC)) == 1)
    model.addCons(sum(yFC[j, k] for j in range(J_FC)) == 1)
    model.addCons(sum(yFD[j, k] for j in range(J_FD)) == 1)
    model.addCons(bF[k] <= bF_max)
    model.addCons(xFC2[k] <= aFC)
    model.addCons(xFD1[k] <= aFD)

# 最適化の実行
model.optimize()

# 結果の取得とCSV出力
results = []
for k in range(K):
    results.append([
        k, 
        gP1[k]*60, 
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
        s_actual[k]*60,
        model.getVal(xFD1[k])*60 - model.getVal(xFC2[k])*60,
        xFD1_xFC2_actual[k]*60
    ])

columns = ['k', 'gP1', 'gP2', 'dA1', 'dA2', 'dB1', 'dB2', 'dC1', 'dC2', 's', 'v', 'xFC1', 'xFC2', 'xFD1', 'xFD2', 'bF', 's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual']
unit = ['[kW]', '[kW]', '[kW]',  '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', '[kWh]', '[kW]', '[kW]', '[kW]']
name = ['太陽光発電電力量(変換前)', '太陽光発電電力量(変換後)', '消費電力A(変換前)', '消費電力A(変換後)', '消費電力B(変換前)', '消費電力B(変換後)', '消費電力C(変換前)', '消費電力C(変換後)', '系統買電', 'ムダ電力量', 'バッテリー充電量(変換前)', 'バッテリー充電量(変換後)', 'バッテリー放電量(変換前)', 'バッテリー放電量(変換後)','バッテリーSOC', '実際の系統買電', 'バッテリー放電量/充電量', '実際のバッテリー放電量/充電量']
ymin = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -250, -250]
ymax = [250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 50, 250, 250 ,250]
color = ['green', 'blue', 'blue', 'green', 'blue', 'green', 'blue', 'green', 'blue', 'blue', 'red', 'blue', 'blue' , 'red', 'blue', 'green', 'blue', 'green']
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
    # fig, ax = plt.subplots(figsize=(8, 6))

    # plt.figure(figsize=(9, 6))
    # plt.plot(df_results['k'], df_results[var], label=var, linewidth=1.5)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(df_results.index, df_results[var]) # , marker='o', linestyle='-')

#
    # ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))  # 1時間ごとの目盛りを表示
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M'))
    # ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))   # 目盛りの書式を「時:分」に設定

    plt.xlabel('') # 'Datetime'
    plt.ylabel(f'{var}: {unit[i]}')
    # plt.title(f'{var}: {name[i]}')
    # plt.gcf().autofmt_xdate()  # 日付ラベルが重ならないように自動調整
    plt.legend()
    plt.grid()
    y_min = ymin[i]
    y_max = ymax[i]
    margin = (y_max - y_min) * 0.05
    ax.set_ylim(y_min - margin, y_max + margin)
    ax.plot(df_results.index, df_results[var], color=color[i]) # , marker='o', linestyle='-')
    
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
    x_idx = (i % images_per_page) % 2  # 左(0)か右(1)
    y_idx = (i % images_per_page) // 2  # 縦の位置
    pdf.image(img, x=x_positions[x_idx], y=y_positions[y_idx], w=img_w, h=img_h)
    

# PDFを保存
pdf_output_path = 'Optimization_Results.pdf'
pdf.output(pdf_output_path)

# PDFのパスを表示
print('PDF saved at:', pdf_output_path)
