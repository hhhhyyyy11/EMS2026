#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Price seasonal analysis script (English version)
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import argparse
import os
import json

# English font settings
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.unicode_minus'] = False

HOKKAIDO_PRICE = 21.51  # JPY/kWh

def load_data(results_dir):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    csv_path = os.path.join(project_root, results_dir, 'rolling_results.csv')

    print(f"Loading data from: {csv_path}")
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['month'] = df['timestamp'].dt.month
    df['hour'] = df['timestamp'].dt.hour

    # 3-5: Spring, 6-8: Summer, 9-11: Autumn, 12-2: Winter
    def get_season(month):
        if 3 <= month <= 5: return 'Spring'
        elif 6 <= month <= 8: return 'Summer'
        elif 9 <= month <= 11: return 'Autumn'
        else: return 'Winter'

    df['season'] = df['month'].apply(get_season)

    return df, project_root

def analyze_monthly_price(df):
    monthly_stats = df.groupby('month')['price_yen_per_kWh'].agg(['mean', 'std', 'min', 'max'])

    # Check rate above Hokkaido price
    def above_hokkaido_rate(x):
        return (x > HOKKAIDO_PRICE).sum() / len(x) * 100

    above_rates = df.groupby('month')['price_yen_per_kWh'].apply(above_hokkaido_rate)
    monthly_stats['above_hokkaido_rate'] = above_rates

    monthly_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    monthly_stats['month_name'] = monthly_names

    return monthly_stats

def analyze_seasonal_price(df):
    seasonal_stats = df.groupby('season')['price_yen_per_kWh'].agg(['mean', 'std', 'min', 'max'])
    return seasonal_stats

def analyze_hourly_price_pattern(df):
    hourly_stats = df.groupby('hour')['price_yen_per_kWh'].agg(['mean', 'std', 'min', 'max'])
    return hourly_stats

def plot_price_analysis(df, monthly_df, seasonal_df, hourly_stats, png_dir, project_root):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Monthly Mean Price vs Hokkaido
    ax1 = axes[0, 0]
    months = range(1, 13)
    month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    bars = ax1.bar(months, monthly_df['mean'], color='steelblue', alpha=0.7, label='Market Price (Mean)')
    ax1.axhline(y=HOKKAIDO_PRICE, color='red', linestyle='--', linewidth=2, label=f'Hokkaido Electric ({HOKKAIDO_PRICE} JPY/kWh)')
    ax1.errorbar(months, monthly_df['mean'], yerr=monthly_df['std'], fmt='none', color='black', capsize=3, label='Std Dev')

    ax1.set_xlabel('Month')
    ax1.set_ylabel('Electricity Price [JPY/kWh]')
    ax1.set_title('Monthly Market Price vs Hokkaido Plan')
    ax1.set_xticks(months)
    ax1.set_xticklabels(month_labels, rotation=45)
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, monthly_df['mean'].max() * 1.5)

    # 2. Hourly Price Pattern
    ax2 = axes[0, 1]
    hours = range(24)
    ax2.fill_between(hours, hourly_stats['mean'] - hourly_stats['std'],
                     hourly_stats['mean'] + hourly_stats['std'], alpha=0.3, color='steelblue')
    ax2.plot(hours, hourly_stats['mean'], color='steelblue', linewidth=2, label='Market Price (Mean +/- Std)')
    ax2.axhline(y=HOKKAIDO_PRICE, color='red', linestyle='--', linewidth=2, label=f'Hokkaido ({HOKKAIDO_PRICE} JPY)')

    ax2.set_xlabel('Time [h]')
    ax2.set_ylabel('Electricity Price [JPY/kWh]')
    ax2.set_title('Hourly Price Pattern')
    ax2.set_xticks(range(0, 24, 2))
    ax2.set_xticklabels([f'{h}:00' for h in range(0, 24, 2)], rotation=45)
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)

    # 3. Seasonal Distribution (Box Plot)
    ax3 = axes[1, 0]
    seasons = ['Spring', 'Summer', 'Autumn', 'Winter']
    season_data = [df[df['season'] == s]['price_yen_per_kWh'].values for s in seasons]

    bp = ax3.boxplot(season_data, labels=seasons, patch_artist=True)
    colors = ['lightgreen', 'lightyellow', 'lightcoral', 'lightblue']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)

    ax3.axhline(y=HOKKAIDO_PRICE, color='red', linestyle='--', linewidth=2, label=f'Hokkaido')

    ax3.set_xlabel('Season')
    ax3.set_ylabel('Price [JPY/kWh]')
    ax3.set_title('Seasonal Price Distribution')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)

    # 4. Rate of Price > Hokkaido
    ax4 = axes[1, 1]
    colors = ['green' if rate < 50 else 'orange' if rate < 70 else 'red' for rate in monthly_df['above_hokkaido_rate']]
    bars = ax4.bar(months, monthly_df['above_hokkaido_rate'], color=colors, alpha=0.7)

    ax4.set_xlabel('Month')
    ax4.set_ylabel('Rate [%]')
    ax4.set_title('Frequency of Market Price > Hokkaido Plan')
    ax4.set_xticks(months)
    ax4.set_xticklabels(month_labels, rotation=45)
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim(0, 100)

    annual_rate = (df['price_yen_per_kWh'] > HOKKAIDO_PRICE).sum() / len(df) * 100
    ax4.axhline(y=annual_rate, color='red', linestyle='--', linewidth=2, label=f'Annual Avg: {annual_rate:.1f}%')
    ax4.legend()

    plt.tight_layout()
    output_file = os.path.join(project_root, png_dir, 'price_seasonal_analysis.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_file}")


def plot_price_histogram(df, png_dir, project_root):
    fig, ax = plt.subplots(figsize=(10, 6))
    prices = df['price_yen_per_kWh']

    n, bins, patches = ax.hist(prices, bins=50, color='steelblue', alpha=0.7, edgecolor='black')

    ax.axvline(x=HOKKAIDO_PRICE, color='red', linestyle='--', linewidth=2,
               label=f'Hokkaido Plan ({HOKKAIDO_PRICE} JPY/kWh)')
    ax.axvline(x=prices.mean(), color='orange', linestyle='-', linewidth=2,
               label=f'Market Mean ({prices.mean():.2f} JPY/kWh)')

    ax.set_xlabel('Price [JPY/kWh]')
    ax.set_ylabel('Frequency (30-min slots)')
    ax.set_title('Distribution of JEPX Spot Prices (2024)')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    output_file = os.path.join(project_root, png_dir, 'price_histogram.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_file}")


def main(results_dir='results', png_dir='png'):
    df, project_root = load_data(results_dir)
    os.makedirs(os.path.join(project_root, png_dir), exist_ok=True)

    monthly_df = analyze_monthly_price(df)
    seasonal_df = analyze_seasonal_price(df)
    hourly_stats = analyze_hourly_price_pattern(df)

    plot_price_analysis(df, monthly_df, seasonal_df, hourly_stats, png_dir, project_root)
    plot_price_histogram(df, png_dir, project_root)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', type=int, default=96)
    parser.add_argument('--soc', type=str, default='soc860')
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
