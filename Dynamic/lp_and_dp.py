import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from fpdf import FPDF
import os
import numpy as np
import unicodedata

# 日本語フォント設定
if os.name == 'nt':
    plt.rcParams['font.family'] = 'Meiryo'
elif os.name == 'posix':
    plt.rcParams['font.family'] = 'Hiragino Maru Gothic Pro'

# 1. データの準備
df = pd.read_csv('lp_and_dp.csv')

# 日付インデックスの作成
start_time = pd.Timestamp('2025-07-03 00:00')
end_time = pd.Timestamp('2025-07-10 00:00')
time_index = pd.date_range(start=start_time, end=end_time, periods=len(df))
df['datetime'] = time_index
df.set_index('datetime', inplace=True)

# 2. グラフの作成
fig, ax = plt.subplots(figsize=(10, 6))

# --- 修正箇所: .to_pydatetime() を追加してNumPy配列化します ---
x_data = df.index.to_pydatetime()

# LP（赤）とDP（青）のプロット
ax.plot(x_data, df['LP'].values, color='red', label='LP', linewidth=1.5)
ax.plot(x_data, df['DP'].values, color='blue', label='DP', linewidth=1.5)
# -------------------------------------------------------

# X軸の設定：横書きにする
# 日付のフォーマット (例: 07-03)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
# 目盛りの間隔を1日ごとに設定（重なり防止）
ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))

# ラベルを水平（rotation=0）に設定
plt.xticks(rotation=0, ha='center') 

# Y軸の設定
plt.ylabel('bF:[kWh]')
import matplotlib.ticker as ticker
ax.yaxis.set_major_locator(ticker.MultipleLocator(500))

# グリッドと凡例
plt.grid(True)
plt.legend()

# 下部のラベル
fig.text(0.5, 0.02, 'time', ha='center', va='bottom', fontsize=12)
plt.tight_layout(rect=[0, 0.05, 1, 1])

# 画像保存
os.makedirs('png_comparison', exist_ok=True)
img_path = 'png_comparison/bF_comparison_horizontal.png'
plt.savefig(img_path, dpi=300)
plt.close(fig)

# 3. PDFの作成
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_font('Arial', style='', size=12)

# 画像をPDFに配置
# 指定の位置 (左上) に配置
pdf.image(img_path, x=10, y=20, w=90, h=60)

# PDF保存
pdf_output_path = 'LP_DP_Comparison_Horizontal.pdf'
pdf.output(pdf_output_path)

print(f"PDF saved to {pdf_output_path}")