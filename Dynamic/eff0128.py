import pandas as pd
import matplotlib.pyplot as plt
import numpy as np  # 回帰直線の計算に使用

# ---------------------------------------------------------
# 設定
# ---------------------------------------------------------
file_name = '20250203_20250216テクシード石井工場_計測データ（項目変更）.xlsx'
sheet_name = 'トレンド値'

# ---------------------------------------------------------
# 1. データの読み込み
# ---------------------------------------------------------
# ※ご自身の環境でうまくいった header の値を指定してください（0 または 2）
df = pd.read_excel(file_name, sheet_name=sheet_name, header=0)

# ---------------------------------------------------------
# 2. データのフィルタリング
# ---------------------------------------------------------
filtered_df = df[(df['GP1'] != 0) & (df['GP2'] != 0)]

x = filtered_df['GP1']
y = filtered_df['GP2']

if len(x) == 0:
    print("条件を満たすデータがありませんでした。")
else:
   # ---------------------------------------------------------
    # 3. 原点を通る回帰直線の計算 (y = Ax)
    # ---------------------------------------------------------
    # 傾き A = Σ(xy) / Σ(x^2) で求められます
    A = np.dot(x, y) / np.dot(x, x)
    
    # 数式のテキスト作成
    formula_text = f'y = {A:.4f}x'
    print(f"回帰直線: {formula_text}")

    # ---------------------------------------------------------
    # 4. 散布図と回帰直線の描画
    # ---------------------------------------------------------
    plt.figure(figsize=(8, 6))
    
    # ドットの描画
    # s=10 でサイズを小さくしています（適宜調整してください）
    plt.scatter(x, y, color='blue', alpha=0.5, s=10)

    # 回帰直線の描画
    # xの最小値から最大値までの範囲で直線を引く
    x_range = np.linspace(x.min(), x.max(), 100)
    y_range = A * x_range
    plt.plot(x_range, y_range, color='red', linewidth=1)

    # 数式の表示 (左上あたり)
    # x座標は x.min(), y座標は y.max() を基準に少し調整しています
    # transform=plt.gca().transAxes を使うと「図の左端から5%、上端から10%」のように指定できて便利です
    plt.text(0.05, 0.95, formula_text, transform=plt.gca().transAxes,
             fontsize=12, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # ラベルとタイトルの設定
    plt.xlabel('gP1 [kW]')
    plt.ylabel('gP2 [kW]')
    #plt.title('Scatter Plot: GP1 vs GP2')
    plt.grid(True)
    
    # 凡例 (plt.legend()) は削除しました

    plt.show()