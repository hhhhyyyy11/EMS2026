# -*- coding: utf-8 -*-
import sys
import os
import time
import numpy as np
import pandas as pd
import numba

# Sharedモジュールのインポート設定
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from Shared import data_loader

# Numba JITによる高速化されたDP計算関数
@numba.jit(nopython=True)
def run_dp_calculation(K, B, soc_levels, cost_table, path_table,
                       gP1, dA2, pBY,
                       alpha_FC, alpha_FD, aFC_max, aFD_max,
                       p_buy_max, dt):
    """
    K: ステップ数 (336)
    B: SOCのグリッド数
    soc_levels: SOCレベル配列 [kWh]
    cost_table, path_table: DP用のコスト表と遷移パス記録用表
    gP1: 太陽光発電量 [kW]
    dA2: 総需要 [kW]
    pBY: 買電単価 [円/kWh]
    alpha_FC, alpha_FD: 充電、放電効率
    aFC_max, aFD_max: 最大充電、放電電力 [kW] (400 kW)
    p_buy_max: 買電電力のハード制約上限 [kW] (170 kW)
    dt: 時間ステップ幅 [h] (0.5時間)
    """
    for k in range(1, K + 1):
        data_idx = k - 1
        p_pv = gP1[data_idx]
        p_demand = dA2[data_idx]
        price = pBY[data_idx]

        for j in range(B):  # 時点 k (現時点) のSOCインデックス
            b_curr = soc_levels[j]

            for i in range(B):  # 時点 k-1 (過去時点) のSOCインデックス
                if np.isinf(cost_table[k - 1, i]):
                    continue

                b_prev = soc_levels[i]

                # 蓄電池の内部電力量変化 [kWh]
                delta_E = b_curr - b_prev

                p_fc1 = 0.0
                p_fd2 = 0.0

                if delta_E >= 0:  # 充電
                    # 内部への充電電力 [kW]
                    p_fc2 = delta_E / dt
                    # 外部からの充電電力 [kW] (効率ロスを考慮)
                    p_fc1 = p_fc2 / alpha_FC

                    # 充電電力上限制約チェック
                    if p_fc2 > aFC_max + 1e-6:
                        continue
                else:  # 放電
                    # 内部からの放電電力 [kW]
                    p_fd1 = -delta_E / dt
                    # 外部への放電出力 [kW] (効率ロスを考慮)
                    p_fd2 = p_fd1 * alpha_FD

                    # 放電電力上限制約チェック
                    if p_fd1 > aFD_max + 1e-6:
                        continue

                # 系統電力需給バランスの計算 [kW]
                p_grid = p_demand + p_fc1 - p_fd2 - p_pv
                p_buy = p_grid if p_grid > 0.0 else 0.0  # 逆潮流なし（売電は0）

                # 買電電力のハード制約上限チェック（170 kWピーク制限）
                if p_buy > p_buy_max + 1e-6:
                    continue

                # ステップ電力量料金コストの計算 [円]
                step_cost = price * p_buy * dt

                total_cost = cost_table[k - 1, i] + step_cost

                # 最小コスト経路の更新
                if total_cost < cost_table[k, j]:
                    cost_table[k, j] = total_cost
                    path_table[k, j] = i

    return cost_table, path_table

