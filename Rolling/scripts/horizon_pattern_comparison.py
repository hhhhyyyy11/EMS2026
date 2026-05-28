#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
異なる予測期間での運用パターンを比較するスクリプト
需要、PV発電、買電、SOC、JEPX価格を表示
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import os

# 日本語フォントの設定
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'Hiragino Sans', 'Yu Gothic', 'Meirio', 'TakaoPGothic', 'IPAexGothic']
plt.rcParams['axes.unicode_minus'] = False

def generate_horizon_comparison_graph(start_date='2024-07-03', num_days=3, output_dir='png'):
    """
    複数日の運用パターンを異なる予測期間で比較したグラフを生成
    需要、PV発電、買電、SOC、JEPX価格を表示
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    os.makedirs(os.path.join(project_root, output_dir), exist_ok=True)

    # JEPX価格データを読み込み
    price_file = os.path.join(project_root, 'data/spot_summary_2024.csv')
    df_price = None
    try:
        df_price = pd.read_csv(price_file, encoding='cp932')
        # タイムスタンプ作成: 受渡日 + 時刻コード（30分単位）
        df_price['timestamp'] = pd.to_datetime(df_price['受渡日']) + pd.to_timedelta((df_price['時刻コード'] - 1) * 30, unit='m')
        df_price = df_price.set_index('timestamp')
        # 北海道エリア価格を使用
        df_price['price'] = df_price['エリアプライス北海道(円/kWh)']
        print(f'✓ JEPX価格データ読み込み: {price_file}')
    except Exception as e:
        print(f'✗ JEPX価格データ読み込みエラー: {e}')

    # 比較対象の設定（市場連動プラン）
    configs = [
        ('results/soc860/rolling_results_market_linked.csv', 'h96 (48時間予測)', 'blue'),
        ('results/h384_c8/soc860/rolling_results_market_linked.csv', 'h384 (8日間予測)', 'green'),
        ('results/h1008_c24/soc860/rolling_results_market_linked.csv', 'h1008 (21日間予測)', 'red'),
    ]

    # 期間設定
    start = pd.to_datetime(start_date)
    end = start + timedelta(days=num_days)

    print(f'\n=== 予測期間比較グラフ生成 ===')
    print(f'対象期間: {start_date}〜{end.strftime("%Y-%m-%d")} ({num_days}日間)')

    # データ読み込み
    dfs = []
    for csv_path, label, color in configs:
        full_path = os.path.join(project_root, csv_path)
        if os.path.exists(full_path):
            df = pd.read_csv(full_path, parse_dates=['timestamp'])
            df = df.set_index('timestamp')
            df_period = df.loc[start:end].copy()
            if len(df_period) > 0:
                dfs.append((df_period, label, color))
                print(f'  ✓ {label}: {len(df_period)} データポイント読み込み')
            else:
                print(f'  ✗ {label}: データなし')
        else:
            print(f'  ✗ {csv_path}: ファイルなし')

    if len(dfs) < 2:
        print('エラー: 比較するデータが不足しています')
        return

    # サブプロット作成
    fig, axes = plt.subplots(len(dfs), 1, figsize=(16, 5 * len(dfs)), sharex=True)
    if len(dfs) == 1:
        axes = [axes]

    # 共通のy軸範囲を設定
    y_max = max(max(df['demand_kW'].max(), df['pv_used_kW'].max(), df['sBY'].max()) for df, _, _ in dfs)
    bF_max = 860.0

    for idx, (df_period, label, color) in enumerate(dfs):
        ax_left = axes[idx]

        # 左軸: 需要、PV発電、買電
        ax_left.plot(df_period.index, df_period['demand_kW'],
                     color='red', linewidth=1.5, label='需要')
        ax_left.plot(df_period.index, df_period['pv_used_kW'],
                     color='orange', linewidth=1.5, label='PV発電')
        ax_left.fill_between(df_period.index, df_period['sBY'],
                             alpha=0.3, color=color)
        ax_left.plot(df_period.index, df_period['sBY'],
                     color=color, linewidth=1.5, label='買電')

        # 買電最大値を水平線で表示
        max_sby = df_period['sBY'].max()
        ax_left.axhline(y=max_sby, color=color, linestyle='--', alpha=0.7, linewidth=1)
        ax_left.text(df_period.index[0], max_sby + 5, f'最大買電: {max_sby:.1f}kW',
                    fontsize=9, color=color, fontweight='bold')

        ax_left.set_ylabel('電力 [kW]', fontsize=12)
        ax_left.set_ylim(0, y_max * 1.2)
        ax_left.grid(True, alpha=0.3)

        # 右軸: SOC
        ax_right = ax_left.twinx()
        ax_right.plot(df_period.index, df_period['bF'],
                      color='purple', linewidth=2, linestyle='--', label='SOC')
        ax_right.axhline(y=bF_max * 0.5, color='gray', linestyle=':', alpha=0.5)
        ax_right.set_ylabel('SOC [kWh]', fontsize=12, color='purple')
        ax_right.tick_params(axis='y', labelcolor='purple')
        ax_right.set_ylim(0, bF_max * 1.05)

        # JEPX価格（第3軸として薄く表示）
        if df_price is not None:
            try:
                df_price_period = df_price.loc[start:end]
                if len(df_price_period) > 0:
                    # 左軸に薄いグレーで価格を重ねる（スケール調整）
                    price_scaled = df_price_period['price'] * (y_max / df_price_period['price'].max()) * 0.8
                    ax_left.fill_between(df_price_period.index, price_scaled,
                                        alpha=0.35, color='gray', label='JEPX価格')
            except:
                pass

        # 日付区切り線を追加
        for day in pd.date_range(start, end, freq='D'):
            ax_left.axvline(x=day, color='gray', linestyle=':', alpha=0.5)
            weekday_jp = ['月', '火', '水', '木', '金', '土', '日'][day.weekday()]
            ax_left.text(day + timedelta(hours=12), y_max * 1.1,
                        f'{day.strftime("%m/%d")}({weekday_jp})',
                        ha='center', fontsize=10)

        # 時刻軸のフォーマット
        ax_left.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax_left.xaxis.set_major_locator(mdates.HourLocator(interval=6))

        # タイトル
        ax_left.set_title(f'{label}: 運用パターン', fontsize=12, pad=10)

        # 凡例
        lines1, labels1 = ax_left.get_legend_handles_labels()
        lines2, labels2 = ax_right.get_legend_handles_labels()
        ax_left.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9, ncol=5)

    axes[-1].set_xlabel('時刻', fontsize=12)
    plt.setp(axes[-1].xaxis.get_majorticklabels(), rotation=45, ha='right')

    plt.tight_layout()

    # 保存
    output_file = os.path.join(project_root, output_dir, 'horizon_comparison_full.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f'\n✓ グラフを保存: {output_file}')

    # 統計情報の表示
    print(f'\n=== {start_date}〜{end.strftime("%Y-%m-%d")} の統計比較 ===')
    print(f'{"設定":<20} {"買電最大[kW]":>12} {"買電平均[kW]":>12} {"SOC最大[kWh]":>12} {"SOC最小[kWh]":>12}')
    print('-' * 72)
    for df_period, label, _ in dfs:
        print(f'{label:<20} {df_period["sBY"].max():>12.1f} {df_period["sBY"].mean():>12.1f} '
              f'{df_period["bF"].max():>12.1f} {df_period["bF"].min():>12.1f}')

    plt.close()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, default='2024-07-03', help='開始日付 (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=3, help='表示日数')
    args = parser.parse_args()

    generate_horizon_comparison_graph(start_date=args.date, num_days=args.days)
    print('\n完了しました!')
