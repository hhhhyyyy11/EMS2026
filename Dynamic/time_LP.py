from pyscipopt import Model
import pandas as pd
import numpy as np
import time

# --- 設定項目 ---
NUM_TRIALS = 1  # 試行回数 (例: 100)
K_PERIODS = 10080   # 計画期間 (1分刻みと仮定して20時間分)
START_HOUR = 0      # シミュレーション開始時刻 (0時)

# 定数設定 (元のコードに基づく)
J_P = 2; J_DA = 1; J_DB = 1; J_DC = 1; J_DD = 1; J_FC = 1; J_FD = 1
M = 1e6
alpha_P = {j: 0.5 * (j + 1) for j in range(J_P)}; beta_P = {j: -0.5*j for j in range(J_P)}
alpha_DA = {j: 0.94 for j in range(J_DA)}; beta_DA = {j: 0.00 for j in range(J_DA)}
alpha_DB = {j: 0.94 for j in range(J_DB)}; beta_DB = {j: 0.00 for j in range(J_DB)}
alpha_DC = {j: 0.94 for j in range(J_DC)}; beta_DC = {j: 0.00 for j in range(J_DC)}
alpha_DD = {j: 0.94 for j in range(J_DD)}; beta_DD = {j: 0.00 for j in range(J_DD)}
alpha_FC = {j: 0.94 for j in range(J_FC)}; beta_FC = {j: 0.00 for j in range(J_FC)}
alpha_FD = {j: 0.94 for j in range(J_FD)}; beta_FD = {j: 0.00 for j in range(J_FD)}

bF_max = 2742      # バッテリー容量上限
aFC = 450 / 60     # 最大充電量
aFD = 450 / 60     # 最大放電量
sBYMAX = 50.0 / 60.0 # 最大買電量

