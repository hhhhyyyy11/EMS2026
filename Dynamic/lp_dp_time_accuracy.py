import matplotlib.pyplot as plt
import numpy as np
import japanize_matplotlib

# データ
steps = [0.1, 0.2, 0.4]  # X軸: 刻み幅
diff_ratios = [0.046, 0.080, 0.145]  # 左Y軸: 相対的な差
times = [125.0, 34.7, 10.8]  # 右Y軸: CPU時間

fig, ax1 = plt.subplots(figsize=(10, 6))

# --- 左側の軸 (相対的な差) の設定 ---
color_1 = 'tab:blue'
ax1.set_xlabel('蓄電池の残量の刻み幅 (kWh)', fontsize=14)
ax1.set_ylabel('LPとの相対的な差', color=color_1, fontsize=14)
# 折れ線グラフで描画
ax1.plot(steps, diff_ratios, color=color_1, marker='o', markersize=8, linewidth=2, label='相対差')
ax1.tick_params(axis='y', labelcolor=color_1, labelsize=12)
ax1.set_xticks(steps) # X軸のメモリをデータ点に合わせる
ax1.set_xticklabels([f'{x} kWh' for x in steps], fontsize=12)

# グリッド線（見やすくするため）
ax1.grid(True, linestyle='--', alpha=0.6)

# --- 右側の軸 (CPU時間) の設定 ---
ax2 = ax1.twinx()  # 2つ目の軸を共有
color_2 = 'tab:red'
ax2.set_ylabel('CPU時間 (秒)', color=color_2, fontsize=14)
# 折れ線グラフで描画（棒グラフにしてもOKですが、傾向を見るなら折れ線がわかりやすいです）
ax2.plot(steps, times, color=color_2, marker='s', markersize=8, linewidth=2, linestyle='--', label='CPU時間')
ax2.tick_params(axis='y', labelcolor=color_2, labelsize=12)

# 数値のラベルを追加（オプション）
for i, txt in enumerate(diff_ratios):
    ax1.annotate(f'{txt:.3f}', (steps[i], diff_ratios[i]), xytext=(-10, 10), textcoords='offset points', color=color_1, fontsize=11, weight='bold')

for i, txt in enumerate(times):
    ax2.annotate(f'{txt}s', (steps[i], times[i]), xytext=(10, 10), textcoords='offset points', color=color_2, fontsize=11, weight='bold')

plt.tight_layout()
plt.savefig('tradeoff_graph.png')
plt.show()