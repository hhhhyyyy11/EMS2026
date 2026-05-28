#!/usr/bin/env python3
"""
Script to generate additional figures for the thesis (English version)

1. Carpet Plot: Annual pattern of SOC and Purchased Power
2. Pareto Frontier: Trade-off between Contract Power and Energy Charge
3. Determinant Identification Plot: Scatter plot of JEPX price vs Charge/Discharge
4. Peak Distribution: Monthly peak power occurrence pattern
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
# try:
#     import japanize_matplotlib
# except ImportError:
#     pass

# Force English fonts
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# Output Directory
OUTPUT_DIR = Path("/Users/yzhy/Documents/大学関係/2025前期/EMS/png/thesis_figures")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Data Directory
RESULTS_DIR = Path("/Users/yzhy/Documents/大学関係/2025前期/EMS/results")

def load_results(capacity: int, plan: str = "market_linked") -> pd.DataFrame:
    """Load simulation results"""
    # Fix path handling if needed, assuming standard structure
    path = RESULTS_DIR / f"soc{capacity}" / f"rolling_results_{plan}.csv"

    if not path.exists():
        # Fallback to simple structure if needed
        path = RESULTS_DIR / f"soc{capacity}" / "rolling_results.csv"

    df = pd.read_csv(path, parse_dates=['timestamp'])
    df['date'] = df['timestamp'].dt.date
    df['hour'] = df['timestamp'].dt.hour + df['timestamp'].dt.minute / 60
    df['month'] = df['timestamp'].dt.month
    df['day_of_year'] = df['timestamp'].dt.dayofyear
    return df


def create_heatmap_carpet_plot():
    """
    Fig 1: Carpet Plot (Heatmap)
    X-axis: Time (0-24h), Y-axis: Date, Color: SOC or Purchased Power
    Comparison between plans
    """
    print("Generating Carpet Plot (Heatmap)...")

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    plans = [
        ("hokkaido_basic", "Hokkaido Electric Basic"),
        ("market_linked", "Market-Linked Plan")
    ]

    for col, (plan, plan_name) in enumerate(plans):
        df = load_results(860, plan)

        # Exclude Feb 29 for leap year handling
        df = df[~((df['timestamp'].dt.month == 2) & (df['timestamp'].dt.day == 29))]

        # SOC Heatmap
        pivot_soc = df.pivot_table(
            values='bF',
            index=df['timestamp'].dt.strftime('%m-%d'),
            columns=df['timestamp'].dt.hour + df['timestamp'].dt.minute/60,
            aggfunc='mean'
        )

        # Purchased Power Heatmap
        pivot_buy = df.pivot_table(
            values='sBY',
            index=df['timestamp'].dt.strftime('%m-%d'),
            columns=df['timestamp'].dt.hour + df['timestamp'].dt.minute/60,
            aggfunc='mean'
        )

        # SOC Plot
        ax1 = axes[0, col]
        im1 = ax1.imshow(pivot_soc.values, aspect='auto', cmap='RdYlBu_r',
                        extent=[0, 24, len(pivot_soc), 0])
        ax1.set_title(f'SOC Transition - {plan_name}', fontsize=12)
        ax1.set_xlabel('Time [h]')
        if col == 0:
            ax1.set_ylabel('Date (Jan -> Dec)')
        cbar1 = plt.colorbar(im1, ax=ax1, label='SOC [kWh]')

        # Y-axis labels by month
        month_positions = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        ax1.set_yticks(month_positions)
        ax1.set_yticklabels(month_labels, fontsize=8)

        # Purchased Power Plot
        ax2 = axes[1, col]
        im2 = ax2.imshow(pivot_buy.values, aspect='auto', cmap='YlOrRd',
                        extent=[0, 24, len(pivot_buy), 0], vmin=0, vmax=250)
        ax2.set_title(f'Purchased Power - {plan_name}', fontsize=12)
        ax2.set_xlabel('Time [h]')
        if col == 0:
            ax2.set_ylabel('Date (Jan -> Dec)')
        cbar2 = plt.colorbar(im2, ax=ax2, label='Purchased Power [kW]')

        ax2.set_yticks(month_positions)
        ax2.set_yticklabels(month_labels, fontsize=8)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "carpet_plot_soc_buy.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {OUTPUT_DIR / 'carpet_plot_soc_buy.png'}")


def create_pareto_frontier():
    """
    Fig 2: Pareto Frontier
    X-axis: Contract Power (Max Purchased Power), Y-axis: Energy Charge
    """
    print("Generating Pareto Frontier...")

    capacities = [0, 215, 430, 540, 645, 860, 1290, 1720]

    fig, ax = plt.subplots(figsize=(10, 8))

    results = {'hokkaido_basic': [], 'market_linked': []}

    for cap in capacities:
        for plan in ['hokkaido_basic', 'market_linked']:
            try:
                df = load_results(cap, plan)
                max_buy = df['sBY'].max()

                # Calculate Energy Charge
                if plan == 'hokkaido_basic':
                    # Fixed price 30.56 JPY/kWh (approx) or actual calculation
                    # Using simple approximate calculation as in original script
                    energy_cost = df['sBY'].sum() * 0.5 * 30.56
                else:
                    # Market linked
                    energy_cost = (df['sBY'] * df['price_yen_per_kWh'] * 0.5).sum()

                results[plan].append({
                    'capacity': cap,
                    'max_buy': max_buy,
                    'energy_cost': energy_cost / 10000  # Convert to 10k JPY
                })
            except Exception as e:
                print(f"  Warning: Could not load {plan} for capacity {cap}: {e}")

    # Plot
    colors = {'hokkaido_basic': '#1f77b4', 'market_linked': '#ff7f0e'}
    labels = {'hokkaido_basic': 'Hokkaido Electric Basic', 'market_linked': 'Market-Linked Plan'}
    markers = {'hokkaido_basic': 'o', 'market_linked': 's'}

    for plan in ['hokkaido_basic', 'market_linked']:
        data = results[plan]
        if data:
            x = [d['max_buy'] for d in data]
            y = [d['energy_cost'] for d in data]
            caps = [d['capacity'] for d in data]

            ax.scatter(x, y, c=colors[plan], marker=markers[plan], s=100,
                      label=labels[plan], zorder=3)
            ax.plot(x, y, c=colors[plan], alpha=0.5, linestyle='--', zorder=2)

            # Add capacity labels
            for xi, yi, cap in zip(x, y, caps):
                ax.annotate(f'{cap}kWh', (xi, yi), textcoords="offset points",
                           xytext=(5, 5), fontsize=8, alpha=0.8)

    ax.set_xlabel('Contract Power (Max Purchased) [kW]', fontsize=12)
    ax.set_ylabel('Energy Charge [10k JPY/Year]', fontsize=12)
    ax.set_title('Pareto Frontier: Trade-off between Contract Power and Energy Charge', fontsize=14)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    # Arrow for optimization direction
    ax.annotate('', xy=(150, 850), xytext=(250, 950),
               arrowprops=dict(arrowstyle='->', color='gray', lw=2))
    ax.text(170, 920, 'Optimization Direction\n(Lower is better)', fontsize=10, color='gray')

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "pareto_frontier.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {OUTPUT_DIR / 'pareto_frontier.png'}")


def create_price_charge_scatter():
    """
    Fig 3: Determinant Identification Plot
    X-axis: JEPX Price, Y-axis: Charge/Discharge amount
    """
    print("Generating Price-Charge Scatter Plot...")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Load market linked plan data
    df = load_results(860, "market_linked")

    # Charge Plot
    ax1 = axes[0]
    charge_mask = df['xFC1'] > 0.1
    scatter1 = ax1.scatter(df.loc[charge_mask, 'price_yen_per_kWh'],
                           df.loc[charge_mask, 'xFC1'],
                           c=df.loc[charge_mask, 'month'], cmap='viridis',
                           alpha=0.3, s=10)
    ax1.set_xlabel('JEPX Price [JPY/kWh]', fontsize=12)
    ax1.set_ylabel('Charge Power [kW]', fontsize=12)
    ax1.set_title('Relation between JEPX Price and Charge', fontsize=14)
    ax1.axvline(x=15, color='red', linestyle='--', alpha=0.5, label='Price Threshold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    cbar1 = plt.colorbar(scatter1, ax=ax1, label='Month')

    # Discharge Plot
    ax2 = axes[1]
    discharge_mask = df['xFD1'] > 0.1
    scatter2 = ax2.scatter(df.loc[discharge_mask, 'price_yen_per_kWh'],
                           df.loc[discharge_mask, 'xFD1'],
                           c=df.loc[discharge_mask, 'month'], cmap='viridis',
                           alpha=0.3, s=10)
    ax2.set_xlabel('JEPX Price [JPY/kWh]', fontsize=12)
    ax2.set_ylabel('Discharge Power [kW]', fontsize=12)
    ax2.set_title('Relation between JEPX Price and Discharge', fontsize=14)
    ax2.axvline(x=20, color='red', linestyle='--', alpha=0.5, label='Price Threshold')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    cbar2 = plt.colorbar(scatter2, ax=ax2, label='Month')

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "price_charge_scatter.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {OUTPUT_DIR / 'price_charge_scatter.png'}")

    # Bar chart by price range
    fig2, axes2 = plt.subplots(1, 2, figsize=(12, 5))

    # Define price bins
    price_bins = [0, 10, 15, 20, 25, 35]
    price_labels = ['0-10', '10-15', '15-20', '20-25', '25+']
    df['price_bin'] = pd.cut(df['price_yen_per_kWh'], bins=price_bins, labels=price_labels)

    # Charge by price bin
    charge_by_price = df.groupby('price_bin', observed=True)['xFC1'].agg(['mean', 'std', 'count'])
    ax3 = axes2[0]
    bars1 = ax3.bar(range(len(price_labels)), charge_by_price['mean'],
                    yerr=charge_by_price['std'], capsize=5, color='steelblue', alpha=0.7)
    ax3.set_xticks(range(len(price_labels)))
    ax3.set_xticklabels([f'{l}\nJPY' for l in price_labels])
    ax3.set_xlabel('JEPX Price Range', fontsize=12)
    ax3.set_ylabel('Avg Charge Power [kW]', fontsize=12)
    ax3.set_title('Avg Charge Power by Price Range', fontsize=14)
    ax3.grid(True, alpha=0.3, axis='y')

    # Discharge by price bin
    discharge_by_price = df.groupby('price_bin', observed=True)['xFD1'].agg(['mean', 'std', 'count'])
    ax4 = axes2[1]
    bars2 = ax4.bar(range(len(price_labels)), discharge_by_price['mean'],
                    yerr=discharge_by_price['std'], capsize=5, color='coral', alpha=0.7)
    ax4.set_xticks(range(len(price_labels)))
    ax4.set_xticklabels([f'{l}\nJPY' for l in price_labels])
    ax4.set_xlabel('JEPX Price Range', fontsize=12)
    ax4.set_ylabel('Avg Discharge Power [kW]', fontsize=12)
    ax4.set_title('Avg Discharge Power by Price Range', fontsize=14)
    ax4.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "price_charge_bar.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {OUTPUT_DIR / 'price_charge_bar.png'}")


def create_peak_distribution():
    """
    Fig 4: Peak Distribution
    Histogram of peak occurrence counts and times by month
    """
    print("Generating Peak Distribution...")

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    plans = [
        ("hokkaido_basic", "Hokkaido Electric Basic"),
        ("market_linked", "Market-Linked Plan")
    ]

    for col, (plan, plan_name) in enumerate(plans):
        df = load_results(860, plan)

        # Identify daily peaks
        daily_peaks = df.groupby('date').apply(
            lambda x: pd.Series({
                'max_buy': x['sBY'].max(),
                'peak_hour': x.loc[x['sBY'].idxmax(), 'hour'],
                'month': x['month'].iloc[0]
            })
        ).reset_index()

        # Treat top 95%ile of daily max as "Peaks"
        threshold = daily_peaks['max_buy'].quantile(0.95)
        peak_days = daily_peaks[daily_peaks['max_buy'] >= threshold]

        # Monthly Peak Count
        ax1 = axes[0, col]
        monthly_peaks = peak_days.groupby('month').size()
        months = range(1, 13)
        peak_counts = [monthly_peaks.get(m, 0) for m in months]

        bars = ax1.bar(months, peak_counts, color='steelblue' if col == 0 else 'coral', alpha=0.7)
        ax1.set_xlabel('Month', fontsize=12)
        ax1.set_ylabel('Peak Occurrence Count', fontsize=12)
        ax1.set_title(f'Monthly Peak Occurrences - {plan_name}\n(Top 5% High Demand Days)', fontsize=12)
        ax1.set_xticks(months)
        ax1.set_xticklabels(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], fontsize=9)
        ax1.grid(True, alpha=0.3, axis='y')

        # Show counts on bars
        for bar, count in zip(bars, peak_counts):
            if count > 0:
                ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                        str(count), ha='center', va='bottom', fontsize=9)

        # Peak Time Distribution
        ax2 = axes[1, col]
        ax2.hist(peak_days['peak_hour'], bins=48, range=(0, 24),
                color='steelblue' if col == 0 else 'coral', alpha=0.7, edgecolor='white')
        ax2.set_xlabel('Time [h]', fontsize=12)
        ax2.set_ylabel('Frequency', fontsize=12)
        ax2.set_title(f'Peak Occurrence Time Distribution - {plan_name}', fontsize=12)
        ax2.set_xlim(0, 24)
        ax2.grid(True, alpha=0.3, axis='y')

        # Highlight key time steps
        if col == 1:  # Market linked
            ax2.axvspan(0, 6, alpha=0.1, color='green', label='Night (Low Price)')
            ax2.axvspan(17, 21, alpha=0.1, color='red', label='Evening Peak')
            ax2.legend(loc='upper right', fontsize=9)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "peak_distribution.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {OUTPUT_DIR / 'peak_distribution.png'}")

    # Comparison of Daily Peak Power
    fig2, ax = plt.subplots(figsize=(12, 6))

    for plan, plan_name, color in [("hokkaido_basic", "Hokkaido Electric Basic", "steelblue"),
                                    ("market_linked", "Market-Linked Plan", "coral")]:
        df = load_results(860, plan)
        daily_max = df.groupby('date')['sBY'].max()
        ax.plot(daily_max.index, daily_max.values, alpha=0.7, label=plan_name, color=color)

    ax.axhline(y=166.83, color='steelblue', linestyle='--', alpha=0.5, label='Hokkaido Contract Power')
    ax.axhline(y=218.05, color='coral', linestyle='--', alpha=0.5, label='Market Contract Power')

    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Daily Max Purchased Power [kW]', fontsize=12)
    ax.set_title('Annual Transition of Daily Max Purchased Power (860kWh)', fontsize=14)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "daily_peak_comparison.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {OUTPUT_DIR / 'daily_peak_comparison.png'}")


def main():
    """Main Function"""
    print("=" * 60)
    print("Generating Thesis Figures (English)")
    print("=" * 60)

    # 1. Heatmap (Carpet Plot)
    create_heatmap_carpet_plot()

    # 2. Pareto Frontier
    create_pareto_frontier()

    # 3. Determinant Identification Plot
    create_price_charge_scatter()

    # 4. Peak Distribution
    create_peak_distribution()

    print("=" * 60)
    print(f"All figures saved in {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
