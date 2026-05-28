#!/usr/bin/env python3
"""Generate graph showing relationship between battery capacity and contract power / annual cost."""

import matplotlib.pyplot as plt
import matplotlib
import numpy as np

# English font settings
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# Data from JSON result files (annual_cost_comparison.json)
capacity = [0, 215, 430, 540, 645, 860, 1290, 1720]

# Hokkaido Electric Basic Plan (from JSON peak_demand_kW and total)
hokkaido_contract = [262.00, 198.01, 185.50, 179.76, 174.36, 166.83, 157.40, 157.40]
hokkaido_cost = [18101486, 15585445, 14941626, 14731394, 14561085, 14343827, 14074455, 14072576]

# Market-Linked Plan (from JSON peak_demand_kW and total)
market_contract = [262.00, 198.01, 201.40, 211.41, 212.00, 218.05, 221.65, 227.63]
market_cost = [17422732, 14787091, 14613390, 14859816, 14858066, 15023532, 15125066, 15290495]

# Purchased Power [kWh] (from Table 6 and 7)
hokkaido_purchase = [590587, 551647, 535043, 532389, 531536, 531528, 531672, 531553]
market_purchase = [590587, 552550, 535623, 532738, 531684, 531358, 531333, 531135]

# Create graph (3-panel layout)
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))

# Panel 1: Contract power vs Battery capacity
ax1.plot(capacity, hokkaido_contract, 'o-', color='#1f77b4', linewidth=2, markersize=8, label='Hokkaido Electric Basic Plan')
ax1.plot(capacity, market_contract, 's-', color='#ff7f0e', linewidth=2, markersize=8, label='Market-Linked Plan')
ax1.set_xlabel('Battery Capacity [kWh]', fontsize=12)
ax1.set_ylabel('Contract Power [kW]', fontsize=12)
ax1.set_title('Relationship between Battery Capacity and Contract Power', fontsize=14)
ax1.legend(loc='upper right', fontsize=10)
ax1.grid(True, alpha=0.3)
ax1.set_xlim(-50, 1800)
ax1.set_ylim(150, 280)

# Panel 2: Purchased Power vs Battery capacity
ax2.plot(capacity, hokkaido_purchase, 'o-', color='#1f77b4', linewidth=2, markersize=8, label='Hokkaido Electric Basic Plan')
ax2.plot(capacity, market_purchase, 's-', color='#ff7f0e', linewidth=2, markersize=8, label='Market-Linked Plan')
ax2.set_xlabel('Battery Capacity [kWh]', fontsize=12)
ax2.set_ylabel('Purchased Power [kWh]', fontsize=12)
ax2.set_title('Relationship between Battery Capacity and Purchased Power', fontsize=14)
ax2.legend(loc='upper right', fontsize=10)
ax2.grid(True, alpha=0.3)
ax2.set_xlim(-50, 1800)
# Dynamic ylim for clarity
ax2.set_ylim(520000, 600000)

# Panel 3: Annual cost vs Battery capacity
hokkaido_cost_man = [c / 10000 for c in hokkaido_cost]  # in 万円 units
market_cost_man = [c / 10000 for c in market_cost]

ax3.plot(capacity, hokkaido_cost_man, 'o-', color='#1f77b4', linewidth=2, markersize=8, label='Hokkaido Electric Basic Plan')
ax3.plot(capacity, market_cost_man, 's-', color='#ff7f0e', linewidth=2, markersize=8, label='Market-Linked Plan')
ax3.set_xlabel('Battery Capacity [kWh]', fontsize=12)
ax3.set_ylabel('Annual Cost [×10,000 JPY]', fontsize=12)
ax3.set_title('Relationship between Battery Capacity and Annual Cost', fontsize=14)
ax3.legend(loc='upper right', fontsize=10)
ax3.grid(True, alpha=0.3)
ax3.set_xlim(-50, 1800)

# Mark crossover point on Cost graph (ax3)
ax3.axvline(x=430, color='gray', linestyle='--', alpha=0.5)
ax3.annotate('Advantage\nreversal', xy=(430, 1550), xytext=(550, 1650),
             fontsize=9, ha='left',
             arrowprops=dict(arrowstyle='->', color='gray'))

plt.tight_layout()
plt.savefig('/Users/yzhy/Documents/大学関係/2025前期/EMS/png/soc860/capacity_contract_power.png', dpi=150, bbox_inches='tight')
plt.close()

print("✓ Graph saved: png/soc860/capacity_contract_power.png")
