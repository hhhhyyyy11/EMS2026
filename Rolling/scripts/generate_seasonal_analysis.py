#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Seasonal analysis script (English version)
Aggregates simulation results by month and season, calculates evaluation metrics, and generates graphs.
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import argparse
import os
import json
import re

# English font settings
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

def load_data(results_dir):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    csv_path = os.path.join(project_root, results_dir, 'rolling_results.csv')

    print(f"Loading data from: {csv_path}")
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date
    return df, project_root

def analyze_monthly(df):
    """Monthly analysis"""
    df['month'] = df['timestamp'].dt.month

    # Check if pv_used_kW exists, if not calculate it or use gP2 logic if applicable (but gP2 is missing)
    if 'pv_used_kW' not in df.columns:
        # Fallback: PV Used = PV Generation - PV Surplus (if exists)
        if 'pv_surplus_kW' in df.columns:
             df['pv_used_kW'] = df['pv_kW'] - df['pv_surplus_kW']
        else:
             # Worst case, assume PV Used = PV Generation (no curtailment information)
             print("Warning: pv_used_kW and pv_surplus_kW missing. Assuming PV Used = PV Gen.")
             df['pv_used_kW'] = df['pv_kW']

    monthly_stats = df.groupby('month').agg({
        'demand_kW': ['sum', 'max'],
        'pv_kW': ['sum'],
        'sBY': ['sum', 'max'],
        'bF': ['mean'],
        'pv_used_kW': ['sum']
    })

    # 30-min data to kWh (sum * 0.5)
    monthly_df = pd.DataFrame({
        'month': monthly_stats.index,
        'demand_total_kWh': monthly_stats[('demand_kW', 'sum')] * 0.5,
        'pv_total_kWh': monthly_stats[('pv_kW', 'sum')] * 0.5,
        'buy_total_kWh': monthly_stats[('sBY', 'sum')] * 0.5,
        'demand_peak_kW': monthly_stats[('demand_kW', 'max')],
        'buy_peak_kW': monthly_stats[('sBY', 'max')],
        'pv_used_kWh': monthly_stats[('pv_used_kW', 'sum')] * 0.5
    })

    # Calculate metrics
    monthly_df['pv_self_consumption_rate'] = (monthly_df['pv_used_kWh'] / monthly_df['pv_total_kWh']) * 100
    monthly_df['peak_cut_rate'] = (1 - monthly_df['buy_peak_kW'] / monthly_df['demand_peak_kW']) * 100

    # Battery contribution
    monthly_df['battery_net_contribution_kWh'] = monthly_df['demand_total_kWh'] - monthly_df['buy_total_kWh'] - monthly_df['pv_used_kWh']
    monthly_df['battery_contribution_rate'] = (monthly_df['battery_net_contribution_kWh'] / monthly_df['demand_total_kWh']) * 100

    return monthly_df

def analyze_seasonal(df):
    """Seasonal analysis"""
    # 3-5: Spring, 6-8: Summer, 9-11: Autumn, 12-2: Winter
    df['month'] = df['timestamp'].dt.month

    def get_season(month):
        if 3 <= month <= 5: return 'Spring'
        elif 6 <= month <= 8: return 'Summer'
        elif 9 <= month <= 11: return 'Autumn'
        else: return 'Winter'

    df['season'] = df['month'].apply(get_season)

    # Reorder for plot: Spring, Summer, Autumn, Winter
    season_order = ['Spring', 'Summer', 'Autumn', 'Winter']
    df['season_cat'] = pd.Categorical(df['season'], categories=season_order, ordered=True)

    if 'pv_used_kW' not in df.columns:
        if 'pv_surplus_kW' in df.columns:
             df['pv_used_kW'] = df['pv_kW'] - df['pv_surplus_kW']
        else:
             df['pv_used_kW'] = df['pv_kW']

    seasonal_stats = df.groupby('season_cat', observed=False).agg({
        'demand_kW': ['sum', 'max'],
        'pv_kW': ['sum'],
        'sBY': ['sum', 'max'],
        'pv_used_kW': ['sum']
    })

    seasonal_df = pd.DataFrame({
        'season': seasonal_stats.index,
        'demand_total_kWh': seasonal_stats[('demand_kW', 'sum')] * 0.5,
        'pv_total_kWh': seasonal_stats[('pv_kW', 'sum')] * 0.5,
        'buy_total_kWh': seasonal_stats[('sBY', 'sum')] * 0.5,
        'demand_peak_kW': seasonal_stats[('demand_kW', 'max')],
        'buy_peak_kW': seasonal_stats[('sBY', 'max')],
        'pv_used_kWh': seasonal_stats[('pv_used_kW', 'sum')] * 0.5
    })

    seasonal_df['pv_self_consumption_rate'] = (seasonal_df['pv_used_kWh'] / seasonal_df['pv_total_kWh']) * 100
    seasonal_df['peak_cut_rate'] = (1 - seasonal_df['buy_peak_kW'] / seasonal_df['demand_peak_kW']) * 100

    return seasonal_df

