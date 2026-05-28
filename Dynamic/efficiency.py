import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
import matplotlib.dates as mdates
import datetime
import seaborn as sns

sns.set_theme()
plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'


# エクセルファイルの読み込み
excel_path = "20241216-20テクシード石井工場_計測データ（項目変更）.xlsx"
xls = pd.ExcelFile(excel_path)
# df_accumulated = pd.read_excel(xls, sheet_name="積算値")
df_trend = pd.read_excel(xls, sheet_name='トレンド値', header=0,skiprows=[1])

# df_trend['datetime'] = df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str)
# print(df_trend['datetime'])
# 2列目、3列目を文字列連結後、datetime形式に変換して 'datetime' 列に設定
df_trend['datetime'] = pd.to_datetime(df_trend.iloc[:, 0].astype(str) + ' ' + df_trend.iloc[:, 1].astype(str))
# 'datetime' 列をインデックスに設定
df_trend.set_index('datetime', inplace=True)
# 不要な列を削除（０列と１列）
df_trend.drop(df_trend.columns[:2], axis=1, inplace=True)

# print(df_trend['No1太陽光PCS交流電力'].head())

df_trend['No1太陽光PCS効率'] = df_trend['No1太陽光PCS交流電力'] / df_trend['No1太陽光PCS直流電力']
df_trend['No2太陽光PCS効率'] = df_trend['No2太陽光PCS交流電力'] / df_trend['No2太陽光PCS直流電力']


# 対象とする列のNaN/Inf補完
cols_to_fix = ['No1太陽光PCS直流電力', 'No1太陽光PCS交流電力', 'No1太陽光PCS効率']
for col in cols_to_fix:
    df_trend[col] = df_trend[col].replace([np.inf, -np.inf], np.nan)
    # 前方向、なければ後方向で補完
    df_trend[col] = df_trend[col].ffill().bfill()
cols_to_fix = ['No2太陽光PCS直流電力', 'No2太陽光PCS交流電力', 'No2太陽光PCS効率']
for col in cols_to_fix:
    df_trend[col] = df_trend[col].replace([np.inf, -np.inf], np.nan)
    # 前方向、なければ後方向で補完
    df_trend[col] = df_trend[col].ffill().bfill()

# 入出力散布図の作成
plt.figure(figsize=(8, 6))
sc = plt.scatter(df_trend['No1太陽光PCS直流電力'],
                 df_trend['No1太陽光PCS交流電力'],
                 c=df_trend['No1太陽光PCS効率'], 
                 cmap='turbo_r', 
                 vmin=0.7,
                 vmax=1.0,
                 s=1)
plt.xlabel('No1太陽光PCS直流電力 [kW]')
plt.ylabel('No1太陽光PCS交流電力 [kW]')
plt.title('直流電力と交流電力の散布図')
plt.colorbar(label='No1太陽光PCS効率')
# 最小二乗法による線形回帰直線の計算
x_data = df_trend['No1太陽光PCS直流電力']
y_data = df_trend['No1太陽光PCS交流電力']
slope, intercept = np.polyfit(x_data, y_data, 1)
x_fit = np.linspace(x_data.min(), x_data.max(), 100)
y_fit = slope * x_fit + intercept
# 回帰直線を描画
plt.plot(x_fit, y_fit, color='black', linewidth=1, alpha=0.5, label='y = {:.2f}x + {:.2f}'.format(slope, intercept))
plt.legend()
plt.savefig('PCS_IO1.png', format='png', dpi=300)
plt.close()

# 入出力散布図の作成
plt.figure(figsize=(8, 6))
sc = plt.scatter(df_trend['No2太陽光PCS直流電力'],
                    df_trend['No2太陽光PCS交流電力'],
                    c=df_trend['No2太陽光PCS効率'], 
                    cmap='turbo_r', 
                    vmin=0.7,
                    vmax=1.0,
                    s=1)
plt.xlabel('No2太陽光PCS直流電力 [kW]')
plt.ylabel('No2太陽光PCS交流電力 [kW]')
plt.title('直流電力と交流電力の散布図')
plt.colorbar(label='No2太陽光PCS効率')
# 最小二乗法による線形回帰直線の計算
x_data = df_trend['No2太陽光PCS直流電力']
y_data = df_trend['No2太陽光PCS交流電力']
slope, intercept = np.polyfit(x_data, y_data, 1)
x_fit = np.linspace(x_data.min(), x_data.max(), 100)
y_fit = slope * x_fit + intercept
# 回帰直線を描画
plt.plot(x_fit, y_fit, color='black', linewidth=1, alpha=0.5, label='y = {:.2f}x + {:.2f}'.format(slope, intercept))
plt.legend()
plt.savefig('PCS_IO2.png', format='png', dpi=300)
plt.close()

