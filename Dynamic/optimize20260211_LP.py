from pyscipopt import Model
import pandas as pd
import matplotlib.pyplot as plt
from fpdf import FPDF
import os
import numpy as np
import matplotlib.dates as mdates
import unicodedata
import time

# import seaborn as sns

# sns.set_theme()

start_time = time.perf_counter()

# 処理系がWindowsの場合はMeiryoを指定
if os.name == 'nt':
    plt.rcParams['font.family'] = 'Meiryo'
# 処理系がMacの場合はHiragino Maru Gothic Proを指定
if os.name == 'posix':
    plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# エクセルファイルの読み込み
# excel_path = '20241216-20テクシード石井工場_計測データ（項目変更）.xlsx'
excel_path = '20250703_20250721テクシード工場トレンドデータ.xlsx'
excel_path = unicodedata.normalize("NFC", excel_path)
xls = pd.ExcelFile(excel_path)
# df_accumulated = pd.read_excel(xls, sheet_name='積算値')
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0, skiprows=[1])

# df_trend['datetime'] = df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str)
# print(df_trend['datetime'])
# 1列目、2列目を文字列連結後、datetime形式に変換して 'datetime' 列に設定
#df_trend['datetime'] = pd.to_datetime(df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str))
df_trend['datetime'] = pd.to_datetime(
    df_trend['日'].astype(str) + ' ' + df_trend['時間(分刻み)'].astype(str),
    format='%Y-%m-%d %H:%M:%S',
    errors='coerce'
)
# 'datetime' 列をインデックスに設定
df_trend.set_index('datetime', inplace=True)
# 不要な列を削除（０列と１列）
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)

# print(len(df_trend))
# print(df_trend.head())

# 計画期間の設定 (10秒単位で7200期間)
# K = min(len(df_trend) - 4, 7200)  # データ数に基づく期間設定
K = len(df_trend) #行の数
J_P = 1  # 太陽光発電の変換効率区分
J_DA = 1  # 消費電力Aの変換効率区分
J_DB = 1  # 消費電力Bの変換効率区分
J_DC = 1  # 消費電力Cの変換効率区分
J_DD = 1  # 消費電力Dの変換効率区分 #0702加筆
J_FC = 1  # バッテリー充電の変換効率区分
J_FD = 1  # バッテリー放電の変換効率区分  # 変換効率の区分数を統一

# 定数の設定
M = 1e6  # 大きな定数
alpha_P = {j: 0.94 for j in range(J_P)}
beta_P = {j: -0.24 for j in range(J_P)}
# alpha_P = {j: 0.95 for j in range(J_P)}
#alpha_P = {0: 0.5, 1: 0.9}
#beta_P = {0: 0, 1: -40}
# alpha_DA = {j: 0.95 for j in range(J_DA)}
alpha_DA = {j: 0.94 for j in range(J_DA)}
beta_DA = {j: 0.00 for j in range(J_DA)}
# alpha_DB = {j: 0.95 for j in range(J_DB)}
alpha_DB = {j: 0.94 for j in range(J_DB)}
beta_DB = {j: 0.00 for j in range(J_DB)}
# alpha_DC = {j: 0.95 for j in range(J_DC)}
alpha_DC = {j: 0.94 for j in range(J_DC)}
beta_DC = {j: 0.00 for j in range(J_DC)}
# alpha_DC = {j: 0.95 for j in range(J_DC)}
alpha_DD = {j: 0.94 for j in range(J_DD)} #0702加筆
beta_DD = {j: 0.00 for j in range(J_DD)} 
# alpha_FC = {j: 0.95 for j in range(J_FC)}
alpha_FC = {j: 0.94 for j in range(J_FC)}
beta_FC = {j: 0.00 for j in range(J_FC)}
# alpha_FD = {j: 0.95 for j in range(J_FD)}
alpha_FD = {0: 0.5, 1: 0.9}
beta_FD = {0: 0, 1: -40}
bF_max = 2742  # バッテリー容量の上限
aFC = 450 / 60  # 最大充電量
aFD = 450 / 60  # 最大放電量

sBYMAX= 50.0 / 60.0 # 最大買電量

