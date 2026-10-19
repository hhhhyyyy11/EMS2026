"""Plot the shared first day of the 30/60-minute three-day LP solutions."""
from pathlib import Path
import csv
import json
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/ems-mpl-1016')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def main():
    plt.rcParams.update({'font.family':'Hiragino Sans','font.size':11,'axes.unicode_minus':False})
    rows=[json.loads(s) for s in (ROOT/'experiments/R1016_three_days/runs.jsonl').read_text().splitlines()]
    fig,axes=plt.subplots(3,2,figsize=(9,8),sharex=True,sharey='row')
    for col,(scenario,minutes) in enumerate((('three_days_30min',30),('three_days_60min',60))):
        run=next(r for r in rows if r['scenario']==scenario and r['method']=='lp' and r['replicate']==0)
        assert run['status']=='success' and run['evaluation_status']=='pass'
        with (Path(run['result_directory'])/'trajectory.csv').open(encoding='utf-8-sig') as f:
            data=list(csv.DictReader(f))[:int(24*60/minutes)]
        dt=minutes/60
        edges=np.arange(len(data)+1)*dt
        x=edges[:-1]+dt/2
        v=lambda key: np.array([float(r[key]) for r in data])
        for key,label,color in [('load_kW','需要','#303b48'),('pv_available_kW','利用可能PV','#d99800'),('purchased_power_kW','買電','#0072b2')]:
            axes[0,col].plot(x,v(key),color=color,label=label,lw=1.4)
        axes[0,col].set_title(f'最適化期間：3日（{minutes}分間隔）',fontsize=12,pad=10)
        axes[1,col].plot(x,v('charge_power_kW_internal')/.98,label='充電（外部側）',color='#009e73',lw=1.5)
        axes[1,col].plot(x,-v('discharge_power_kW_internal')*.98,label='放電（外部側）',color='#cc6677',lw=1.5)
        axes[1,col].axhline(0,color='#888',lw=.5)
        soc=np.r_[v('soc_start_kWh'),float(data[-1]['soc_end_kWh'])]/860*100
        axes[2,col].plot(edges,soc,label='SOC',color='#0072b2',lw=1.7)
        axes[2,col].axhline(50,color='#999',ls='--',lw=.8,label='初期SOC 50%')
        axes[2,col].set_ylim(0,100)
        axes[2,col].set_xlabel('7月22日の時刻 [時]')
    for row,label in enumerate(('電力 [kW]','充電 + / 放電 − [kW]','SOC [%]')):
        axes[row,0].set_ylabel(label)
        axes[row,0].legend(loc='upper right' if row<2 else 'upper left',fontsize=8,framealpha=.9)
        for ax in axes[row]:
            ax.set_xlim(0,24)
            ax.set_xticks([0,6,12,18,24])
            ax.grid(alpha=.18)
            ax.spines[['top','right']].set_visible(False)
    fig.tight_layout(pad=1.4,w_pad=1.2,h_pad=1.4)
    path=ROOT/'figures/R1016_three_day_operation.png'
    fig.savefig(path,dpi=230,facecolor='white')
    print(path)


if __name__=='__main__':
    main()