def plot_monthly_analysis(monthly_df, png_dir, project_root):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # 1. Monthly Energy
    ax1 = axes[0, 0]
    width = 0.25
    x = np.arange(12)
    ax1.bar(x - width, monthly_df['demand_total_kWh'] / 1000, width, label='Demand', color='red', alpha=0.7)
    ax1.bar(x, monthly_df['pv_total_kWh'] / 1000, width, label='PV Generation', color='orange', alpha=0.7)
    ax1.bar(x + width, monthly_df['buy_total_kWh'] / 1000, width, label='Purchased Power', color='blue', alpha=0.7)
    ax1.set_xlabel('Month')
    ax1.set_ylabel('Energy [MWh]')
    ax1.set_title('Monthly Energy')
    ax1.set_xticks(x)
    ax1.set_xticklabels(month_labels)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Monthly Peak Power
    ax2 = axes[0, 1]
    ax2.bar(x - width/2, monthly_df['demand_peak_kW'], width, label='Demand Peak', color='red', alpha=0.7)
    ax2.bar(x + width/2, monthly_df['buy_peak_kW'], width, label='Purchase Peak', color='blue', alpha=0.7)
    ax2.set_xlabel('Month')
    ax2.set_ylabel('Peak Power [kW]')
    ax2.set_title('Monthly Peak Power')
    ax2.set_xticks(x)
    ax2.set_xticklabels(month_labels)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. PV & Battery Contribution
    ax3 = axes[1, 0]
    ax3.bar(x, monthly_df['pv_self_consumption_rate'], width, label='PV Self-consumption', color='orange', alpha=0.7)
    # ax3.bar(x + width/2, monthly_df['battery_contribution_rate'], width, label='Battery Contrib.', color='green', alpha=0.7)
    ax3.set_xlabel('Month')
    ax3.set_ylabel('Rate [%]')
    ax3.set_title('Monthly PV Self-Consumption Rate')
    ax3.set_xticks(x)
    ax3.set_xticklabels(month_labels)
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    # 4. Peak Shaving Rate
    ax4 = axes[1, 1]
    colors = ['#ff6b6b' if rate < 50 else '#4ecdc4' if rate < 70 else '#45b7d1' for rate in monthly_df['peak_cut_rate']]
    bars = ax4.bar(x, monthly_df['peak_cut_rate'], color=colors, alpha=0.8)
    ax4.axhline(y=monthly_df['peak_cut_rate'].mean(), color='red', linestyle='--', label=f'Annual avg: {monthly_df["peak_cut_rate"].mean():.1f}%')
    ax4.set_xlabel('Month')
    ax4.set_ylabel('Peak Shaving Rate [%]')
    ax4.set_title('Monthly Peak Shaving Rate')
    ax4.set_xticks(x)
    ax4.set_xticklabels(month_labels)
    ax4.legend()
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    output_file = os.path.join(project_root, png_dir, 'monthly_analysis.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_file}")

def plot_seasonal_analysis(seasonal_df, png_dir, project_root):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    seasons = seasonal_df['season']
    x = np.arange(4)

    # 1. Seasonal Energy
    ax1 = axes[0]
    width = 0.25
    ax1.bar(x - width, seasonal_df['demand_total_kWh'] / 1000, width, label='Demand', color='red', alpha=0.7)
    ax1.bar(x, seasonal_df['pv_total_kWh'] / 1000, width, label='PV Generation', color='orange', alpha=0.7)
    ax1.bar(x + width, seasonal_df['buy_total_kWh'] / 1000, width, label='Purchased Power', color='blue', alpha=0.7)
    ax1.set_xlabel('Season')
    ax1.set_ylabel('Energy [MWh]')
    ax1.set_title('Seasonal Energy')
    ax1.set_xticks(x)
    ax1.set_xticklabels(seasons, rotation=15)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Seasonal Metrics
    ax2 = axes[1]
    width = 0.35
    ax2.bar(x - width/2, seasonal_df['pv_self_consumption_rate'], width, label='PV Self-consumption', color='orange', alpha=0.7)
    ax2.bar(x + width/2, seasonal_df['peak_cut_rate'], width, label='Peak Shaving Rate', color='green', alpha=0.7)
    ax2.set_xlabel('Season')
    ax2.set_ylabel('Rate [%]')
    ax2.set_title('Seasonal PV Self-con & Peak Shaving')
    ax2.set_xticks(x)
    ax2.set_xticklabels(seasons, rotation=15)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    output_file = os.path.join(project_root, png_dir, 'seasonal_analysis.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_file}")

def plot_monthly_battery_cycle(df, png_dir, project_root):
    """Estimate daily cycles and plot monthly avg"""
    daily_stats = df.groupby('date').agg({
        'xFC1': lambda x: x.sum() * 0.5,  # Charge kWh
        'xFD1': lambda x: x.sum() * 0.5,  # Discharge kWh
        'bF': ['min', 'max', 'mean'],
    })

    daily_stats.columns = ['charge_kWh', 'discharge_kWh', 'soc_min', 'soc_max', 'soc_mean']
    daily_stats = daily_stats.reset_index()
    daily_stats['date'] = pd.to_datetime(daily_stats['date'])
    daily_stats['month'] = daily_stats['date'].dt.month

    monthly_cycle = daily_stats.groupby('month').agg({
        'charge_kWh': 'sum',
        'discharge_kWh': 'sum',
        'soc_min': 'min',
        'soc_max': 'max',
    })

    # Cycle estimation: Discharge / Effective Capacity (85% DOD)
    effective_capacity = 860 * 0.85  # approx 731 kWh
    monthly_cycle['cycles'] = monthly_cycle['discharge_kWh'] / effective_capacity

    fig, ax = plt.subplots(figsize=(10, 5))

    month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    x = np.arange(12)

    bars = ax.bar(x, monthly_cycle['cycles'], color='teal', alpha=0.7)
    ax.axhline(y=monthly_cycle['cycles'].mean(), color='red', linestyle='--',
               label=f'Avg: {monthly_cycle["cycles"].mean():.1f} cycles/mo')
    ax.axhline(y=monthly_cycle['cycles'].sum() / 12, color='orange', linestyle=':',
               label=f'Total Annual: {int(monthly_cycle["cycles"].sum())} cycles')

    ax.set_xlabel('Month')
    ax.set_ylabel('Estimated Cycles')
    ax.set_title('Monthly Battery Cycles (Estimated)')
    ax.set_xticks(x)
    ax.set_xticklabels(month_labels)
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    output_file = os.path.join(project_root, png_dir, 'monthly_battery_cycles.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_file}")

    return monthly_cycle

def main(results_dir='results', png_dir='png'):
    df, project_root = load_data(results_dir)
    os.makedirs(os.path.join(project_root, png_dir), exist_ok=True)

    monthly_df = analyze_monthly(df)
    plot_monthly_analysis(monthly_df, png_dir, project_root)

    seasonal_df = analyze_seasonal(df)
    plot_seasonal_analysis(seasonal_df, png_dir, project_root)

    monthly_cycle = plot_monthly_battery_cycle(df, png_dir, project_root)

    return monthly_df, seasonal_df

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', type=int, default=96, help='Prediction horizon steps')
    parser.add_argument('--soc', type=str, default='soc860', help='SOC directory (e.g. soc860)')

    args = parser.parse_args()

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

    main(results_dir=results_dir, png_dir=png_dir)