# bF0 = 0  # バッテリーの初期SOC
bF0 = df_trend['蓄電池'].iloc[:K].ffill().iloc[0] * 0.01 * bF_max  # バッテリーの初期SOC *0.01...％を小数にしている

# 定数の設定
gP1 = df_trend['太陽光発電電力'].iloc[:K].ffill()
gP1 = (gP1.values / 60)
gP1[gP1 < 0] = 0  # 負の値を0に変換

dA2 = df_trend['6600/210-105V 75kVA 全体'].iloc[:K].ffill()
dA2 = dA2.values / 60
dA2 = dA2.tolist()

dB2 = df_trend['6600/210V 300kVA 全体'].iloc[:K].ffill()
dB2 = dB2.values / 60
dB2 = dB2.tolist()

dC2 = df_trend['6600/210V 500kVA 全体'].iloc[:K].ffill()
dC2 = dC2.values / 60
dC2 = dC2.tolist()

s_actual = df_trend['系統購入電力'].iloc[:K].ffill()
s_actual = s_actual.values / 60

xFD1_xFC2_actual = df_trend['蓄電池MegaPower放電電力'].iloc[:K].ffill()
xFD1_xFC2_actual = xFD1_xFC2_actual.values / 60

bF_actual = df_trend['蓄電池'].iloc[:K].ffill()
bF_actual = bF_actual.values * 0.01 * bF_max

solar_radiation = df_trend['日射量'].iloc[:K].ffill()

pBY = df_trend['売買電単価'].iloc[:K].ffill() #0702変更
pBY = pBY.tolist()
pSL = pBY.copy()

#dD = df_trend['本社工場デマンド'].iloc[:K].ffill() #0702変更
#dD = dD.tolist()

#pSL = [x / 1000 for x in pSL] #1105変更　託送のインセンティブから売電のインセンティブに(買電最小を売電最大より優先)

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"データの読み込みに要した時間: {elapsed_time:.5f}秒")

start_time = time.perf_counter()


# 最適化モデルの作成
model = Model('PowerOptimization')

# 変数の定義
sBY = {k: model.addVar(vtype='C', name=f'sBY_{k}', lb=0) for k in range(K)} #0521加筆
sSL = {k: model.addVar(vtype='C', name=f'sSL_{k}', lb=0) for k in range(K)} #0521加筆
v = {k: model.addVar(vtype='C', name=f'v_{k}', lb=0) for k in range(K)} 

#gP1 = {k: model.addVar(vtype='C', name=f'gP1_{k}', lb=0) for k in range(K)}
gP2 = {k: model.addVar(vtype='C', name=f'gP2_{k}', lb=0) for k in range(K)}

dA1 = {k: model.addVar(vtype='C', name=f'dA1_{k}', lb=0) for k in range(K)}
#dA2 = {k: model.addVar(vtype='C', name=f'dA2_{k}', lb=0) for k in range(K)}

dB1 = {k: model.addVar(vtype='C', name=f'dB1_{k}', lb=0) for k in range(K)}
#dB2 = {k: model.addVar(vtype='C', name=f'dB2_{k}', lb=0) for k in range(K)}

dC1 = {k: model.addVar(vtype='C', name=f'dC1_{k}', lb=0) for k in range(K)}
#dC2 = {k: model.addVar(vtype='C', name=f'dC2_{k}', lb=0) for k in range(K)}

#dD1 = {k: model.addVar(vtype='C', name=f'dD1_{k}', lb=0) for k in range(K)} #0702加筆
#dD2 = {k: model.addVar(vtype='C', name=f'dD2_{k}', lb=0) for k in range(K)} #0702加筆

bF = {k: model.addVar(vtype='C', name=f'bF_{k}', lb=0) for k in range(K)}
xFC1 = {k: model.addVar(vtype='C', name=f'xFC1_{k}', lb=0) for k in range(K)}
xFC2 = {k: model.addVar(vtype='C', name=f'xFC2_{k}', lb=0) for k in range(K)}
xFD1 = {k: model.addVar(vtype='C', name=f'xFD1_{k}', lb=0) for k in range(K)}
xFD2 = {k: model.addVar(vtype='C', name=f'xFD2_{k}', lb=0) for k in range(K)}

