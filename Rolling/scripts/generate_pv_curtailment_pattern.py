#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PV余剰（カーテイルメント）が発生している日のパターンを生成するスクリプト
PV発電が豊富で蓄電池が満充電となり、余剰が発生する様子を可視化
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import os

# 日本語フォントの設定
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def find_max_pv_surplus_day(results_file):
    """
    PV余剰が最大の日を見つける

    Parameters:
    -----------
    results_file : str
        結果CSVファイルのパス

    Returns:
    --------
    str : 最大余剰日の日付 (YYYY-MM-DD形式)
    """
    print('\n=== PV余剰が最大の日を検索中... ===')
    df = pd.read_csv(results_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date

    # 日ごとのPV余剰合計を計算
    daily_surplus = df.groupby('date').agg({
        'pv_surplus_kW': 'sum',
        'pv_kW': 'sum'
    }).reset_index()

    daily_surplus['pv_surplus_kWh'] = daily_surplus['pv_surplus_kW'] * 0.5
    daily_surplus['pv_total_kWh'] = daily_surplus['pv_kW'] * 0.5
    daily_surplus['curtail_ratio'] = (daily_surplus['pv_surplus_kWh'] / daily_surplus['pv_total_kWh']) * 100

    # 余剰が最大の日を見つける
    max_day = daily_surplus.loc[daily_surplus['pv_surplus_kWh'].idxmax()]

    print(f'最大余剰日: {max_day["date"]}')
    print(f'  PV余剰: {max_day["pv_surplus_kWh"]:.2f} kWh')
    print(f'  余剰率: {max_day["curtail_ratio"]:.2f}%')

    return str(max_day['date'])

def generate_pv_curtailment_pattern(target_date=None, results_dir='results', png_dir='png'):
    """
    PV余剰が発生している日のパターンを生成
    results_dir, png_dir: サブフォルダ対応（例: results/soc860, png/soc860）

    Parameters:
    -----------
    target_date : str or None
        対象日付 (YYYY-MM-DD形式)。Noneの場合は自動的に最大余剰日を選択
    results_dir : str
        入力CSVのディレクトリ
    png_dir : str
        出力PNGのディレクトリ
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    results_file = os.path.join(project_root, results_dir, 'rolling_results.csv')
    os.makedirs(os.path.join(project_root, png_dir), exist_ok=True)

    # target_dateがNoneの場合、最大余剰日を自動検索
    if target_date is None:
        target_date = find_max_pv_surplus_day(results_file)

    print(f'\n=== PV余剰パターングラフ生成 ({target_date}) ===')
    print(f'データ読み込み: {results_file}')

    df = pd.read_csv(results_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 対象日のデータを抽出
    target_day = pd.to_datetime(target_date)
    df_day = df[df['timestamp'].dt.date == target_day.date()].copy()

    if len(df_day) == 0:
        print(f'エラー: {target_date}のデータが見つかりません')
        return

    print(f'データ件数: {len(df_day)}件')

    # 統計情報の計算
    pv_total = df_day['pv_kW'].sum() * 0.5  # kWh
    pv_used = df_day['pv_used_kW'].sum() * 0.5  # kWh
    pv_surplus = df_day['pv_surplus_kW'].sum() * 0.5  # kWh
    curtail_ratio = (pv_surplus / pv_total) * 100

    print(f'\n=== {target_date} のPV統計 ===')
    print(f'PV発電量: {pv_total:.2f} kWh')
    print(f'PV使用量: {pv_used:.2f} kWh')
    print(f'PV余剰量: {pv_surplus:.2f} kWh')
    print(f'余剰率: {curtail_ratio:.2f}%')

    # グラフ作成（1つのグラフに電力フローとSOCを両軸で表示）
    fig, ax1 = plt.subplots(figsize=(14, 6))

    # 左軸: 電力フロー
    ax1.plot(df_day['timestamp'], df_day['demand_kW'],
             color='red', linewidth=2, label='Demand')
    ax1.plot(df_day['timestamp'], df_day['pv_kW'],
             color='darkorange', linewidth=2, linestyle='--', label='PV Generation')
    ax1.plot(df_day['timestamp'], df_day['pv_used_kW'],
             color='orange', linewidth=2, label='PV使用')
    ax1.plot(df_day['timestamp'], df_day['sBY'],
             color='blue', linewidth=2, label='Purchased Power')

    ax1.set_xlabel('Time', fontsize=12)
    ax1.set_ylabel('Power [kW]', fontsize=12)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left', fontsize=10)

    # y軸の範囲設定
    y1_max = max(df_day['demand_kW'].max(),
                 df_day['pv_kW'].max(),
                 df_day['pv_used_kW'].max(),
                 df_day['sBY'].max())
    ax1.set_ylim(0, y1_max * 1.1)

    # 右軸: 蓄電池SOC
    ax2 = ax1.twinx()
    ax2.plot(df_day['timestamp'], df_day['bF'],
             color='green', linewidth=2.5, linestyle='--', label='Battery SOC')

    # bF_max を動的に決定（CSVに列があれば優先、それ以外はフォルダ名から推定）
    try:
        if 'bF_max' in df.columns:
            bF_max = float(df['bF_max'].iloc[0])
        else:
            import re
            bF_max = 860.0
            for token in (results_dir,):
                if isinstance(token, str) and 'soc' in token:
                    m = re.search(r'soc(\d+)', token)
                    if m:
                        bF_max = float(m.group(1))
                        break
    except Exception:
        bF_max = 860.0

    # 50%ラインを描画（bF_max 使用）
    ax2.axhline(y=bF_max * 0.5, color='red', linestyle=':', linewidth=1, alpha=0.5)

    ax2.set_ylabel('蓄電池SOC [kWh]', fontsize=12)
    ax2.set_ylim(0, bF_max * 1.05)
    ax2.legend(loc='upper right', fontsize=10)

    # 時刻軸のフォーマット
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # タイトル
    ax1.set_title(f'需要が少なく満充電に到達した日の運用パターン ({target_date}, PV余剰: {pv_surplus:.0f} kWh, 余剰率: {curtail_ratio:.1f}%)',
                  fontsize=12, pad=10)

    plt.tight_layout()

    # 保存
    output_file = os.path.join(project_root, png_dir, 'pv_curtailment_pattern.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f'✓ グラフを保存: {output_file}')

    # 詳細統計
    print(f'\n=== 詳細統計 ===')
    print(f'需要: 平均 {df_day["demand_kW"].mean():.2f} kW, 最大 {df_day["demand_kW"].max():.2f} kW')
    print(f'PV発電可能量: 平均 {df_day["pv_kW"].mean():.2f} kW, 最大 {df_day["pv_kW"].max():.2f} kW')
    print(f'PV使用量: 平均 {df_day["pv_used_kW"].mean():.2f} kW, 最大 {df_day["pv_used_kW"].max():.2f} kW')
    print(f'PV余剰: 平均 {df_day["pv_surplus_kW"].mean():.2f} kW, 最大 {df_day["pv_surplus_kW"].max():.2f} kW')
    print(f'買電: 平均 {df_day["sBY"].mean():.2f} kW, 最大 {df_day["sBY"].max():.2f} kW')
    print(f'SOC: 平均 {df_day["bF"].mean():.2f} kWh, 最大 {df_day["bF"].max():.2f} kWh, 最小 {df_day["bF"].min():.2f} kWh')

    # 満充電時間の計算
    full_charge_hours = (df_day['bF'] >= bF_max).sum() * 0.5
    print(f'満充電時間: {full_charge_hours:.1f} 時間 ({full_charge_hours/24*100:.1f}%)')

    plt.close()

    return target_date

if __name__ == '__main__':
    # 引数なしの場合は自動的に最大余剰日を選択
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--soc', type=str, default=None, help='SOCサブフォルダ名（例: soc860）')
    parser.add_argument('--horizon', type=int, default=96, help='予測期間（ステップ数）。96以外の場合はh{horizon}/サブフォルダを使用')
    args = parser.parse_args()

    # horizon=96 が基準、それ以外は h{horizon}/ サブフォルダを追加
    if args.horizon == 96:
        horizon_prefix = ''
    else:
        horizon_prefix = f'h{args.horizon}/'

    if args.soc:
        results_dir = f'results/{horizon_prefix}{args.soc}'
        png_dir = f'png/{horizon_prefix}{args.soc}'
    else:
        results_dir = f'results/{horizon_prefix}'.rstrip('/')
        png_dir = f'png/{horizon_prefix}'.rstrip('/')

    generate_pv_curtailment_pattern(results_dir=results_dir, png_dir=png_dir)
    print('\n完了しました！')