def generate_scenario(seed, K):
    """
    指定されたシード値に基づいてシナリオデータ(gP1, dA2, etc.)を生成する関数
    """
    np.random.seed(seed)
    
    # 時間軸の作成 (0始まり、1ステップ=1分と仮定)
    # 0 -> 0:00, 360 -> 6:00, 840 -> 14:00, 1140 -> 19:00
    minutes = np.arange(K) + START_HOUR * 60
    hours_of_day = (minutes // 60) % 24
    exact_hours = minutes / 60.0 % 24  # 小数点付きの時間
    
    # 1. 太陽光発電 (gP1)
    # 19:00-06:00 は0。それ以外は14:00ピークの逆V字
    # ピーク値: (150~250)/60
    peak_val_solar = np.random.uniform(150, 250) / 60
    
    base_solar = np.zeros(K)
    for k in range(K):
        h = exact_hours[k]
        if 6 <= h < 14:
            # 6時から14時まで直線的に上昇
            base_solar[k] = peak_val_solar * (h - 6) / (14 - 6)
        elif 14 <= h < 19:
            # 14時から19時まで直線的に下降
            base_solar[k] = peak_val_solar * (19 - h) / (19 - 14)
        else:
            base_solar[k] = 0
            
    # ノイズ付加: 各期について 0.8~1.2 の一様乱数を掛ける
    noise_solar = np.random.uniform(0.8, 1.2, K)
    gP1 = base_solar * noise_solar
    
    # 2. dA2, dB2 (一様乱数 0~20/60)
    dA2 = np.random.uniform(0, 20/60, K)
    dB2 = np.random.uniform(0, 20/60, K)
    
    # 3. dC2
    # 太陽光と同様のロジックだがピーク値が異なる ((100~200)/60)
    peak_val_C = np.random.uniform(100, 200) / 60
    base_C = np.zeros(K)
    for k in range(K):
        h = exact_hours[k]
        if 6 <= h < 14:
            base_C[k] = peak_val_C * (h - 6) / (14 - 6)
        elif 14 <= h < 19:
            base_C[k] = peak_val_C * (19 - h) / (19 - 14)
        else:
            base_C[k] = 0
            
    noise_C = np.random.uniform(0.8, 1.2, K)
    dC2 = base_C * noise_C
    
    # 4. pBY (売買電単価)
    # 30分ごと(30ステップごと)に 10~120 の一様乱数
    num_blocks = (K + 29) // 30
    block_prices = np.random.uniform(10, 120, num_blocks)
    pBY = np.repeat(block_prices, 30)[:K]
    pSL = pBY.copy() # 売電単価も同じと仮定(元のロジック準拠)
    
    # 5. 初期SOC (bF0)
    # 10%~90% の一様乱数
    bF0_percent = np.random.uniform(0.1, 0.9)
    bF0 = bF0_percent * bF_max
    
    return gP1, dA2, dB2, dC2, pBY, pSL, bF0

def run_optimization(seed, K):
    """
    1回分の最適化を実行し、計算にかかった時間を返す
    """
    # データの生成 (計測対象外)
    gP1, dA2, dB2, dC2, pBY, pSL, bF0 = generate_scenario(seed, K)
    
    # --- 計測開始 ---
    # モデル構築から最適化完了までを計測
    start_time = time.perf_counter()
    
    model = Model(f'PowerOptimization_seed{seed}')
    # 出力を抑制
    model.hideOutput()

    # 変数の定義
    # 変数作成もモデル構築の一部なので計測時間に含めます
    sBY_vars = {}
    sSL_vars = {}
    v_vars = {}
    gP2_vars = {}
    dA1_vars = {}
    dB1_vars = {}
    dC1_vars = {}
    bF_vars = {}
    xFC1_vars = {}
    xFC2_vars = {}
    xFD1_vars = {}
    xFD2_vars = {}

    for k in range(K):
        sBY_vars[k] = model.addVar(vtype='C', lb=0, name=f"sBY_{k}")
        sSL_vars[k] = model.addVar(vtype='C', lb=0, name=f"sSL_{k}")
        v_vars[k]   = model.addVar(vtype='C', lb=0, name=f"v_{k}")
        gP2_vars[k] = model.addVar(vtype='C', lb=0, name=f"gP2_{k}")
        dA1_vars[k] = model.addVar(vtype='C', lb=0, name=f"dA1_{k}")
        dB1_vars[k] = model.addVar(vtype='C', lb=0, name=f"dB1_{k}")
        dC1_vars[k] = model.addVar(vtype='C', lb=0, name=f"dC1_{k}")
        bF_vars[k]  = model.addVar(vtype='C', lb=0, name=f"bF_{k}")
        xFC1_vars[k]= model.addVar(vtype='C', lb=0, name=f"xFC1_{k}")
        xFC2_vars[k]= model.addVar(vtype='C', lb=0, name=f"xFC2_{k}")
        xFD1_vars[k]= model.addVar(vtype='C', lb=0, name=f"xFD1_{k}")
        xFD2_vars[k]= model.addVar(vtype='C', lb=0, name=f"xFD2_{k}")

    # 目的関数
    model.setObjective(sum(pBY[k] * sBY_vars[k] - (pSL[k]-1e-9)*sSL_vars[k] for k in range(K)), 'minimize')

    # 制約条件
    for k in range(K):
        # 電力バランス
        model.addCons(gP2_vars[k] + sBY_vars[k] - sSL_vars[k] - xFC1_vars[k] + xFD2_vars[k] - dA1_vars[k] - dB1_vars[k] - dC1_vars[k] - v_vars[k] == 0)
        
        # 変換効率
        model.addCons(gP2_vars[k] == alpha_P[0] * gP1[k] + beta_P[0])
        model.addCons(alpha_DA[0] * dA1_vars[k] + beta_DA[0] == dA2[k])
        model.addCons(alpha_DB[0] * dB1_vars[k] + beta_DB[0] == dB2[k])
        model.addCons(alpha_DC[0] * dC1_vars[k] + beta_DC[0] == dC2[k])
        
        model.addCons(xFC2_vars[k] == alpha_FC[0] * xFC1_vars[k] + beta_FC[0])
        model.addCons(xFD2_vars[k] == alpha_FD[0] * xFD1_vars[k] + beta_FD[0])
        
        # バッテリーSOC更新
        if k == 0:
            model.addCons(bF_vars[k] == bF0 + xFC2_vars[k] - xFD1_vars[k])
        else:
            model.addCons(bF_vars[k] == 0.99999999999 * bF_vars[k-1] + xFC2_vars[k] - xFD1_vars[k])
            
        model.addCons(bF_vars[k] <= bF_max)
        model.addCons(xFC2_vars[k] <= aFC)
        model.addCons(xFD1_vars[k] <= aFD)
        
        # 買電制約 (30分ごとの総量規制)
        # ※ k % 30 == 0 の時だけ追加
        if k % 30 == 0 and (k + 30 <= K):
            model.addCons(sum(sBY_vars[k2] for k2 in range(k, k+30)) <= sBYMAX * 30)

    # 最適化実行
    model.optimize()
    
    end_time = time.perf_counter()
    # --- 計測終了 ---
    
    elapsed = end_time - start_time
    
    return elapsed

# --- メイン処理 ---
if __name__ == "__main__":
    print(f"計算を開始します。試行回数: {NUM_TRIALS}, 期間K: {K_PERIODS}")
    cpu_times = []

    # 全体の開始時刻（参考用）
    total_start_wall = time.perf_counter()

    for i in range(NUM_TRIALS):
        # run_optimization内で個別に計測した時間を取得
        t = run_optimization(seed=i, K=K_PERIODS)
        cpu_times.append(t)
        
        if (i + 1) % 10 == 0:
            print(f"処理中: {i + 1}/{NUM_TRIALS} 回完了... (直近の計算時間: {t:.4f}秒)")

    total_end_wall = time.perf_counter()

    # 統計量の計算
    avg_time = np.mean(cpu_times)
    var_time = np.var(cpu_times)
    min_time = np.min(cpu_times)
    max_time = np.max(cpu_times)

    print("-" * 30)
    print(f"【結果サマリ】 (試行回数: {NUM_TRIALS})")
    print(f"合計経過時間(Wall clock): {total_end_wall - total_start_wall:.4f} 秒")
    print(f"平均計算時間 (Model構築+Solve): {avg_time:.5f} 秒")
    print(f"分散        : {var_time:.5f}")
    print(f"最小値      : {min_time:.5f} 秒")
    print(f"最大値      : {max_time:.5f} 秒")
    print("-" * 30)

    # 必要であればCSVに時間のリストを保存
    df_times = pd.DataFrame(cpu_times, columns=['Calculation_Time'])
    df_times.index.name = 'Seed'
    df_times.to_csv('cpu_times_benchmark.csv')
    print("各試行の計算時間を 'cpu_times_benchmark.csv' に保存しました。")