if J_P > 1:
    yP = {(j, k): model.addVar(vtype='B', name=f'yP_{j}_{k}') for j in range(J_P) for k in range(K)}
if J_DA > 1:
    yDA = {(j, k): model.addVar(vtype='B', name=f'yDA_{j}_{k}') for j in range(J_DA) for k in range(K)}
if J_DB > 1:
    yDB = {(j, k): model.addVar(vtype='B', name=f'yDB_{j}_{k}') for j in range(J_DB) for k in range(K)}
if J_DC > 1:
    yDC = {(j, k): model.addVar(vtype='B', name=f'yDC_{j}_{k}') for j in range(J_DC) for k in range(K)}
if J_DD > 1:
    yDD = {(j, k): model.addVar(vtype='B', name=f'yDD_{j}_{k}') for j in range(J_DD) for k in range(K)} #0702加筆
if J_FC > 1:
    yFC = {(j, k): model.addVar(vtype='B', name=f'yFC_{j}_{k}') for j in range(J_FC) for k in range(K)}
if J_FD > 1:
    yFD = {(j, k): model.addVar(vtype='B', name=f'yFD_{j}_{k}') for j in range(J_FD) for k in range(K)}

# 目的関数の設定
#model.setObjective(sum(s[k] + v[k] for k in range(K)), 'minimize')
#model.setObjective(sum(s[k] + v[k] + 0.99 * xFC1[k] for k in range(K)), 'minimize') 0521削除
#model.setObjective(sum(s[k] + 0.001 * v[k] + 0.01 * xFC1[k] for k in range(K)) - bF[K - 1], 'minimize')
model.setObjective(sum( pBY[k] * sBY[k] - (pSL[k]-0.000000001)*sSL[k] for k in range(K)), 'minimize') #0702修正

# 制約の追加（17本すべてをPDFの順序通りに）
for k in range(K):
    # 電力バランス制約
    model.addCons(gP2[k] + sBY[k] - sSL[k]- xFC1[k] + xFD2[k] - dA1[k] - dB1[k] - dC1[k] - v[k] == 0)#0702修正 
    if J_P > 1:
        for j in range(J_P):
            model.addCons(gP2[k] <= alpha_P[j] * gP1[k] + beta_P[j] + M * (1 - yP[j, k]))
    else:
        model.addCons(gP2[k] == alpha_P[0] * gP1[k] + beta_P[0])
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
    model.addCons(bF[k] == (0.99999*bF[k - 1] + xFC2[k] - xFD1[k]) if k > 0 else bF[k] == (bF0 + xFC2[k] - xFD1[k]))
    #model.addCons(bF[k] == (bF[k - 1] + xFC2[k] - xFD1[k]) if k > 0 else bF[k] == (bF0 + xFC2[k] - xFD1[k]))

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

    #買電制約
    if k % 30 == 0:
        model.addCons(sum(sBY[k2] for k2 in range(k,k+30) ) <= sBYMAX * 30)

# 最終SOC制約
#model.addCons(bF[K - 1] >= 2742*0.69)  

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"変数と制約条件の立式に要した時間: {elapsed_time:.5f}秒")
start_time = time.perf_counter()

# 最適化の実行
model.optimize()

if model.getStatus() == "optimal":
    print(f"最適解が見つかりました。")
    print(f"最適目的関数値: {model.getObjVal():.2f}")
else:
    print(f"最適解が見つかりませんでした。ステータス: {model.getStatus()}")

end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"最適化の実行に処理時間: {elapsed_time:.5f}秒")