def run_dp_test(grid_pct):
    """指定されたグリッド幅（容量に対する%）でDPを実行"""
    print(f"\n--- SOC離散化グリッド幅: {grid_pct}% でのDPテスト実行 ---")
    start_time = time.perf_counter()

    # 設定と共通データのロード
    config = data_loader.load_config('config.json')
    df_full = data_loader.get_simulation_data('config.json')

    # 夏のピークを含む1週間の切り出し (2025年7月22日 00:00 〜 2025年7月28日 23:30, 計336ステップ)
    test_start = '2025-07-22 00:00:00'
    test_end = '2025-07-28 23:30:00'
    df_trend = df_full.loc[test_start:test_end]
    K = len(df_trend)
    print(f"テストデータステップ数: {K} (期間: {test_start} から {test_end})")

    # バッテリーパラメータのロード
    battery_config = config.get('battery', {})
    bF_max = battery_config.get('capacity_kWh', 860.0)
    aFC = battery_config.get('charge_limit_kW', 400.0)
    aFD = battery_config.get('discharge_limit_kW', 400.0)
    alpha_FC = battery_config.get('charge_efficiency', 0.98)
    alpha_FD = battery_config.get('discharge_efficiency', 0.98)
    initial_soc_ratio = battery_config.get('initial_soc_ratio', 0.5)

    # 運用SOCの上下限 (5%〜95%)
    soc_min = bF_max * 0.05
    soc_max = bF_max * 0.95
    bF0 = bF_max * initial_soc_ratio

    # グリッドの作成
    # 指定された%刻みのステップサイズ [kWh] を計算
    step_size = bF_max * (grid_pct / 100.0)
    B = int(np.round((soc_max - soc_min) / step_size)) + 1
    soc_levels = np.linspace(soc_min, soc_max, B)
    print(f"SOC離散化グリッド数: {B} 点 (ステップ幅: {step_size:.2f} kWh)")

    # 共通データマッピング
    gP1 = df_trend['pv_kW'].values
    gP1[gP1 < 0] = 0.0
    dA2 = df_trend['consumption_kW'].values
    pBY = df_trend['price_yen_per_kWh'].values

    # DPテーブルの初期化
    cost_table = np.full((K + 1, B), np.inf)
    path_table = np.zeros((K + 1, B), dtype=np.int64)

    # 初期状態の設定 (SOC = 50%に最も近いインデックス)
    initial_soc_idx = np.argmin(np.abs(soc_levels - bF0))
    cost_table[0, initial_soc_idx] = 0.0

    # 170kW ハードピーク制限
    p_buy_max = 170.0
    dt = 0.5

    # 計算実行
    print("Numba DPソルバー起動...")
    # JITのコンパイル時間を含めて計測
    calc_start = time.perf_counter()
    cost_table, path_table = run_dp_calculation(
        K, B, soc_levels, cost_table, path_table,
        gP1, dA2, pBY,
        alpha_FC, alpha_FD, aFC, aFD,
        p_buy_max, dt
    )
    calc_end = time.perf_counter()
    calc_time = calc_end - calc_start

    # バックトラッキングによる最適経路探索
    optimal_path_indices = np.zeros(K + 1, dtype=np.int64)
    optimal_path_indices[K] = np.argmin(cost_table[K, :])
    
    if np.isinf(cost_table[K, optimal_path_indices[K]]):
        print("ERROR: 実行可能解（ピーク170kW制約を満たす経路）が見つかりませんでした。")
        return None

    # 最適経路を復元
    for k in range(K, 0, -1):
        optimal_path_indices[k - 1] = path_table[k, optimal_path_indices[k]]

    # 買電電力等の時系列結果を再構築し、ハード制約が守られているか検証
    max_buy_power_observed = 0.0
    total_cost = cost_table[K, optimal_path_indices[K]]

    for k in range(K):
        idx_prev = optimal_path_indices[k]
        idx_curr = optimal_path_indices[k + 1]
        b_prev = soc_levels[idx_prev]
        b_curr = soc_levels[idx_curr]
        
        delta_E = b_curr - b_prev
        p_fc1 = 0.0
        p_fd2 = 0.0
        
        if delta_E >= 0:
            p_fc2 = delta_E / dt
            p_fc1 = p_fc2 / alpha_FC
        else:
            p_fd1 = -delta_E / dt
            p_fd2 = p_fd1 * alpha_FD
            
        p_grid = dA2[k] + p_fc1 - p_fd2 - gP1[k]
        p_buy = p_grid if p_grid > 0.0 else 0.0
        
        if p_buy > max_buy_power_observed:
            max_buy_power_observed = p_buy

    total_time = time.perf_counter() - start_time
    print(f"DP計算（ソルバー内）時間: {calc_time:.5f} 秒")
    print(f"総処理時間（ロード・構築等含む）: {total_time:.5f} 秒")
    print(f"算出された電力量料金: {total_cost:,.2f} 円")
    print(f"最適経路上の最大買電電力: {max_buy_power_observed:.2f} kW (制約上限 170.00 kW に対して安全)")
    
    return {
        'grid_pct': grid_pct,
        'calc_time': calc_time,
        'total_time': total_time,
        'total_cost': total_cost,
        'max_buy_power': max_buy_power_observed
    }

if __name__ == '__main__':
    results = []
    # ユーザー指示の10%刻み、および5%刻みで実行
    for pct in [10, 5]:
        res = run_dp_test(pct)
        if res:
            results.append(res)
            
    print("\n==================================================")
    print("【夏のピーク1週間テスト実行 結果サマリー】")
    print("==================================================")
    for r in results:
        print(f"SOC離散化幅: {r['grid_pct']}%刻み")
        print(f"  - DP計算時間: {r['calc_time']:.4f} 秒")
        print(f"  - 電力量料金: {r['total_cost']:,.2f} 円")
        print(f"  - 最大買電電力: {r['max_buy_power']:.2f} kW")
        print("--------------------------------------------------")