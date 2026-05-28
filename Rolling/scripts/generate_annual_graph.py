#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年間のPV発電・買電・需要の推移グラフを生成するスクリプト
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from typing import Optional

# Font settings (English)
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

def generate_annual_pv_buy_demand_graph(results_dir: str = 'results', png_dir: str = 'png'):
    """年間のPV発電・買電・需要の推移グラフを生成

    Args:
        results_dir: results ディレクトリまたはサブフォルダパス（workspace 相対）
        png_dir: png 出力ディレクトリまたはサブフォルダパス（workspace 相対）
    """

    # データ読み込み
    base_dir = Path(__file__).parent.parent
    results_file = Path(base_dir) / Path(results_dir) / 'rolling_results.csv'
    output_dir = Path(base_dir) / Path(png_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"データ読み込み中: {results_file}")
    df = pd.read_csv(results_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # グラフ作成
    fig, ax = plt.subplots(figsize=(14, 6))

    # データプロット
    ax.plot(df['timestamp'], df['demand_kW'], label='Demand', linewidth=0.5, alpha=0.7, color='red')
    ax.plot(df['timestamp'], df['pv_kW'], label='PV Generation', linewidth=0.5, alpha=0.7, color='orange')
    ax.plot(df['timestamp'], df['sBY'], label='Purchased Power', linewidth=0.5, alpha=0.7, color='blue')

    # Graph settings
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Power [kW]', fontsize=12)
    ax.set_title('Annual Transition of PV Generation, Purchased Power, and Demand (2024)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.3)

    # X軸の日付フォーマット
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)

    # Y軸の範囲設定（0から開始）
    ax.set_ylim(bottom=0)

    plt.tight_layout()

    # 保存
    output_file = output_dir / 'annual_pv_buy_demand.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"グラフ保存完了: {output_file}")

    # 統計情報表示
    print("\n=== データ統計 ===")
    print(f"データ期間: {df['timestamp'].min()} ～ {df['timestamp'].max()}")
    print(f"データポイント数: {len(df)}")
    print(f"\n需要 [kW]: 平均={df['demand_kW'].mean():.2f}, 最大={df['demand_kW'].max():.2f}, 最小={df['demand_kW'].min():.2f}")
    print(f"PV発電 [kW]: 平均={df['pv_kW'].mean():.2f}, 最大={df['pv_kW'].max():.2f}, 最小={df['pv_kW'].min():.2f}")
    print(f"買電 [kW]: 平均={df['sBY'].mean():.2f}, 最大={df['sBY'].max():.2f}, 最小={df['sBY'].min():.2f}")

    # PV発電がゼロでないデータ点の確認
    pv_nonzero = df[df['pv_kW'] > 0]
    print(f"\nPV発電がゼロでないデータ点: {len(pv_nonzero)} / {len(df)} ({100*len(pv_nonzero)/len(df):.1f}%)")

    plt.close()

def generate_annual_soc_graph(results_dir: str = 'results', png_dir: str = 'png', bF_max: Optional[int] = None):
    """年間のSOC推移グラフを生成

    Args:
        results_dir: results ディレクトリまたはサブフォルダパス（workspace 相対）
        png_dir: png 出力ディレクトリまたはサブフォルダパス（workspace 相対）
        bF_max: 蓄電池容量（kWh） - グラフの目盛り等で使用
    """

    # データ読み込み
    base_dir = Path(__file__).parent.parent
    results_file = Path(base_dir) / Path(results_dir) / 'rolling_results.csv'
    output_dir = Path(base_dir) / Path(png_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nデータ読み込み中: {results_file}")
    df = pd.read_csv(results_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # グラフ作成
    fig, ax = plt.subplots(figsize=(14, 6))

    # SOCデータプロット
    ax.plot(df['timestamp'], df['bF'], linewidth=0.5, alpha=0.8, color='green')

    # グラフ設定
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('SOC [kWh]', fontsize=12)
    ax.set_title('Annual Battery SOC Transition (2024)', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    # X軸の日付フォーマット
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=45)

    # bF_max を動的に決定（引数 > CSV列 > png_dir名 > デフォルト860）
    try:
        if bF_max is None:
            # try to read from results CSV
            sample = pd.read_csv(Path(base_dir) / Path(results_dir) / 'rolling_results.csv', nrows=1)
            if 'bF_max' in sample.columns:
                bF_max = int(sample['bF_max'].iloc[0])
            else:
                # infer from results_dir or png_dir name like socNNN
                import re
                for token in (results_dir, png_dir):
                    if isinstance(token, str):
                        m = re.search(r'soc(\d+)', token)
                        if m:
                            bF_max = int(m.group(1))
                            break
        if bF_max is None:
            bF_max = 860
    except Exception:
        bF_max = 860

    # Y軸の範囲設定（0 - bF_max）: SOCの最大容量に合わせる
    ax.set_ylim(0, bF_max)

    # 容量の50%ラインを追加
    half = bF_max / 2.0
    ax.axhline(y=half, color='red', linestyle='--', linewidth=1, alpha=0.5, label=f'50% ({half:.0f}kWh)')
    ax.legend(loc='upper right', fontsize=10)

    plt.tight_layout()

    # 保存
    output_file = output_dir / 'annual_soc.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"グラフ保存完了: {output_file}")

    # 統計情報表示
    print(f"\n=== SOC統計 ===")
    mean = df['bF'].mean()
    maxv = df['bF'].max()
    minv = df['bF'].min()
    print(f"平均SOC: {mean:.2f} kWh ({100*mean/bF_max:.1f}%)")
    print(f"最大SOC: {maxv:.2f} kWh ({100*maxv/bF_max:.1f}%)")
    print(f"最小SOC: {minv:.2f} kWh ({100*minv/bF_max:.1f}%)")
    print(f"標準偏差: {df['bF'].std():.2f} kWh")

    plt.close()

if __name__ == '__main__':
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

    # bF_max が環境やファイル名から決まる場合は引数で上書き可能
    bF_max = None
    try:
        # results ディレクトリ内の rolling_results.csv に bF_max 情報がある場合に読み取る
        sample = pd.read_csv(Path(__file__).parent.parent / Path(results_dir) / 'rolling_results.csv', nrows=1)
        if 'bF_max' in sample.columns:
            bF_max = int(sample['bF_max'].iloc[0])
    except Exception:
        bF_max = None

    generate_annual_pv_buy_demand_graph(results_dir=results_dir, png_dir=png_dir)
    generate_annual_soc_graph(results_dir=results_dir, png_dir=png_dir, bF_max=bF_max)