# 結果の取得とCSV出力
results = []
for k in range(K):
    results.append([
        k,
        gP1[k] * 60,model.getVal(gP2[k]) * 60,model.getVal(dA1[k]) * 60,dA2[k] * 60,model.getVal(dB1[k]) * 60,
        dB2[k] * 60,model.getVal(dC1[k]) * 60,dC2[k] * 60,model.getVal(sBY[k]-sSL[k]) * 60,model.getVal(xFC1[k]) * 60,
        model.getVal(xFC2[k]) * 60,model.getVal(xFD1[k]) * 60,model.getVal(xFD2[k]) * 60,model.getVal(bF[k]),bF_actual[k],
        s_actual[k] * 60,model.getVal(xFD1[k]) * 60 - model.getVal(xFC2[k]) * 60,xFD1_xFC2_actual[k] * 60,solar_radiation[k],pBY[k],
        model.getVal(v[k])*60
    ])



columns = ['k', 
           'gP1', 'gP2', 'dA1', 'dA2','dB1', 
           'dB2', 'dC1', 'dC2', 'sBY,sSL','xFC1', 
           'xFC2', 'xFD1', 'xFD2', 'bF','bF_actual',
            's_actual', 'xFD1_xFC2', 'xFD1_xFC2_actual', 'solar_radiation','pSL',
            'w']
unit = ['[kW]', '[kW]', '[kW]', '[kW]', '[kW]', 
        '[kW]', '[kW]', '[kW]', '[kW]', '[kW]', 
        '[kW]', '[kW]', '[kW]','[kWh]', '[kWh]', 
        '[kW]', '[kW]', '[kW]', '[W/m2]','[yen/kWh]',
        '[kW]']
'''
name = ['太陽光発電電力量(変換前)', '太陽光発電電力量(変換後)', '消費電力A(変換前)', '消費電力A(変換後)','消費電力B(変換前)',
         '消費電力B(変換後)', '消費電力C(変換前)', '消費電力C(変換後)', '系統買電','バッテリー充電量(変換前)', 
         'バッテリー充電量(変換後)', 'バッテリー放電量(変換前)', 'バッテリー放電量(変換後)','バッテリーSOC', '実際のバッテリーSOC', 
         '実際の系統買電', 'バッテリー放電量/充電量','実際のバッテリー放電量/充電量', '日射量','買電単価',
         '無駄電力量'
        ]
'''

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
    'Wasted Energy'
]



ymin = [0, 0, 0, 0, 0, 
        0, 0, 0, -500, 0, 
        0, 0, 0, 0, 0, 
        -500, -500, -500, 0,0,
        0
        ]
ymax = [250, 250, 250, 250, 250,
        250, 250, 250, 500, 500, 
        500, 500, 500, bF_max, bF_max, 
        250, 500, 500, 1400,50,
        250
        ]
color = ['green', 'red', 'red', 'green', 'red', 
         'green', 'red', 'green', 'red', 'red', 
         'red', 'red','red', 'red', 'green', 
         'green', 'red', 'green', 'green','green',
         'red'
         ]
df_results = pd.DataFrame(results, columns=columns)
df_results.index = df_trend.index
df_results.to_csv('optimization_results_買電売電を考慮.csv', index=False)
df_trend.to_csv('trend.csv', index=False)


# ==========================================
# 追加機能: 最初の12時間だけの売買電グラフを出力
# ==========================================
print("最初の3時間の詳細グラフを作成しています...")

# 1. 開始時刻と終了時刻（開始から12時間後）を定義
start_dt = df_results.index[0]
end_dt = start_dt + pd.Timedelta(hours=3)

# 2. データを切り出し (locを使って時間で範囲指定)
# データの期間が12時間未満の場合は全期間になります
df_subset = df_results.loc[start_dt:end_dt]

# 3. グラフ描画
fig, ax = plt.subplots(figsize=(10, 6))

# 'sBY,sSL' 列をプロット（色は赤に設定していますが、お好みで変更可能です）
#ax.plot(df_subset.index.to_pydatetime(), df_subset['sBY,sSL'].values, color='red', linewidth=2.0)
ax.plot(df_subset.index.to_pydatetime(), df_subset['pSL'].values, color='red', linewidth=2.0)

# X軸のフォーマット（12時間分なので、日付は不要で「時:分」が見やすいです）
ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
fig.autofmt_xdate() # ラベルが重ならないように斜めにする

# ラベルとタイトル
plt.ylabel('sBY,sSL [kW]')
plt.xlabel('Time')
plt.grid(True)

# 範囲調整（見やすくするため）
plt.tight_layout()