# datetime型をmatplotlibが扱えるfloatに変換（全データのx軸用）
x = mdates.date2num(df_trend.index.to_pydatetime())
y = df_trend['No1太陽光PCS直流電力'].values
z = df_trend['No1太陽光PCS効率'].values
x2 = [datetime.datetime.combine(datetime.date(1900, 1, 1), dt.time()) for dt in df_trend.index.to_pydatetime()]



# x軸の表示範囲（2024/12/16 0:00～2024/12/17 0:00）
start_date = datetime.datetime(2024, 12, 16)
end_date = start_date + datetime.timedelta(days=1)
xlim = (mdates.date2num(start_date), mdates.date2num(end_date))

fig, ax = plt.subplots(figsize=(8, 6))
sc = ax.scatter(x, y, c=z, cmap='viridis', s=10)
ax.set_xlim(xlim)
ax.set_ylim(y.min(), y.max())
ax.set_xlabel('Datetime')
ax.set_ylabel('No1太陽光PCS直流電力 [kW]')
ax.set_title('直流電力の推移 (点の色: No1太陽光PCS効率)')

# x軸をdatetime表示に変換
ax.xaxis_date()
fig.autofmt_xdate()

plt.colorbar(sc, label='No1太陽光PCS効率')
plt.savefig('point_plot_20241216.png', format='png')
plt.close()


fig, ax = plt.subplots(figsize=(8, 6))
sc = ax.scatter(x, z, c=y, cmap='viridis', s=10)
ax.set_xlim(xlim)
ax.set_ylim(z.min(), z.max())
ax.set_xlabel('Datetime')
ax.set_ylabel('No1太陽光PCS効率')
ax.set_title('No1太陽光PCS効率推移')

# x軸をdatetime表示に変換
ax.xaxis_date()
fig.autofmt_xdate()

plt.colorbar(sc, label='No1太陽光PCS直流電力')
plt.savefig('efficiency_20241216.png', format='png')
plt.close()


# fig, ax = plt.subplots(figsize=(8, 6))
# sc = ax.scatter(y, z, s=10)
# ax.set_ylim(z.min(), z.max())
# ax.set_xlabel('No1太陽光PCS直流電力 [kW]')
# ax.set_ylabel('No1太陽光PCS効率')
# ax.set_title('No1太陽光PCS効率')
# 
# plt.colorbar(sc, label='No1太陽光PCS直流電力')
# plt.savefig('efficiency2.png', format='png')
# plt.close()

# y: No1太陽光PCS直流電力, z: No1太陽光PCS効率
# 点の順序に沿って線分を作成
points = np.array([y, z]).T.reshape(-1, 1, 2)
segments = np.concatenate([points[:-1], points[1:]], axis=1)

# 各線分の色は両端の平均効率に応じて決定
lc = LineCollection(segments, cmap='turbo_r', norm=plt.Normalize(0.7, 1.0))
lc.set_array((z[:-1] + z[1:]) / 2)
lc.set_linewidth(0.5)

fig, ax = plt.subplots(figsize=(8, 6))
ax.add_collection(lc)
ax.set_xlim(y.min(), y.max())
ax.set_ylim(z.min(), z.max())
ax.set_xlabel('No1太陽光PCS直流電力 [kW]')
ax.set_ylabel('No1太陽光PCS効率')
# ax.set_title('No1太陽光PCS効率 (折れ線グラフ)')
ax.scatter(x, z, s=10)

# plt.colorbar(lc, label='No1太陽光PCS効率')
plt.savefig('efficiency-line.png', format='png', dpi=300)
plt.close()


fig, ax = plt.subplots(figsize=(8, 6))
ax.set_xlabel('No1太陽光PCS直流電力 [kW]')
ax.set_ylabel('No1太陽光PCS効率')
ax.scatter(y, z, c=z, cmap='turbo_r', vmin=0.7, vmax=1.0, s=10)
plt.savefig('efficiency-scatter.png', format='png', dpi=300)
plt.close()

