import matplotlib.pyplot as plt
import numpy as np
import japanize_matplotlib  # これをインポートするだけで日本語が使えるようになります

# データ
periods = ['5,050\n(0.5 週間分)', '10,080\n(1 週間分)', '15,120\n(1.5 週間分)', '20,160\n(2 週間分)']
lp_values = [8.0, 25.3, 44.4, 70.6]
dp_values = [18.4, 34.7, 49.3, 67.6]

x = np.arange(len(periods))
width = 0.35

fig, ax = plt.subplots(figsize=(8, 6))

# 棒グラフの描画
rects1 = ax.bar(x - width/2, lp_values, width, label='線形計画モデル', color='red')
rects2 = ax.bar(x + width/2, dp_values, width, label='動的計画モデル(刻み幅0.2 kWh)', color='blue')

# ラベルとタイトル
ax.set_ylabel('CPU時間 (s)')
ax.set_xlabel('期の数')
ax.set_xticks(x)
ax.set_xticklabels(periods)
ax.legend(fontsize=12)

# 数値をバーの上に表示する関数
def autolabel(rects):
    for rect in rects:
        height = rect.get_height()
        ax.annotate('{}'.format(height),
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom')

autolabel(rects1)
autolabel(rects2)

plt.tight_layout()
plt.savefig('lp_dp_time_bar_fixed.png')
plt.show()