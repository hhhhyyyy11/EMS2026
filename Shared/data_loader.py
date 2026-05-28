import os
import json
import pandas as pd
import numpy as np

def load_config(config_path='config.json'):
    """config.jsonから設定情報をロード"""
    if not os.path.exists(config_path):
        # EMSルートからの相対パス解決を試みる
        possible_paths = [
            config_path,
            os.path.join(os.path.dirname(__file__), '..', config_path),
            os.path.join(os.getcwd(), config_path)
        ]
        for p in possible_paths:
            if os.path.exists(p):
                config_path = p
                break
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def is_number(x):
    """値が数値に変換可能か判定"""
    try:
        float(x)
        return True
    except Exception:
        return False

def read_energy_data(path, sheet_name='30分値'):
    """Excelの30分値から消費電力[kW]および太陽光発電量[kW]をロード"""
    if not os.path.exists(path):
        possible_paths = [path, os.path.join(os.path.dirname(__file__), '..', path)]
        for p in possible_paths:
            if os.path.exists(p):
                path = p
                break
                
    xls = pd.ExcelFile(path)
    df = pd.read_excel(xls, sheet_name=sheet_name, header=0)
    
    col = '消費電力量'
    if col not in df.columns:
        raise KeyError(f"Expected column '{col}' in sheet '{sheet_name}'")
        
    df = df[df[col].apply(lambda x: is_number(x))]
    df = df.copy()
    
    pv_col = '発電量'
    if pv_col in df.columns:
        df = df[df[pv_col].apply(lambda x: is_number(x)) | df[pv_col].isnull()]
        df[pv_col] = pd.to_numeric(df[pv_col], errors='coerce').fillna(0.0)
    else:
        df[pv_col] = 0.0
        
    df['datetime'] = pd.to_datetime(df['日付'].astype(str) + ' ' + df['時刻'].astype(str))
    df.set_index('datetime', inplace=True)
    df[col] = pd.to_numeric(df[col])
    
    # 30分積算エネルギー [kWh] → 平均電力 [kW] (Δt=0.5h なので ×2)
    df['consumption_kW'] = df[col] * 2.0
    df['pv_kW'] = df[pv_col] * 2.0
    
    return df[['consumption_kW', 'pv_kW']]

def read_jepx_prices(path_2023, path_2024):
    """JEPXスポット価格CSVをロードし30分値に展開"""
    def process_spot_data(df):
        expanded_data = []
        for _, row in df.iterrows():
            date_str = row['受渡日']
            time_code = row['時刻コード']  # 1..48 (30分間隔スロット)
            price = row['エリアプライス北海道(円/kWh)']
            
            if time_code <= 47:
                start_hour = time_code - 1
                base_date = pd.to_datetime(date_str)
            else:
                start_hour = 23
                base_date = pd.to_datetime(date_str)
                
            for minute in [0, 30]:
                timestamp = base_date + pd.Timedelta(hours=start_hour, minutes=minute)
                expanded_data.append({
                    'datetime': timestamp,
                    'price_yen_per_kWh': price
                })
        return expanded_data

    # 各パスの解決
    paths = [path_2023, path_2024]
    resolved_paths = []
    for p in paths:
        if not os.path.exists(p):
            possible_paths = [p, os.path.join(os.path.dirname(__file__), '..', p)]
            for pos in possible_paths:
                if os.path.exists(pos):
                    p = pos
                    break
        resolved_paths.append(p)
    path_2023, path_2024 = resolved_paths
    
    df_2024 = pd.read_csv(path_2024, encoding='shift_jis')
    expanded_2024 = process_spot_data(df_2024)
    
    try:
        df_2023 = pd.read_csv(path_2023, encoding='shift_jis')
        expanded_2023 = process_spot_data(df_2023)
        all_data = expanded_2023 + expanded_2024
    except Exception as e:
        print(f"Warning: Could not load 2023 data ({e}), using 2024 data only")
        all_data = expanded_2024
        
    price_df = pd.DataFrame(all_data)
    price_df = price_df.drop_duplicates(subset=['datetime'])
    price_df.set_index('datetime', inplace=True)
    price_df.sort_index(inplace=True)
    price_df = price_df[~price_df.index.duplicated(keep='first')]
    return price_df

def get_simulation_data(config_path='config.json', sheet_name='30分値'):
    """config.jsonの設定に沿って、共通の統合需要・PV・単価DataFrameを返す"""
    config = load_config(config_path)
    
    # エネルギーデータのロード
    excel_path = config['data_paths']['energy_excel']
    df_energy = read_energy_data(excel_path, sheet_name=sheet_name)
    
    price_plan = config.get('price_plan', 'fixed_price')
    
    if price_plan == 'market_linked':
        # JEPX市場価格連動モード
        path_2023 = config['data_paths']['spot_price_2023']
        path_2024 = config['data_paths']['spot_price_2024']
        df_price = read_jepx_prices(path_2023, path_2024)
        
        # 再エネ賦課金を加算 (3.98円/kWh)
        renewable_levy = 3.98
        
        # マージ
        df_merged = df_energy.join(df_price, how='left')
        
        # 価格データがない時間帯のフォールバック
        fixed_price = config.get('fixed_price_yen_per_kWh', 21.51)
        df_merged['price_yen_per_kWh'] = df_merged['price_yen_per_kWh'].fillna(fixed_price)
        df_merged['price_yen_per_kWh'] = df_merged['price_yen_per_kWh'] + renewable_levy
    else:
        # 固定単価モード
        fixed_price = config.get('fixed_price_yen_per_kWh', 21.51)
        df_merged = df_energy.copy()
        df_merged['price_yen_per_kWh'] = fixed_price
        
    return df_merged