# 4. PNGとして保存
output_png_12h = 'png/grid_power_first_3h.png'
plt.savefig(output_png_12h, dpi=300)
plt.close(fig)

print(f"グラフを保存しました: {output_png_12h}")

# ==========================================
# 追加機能: 最初の3時間だけの売電単価グラフを出力 (修正版)
# ==========================================
print("最初の3時間の売電単価グラフを作成しています...")

# 1. データの切り出し
df_subset_price = df_results.loc[start_dt:end_dt]

# 2. グラフ描画
fig2, ax2 = plt.subplots(figsize=(10, 6))

# --- 【修正ポイント】 drawstyle='steps-post' を追加 ---
# これにより、斜め線ではなく「階段状（直角）」に線が引かれます
ax2.plot(df_subset_price.index.to_pydatetime(), 
         df_subset_price['pSL'].values, 
         color='green', 
         linewidth=2.0, 
         drawstyle='steps-post') 

# X軸のフォーマット
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
fig2.autofmt_xdate()

# ラベルとタイトル
plt.ylabel('Selling Price [yen/kWh]')
plt.xlabel('Time')
plt.title(f'Selling Price (First 3h from {start_dt.strftime("%Y-%m-%d")})')
plt.grid(True)

# 3. PNGとして保存
output_png_price_12h = 'png/selling_price_first_3h_step.png' # ファイル名も変更しておくと分かりやすいです
plt.tight_layout()
plt.savefig(output_png_price_12h) # dpiはデフォルトでも十分ですが、指定してもOK
plt.close(fig2)

print(f"単価グラフを保存しました: {output_png_price_12h}")


# PDFの作成
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_font('Arial', style='', size=12)
pdf.cell(200, 10,  ln=True, align='C')


# 各変数の時系列グラフを作成
variables = df_results.columns[1:]  # 'k' を除く全変数
figures = []

os.makedirs('png', exist_ok=True)

# --- 修正箇所：グラフ作成のループ内 ---
for i, var in enumerate(variables):
    fig, ax = plt.subplots(figsize=(9, 6))
    
    # データをプロット（一度だけに整理）
    # index.to_pydatetime() を使うと Matplotlib との親和性が最も高まります
    ax.plot(df_results.index.to_pydatetime(), df_results[var].values, color=color[i], linewidth=1.5)

    # X軸のフォーマット設定
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d\n%H:%M'))
    
    plt.ylabel(f'{var}: {unit[i]}')
    plt.grid(True)
    
    # Y軸の範囲設定
    y_min, y_max = ymin[i], ymax[i]
    margin = (y_max - y_min) * 0.05 if y_max != y_min else 1.0
    ax.set_ylim(y_min - margin, y_max + margin)

    # 図の下部に説明テキスト
    fig.text(0.5, 0.02, 'time', ha='center', va='bottom', fontsize=12)

    # レイアウトの調整（これがないとラベルが切れることがあります）
    plt.tight_layout(rect=[0, 0.05, 1, 1]) 

    img_path = f'png/{var}.png'
    plt.savefig(img_path, dpi=300)
    plt.close(fig) # 明示的に fig を閉じる

    figures.append(img_path)

# 画像をPDFに追加（1ページに8個のグラフを4x2で配置）
images_per_page = 8
img_w, img_h = 90, 60  # 画像の幅と高さ
x_positions = [10, 100]  # 左と右の位置
y_positions = [20, 90, 160, 230]  # 上からの位置

# --- 修正箇所：PDF追加部分 ---
for i, img in enumerate(figures):
    if i % images_per_page == 0 and i != 0:
        pdf.add_page()
    x_idx = (i % images_per_page) % 2
    y_idx = (i % images_per_page) // 2
    pdf.image(img, x=x_positions[x_idx], y=y_positions[y_idx], w=img_w, h=img_h)
    # 2つ目の pdf.image は削除
    
# PDFを保存
pdf_output_path = 'Optimization_Results_買電売電を考慮_LP.pdf'
pdf.output(pdf_output_path)

# PDFのパスを表示
print('PDF saved at:', pdf_output_path)

