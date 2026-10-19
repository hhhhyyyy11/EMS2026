"""Figure 1: compare saved LP, DP37 and DP73 trajectories on the shared day."""
from pathlib import Path
import csv
import hashlib
import json
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/ems-mpl-1016')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
INTRO='LP・DP37点・DP73点の1日・7日・30日計画から，共通する2025年7月22日の運用を取り出した．各条件の1回目の保存済み結果を用いた．30日計画のDP73点は4回とも時間切れであり，運用図には表示していない．'
CAPTION='最適化期間別の7月22日の運用（30分刻み）．上段は需要・利用可能PV・各手法の買電，中段は外部側の充放電（充電を正，放電を負），下段はSOCを示す．電力は各区間の平均値を区間中央に置き，折れ線で結んだ．30日計画のDP73点は時間切れのため欠測とした．'


def main():
    plt.rcParams.update({'font.family':'Hiragino Sans', 'font.size':11, 'axes.unicode_minus':False})
    runs=[json.loads(s) for s in (ROOT/'experiments/R1008_recompute/runs.jsonl').read_text().splitlines()]
    fig, axes=plt.subplots(3,3,figsize=(11,8),sharex=True,sharey='row')
    edges=np.arange(49)*.5
    x=edges[:-1]+.25
    provenance=[]
    inputs=[]
    specs=(('lp',None,'LP','#0072b2','-'),('dp',37,'DP37','#aa4499','--'),('dp',73,'DP73','#009e73','-.'))
    for col,(scenario,days) in enumerate((('period_day',1),('period_week',7),('period_month',30))):
        axes[0,col].set_title(f'最適化期間：{days}日',fontsize=12,pad=10)
        for method,grid,label,color,style in specs:
            group=[r for r in runs if (r['scenario'],r['method'],r['grid_count'])==(scenario,method,grid)]
            assert len(group)==4
            run=next(r for r in group if r['replicate']==0)
            if run['status']!='success':
                assert all(r['status']=='time_limit' for r in group)
                axes[2,col].text(.98,.96,f'{label}：時間切れ',ha='right',va='top',transform=axes[2,col].transAxes,fontsize=9,color=color)
                provenance.append({'scenario':scenario,'method':label,'status':'time_limit','successful_runs':0,'attempted_runs':4})
                continue
            folder=Path(run['result_directory'])
            assert json.loads((folder/'evaluation.json').read_text())['status']=='pass'
            with (folder/'trajectory.csv').open(encoding='utf-8-sig') as f:
                data=list(csv.DictReader(f))
            assert len(data)==days*48
            data=data[:48]
            assert all(r['timestamp'].startswith('2025-07-22T') for r in data)
            v=lambda key:np.array([float(r[key]) for r in data])
            load,pv=v('load_kW'),v('pv_available_kW')
            inputs.append(np.c_[load,pv])
            if method=='lp':
                axes[0,col].plot(x,load,color='#454545',lw=1.2,label='需要')
                axes[0,col].plot(x,pv,color='#d99800',lw=1.2,label='利用可能PV')
            axes[0,col].plot(x,v('purchased_power_kW'),color=color,ls=style,lw=1.5,label=label)
            net=v('charge_power_kW_internal')/.98-v('discharge_power_kW_internal')*.98
            axes[1,col].plot(x,net,color=color,ls=style,lw=1.5)
            soc=np.r_[v('soc_start_kWh'),float(data[-1]['soc_end_kWh'])]/860*100
            assert np.isclose(soc[0],50)
            axes[2,col].plot(edges,soc,color=color,ls=style,lw=1.5)
            provenance.append({'scenario':scenario,'method':label,'run_id':run['run_id'],'result_directory':str(folder),'trajectory_sha256':hashlib.sha256((folder/'trajectory.csv').read_bytes()).hexdigest(),'evaluation':'pass'})
        axes[1,col].axhline(0,color='#999',lw=.6)
        axes[2,col].axhline(50,color='#aaa',lw=.6,ls=':')
        axes[2,col].set_ylim(0,100)
        axes[2,col].set_xlabel('7月22日の時刻 [時]')
    assert len(inputs)==8 and all(np.array_equal(inputs[0],a) for a in inputs[1:])
    for row,label in enumerate(('電力 [kW]','充電 + / 放電 − [kW]','SOC [%]')):
        axes[row,0].set_ylabel(label)
        for ax in axes[row]:
            ax.set_xlim(0,24)
            ax.set_xticks([0,6,12,18,24])
            ax.grid(alpha=.18)
            ax.spines[['top','right']].set_visible(False)
    handles,labels=axes[0,0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='upper center',ncol=5,frameon=False,bbox_to_anchor=(.53,1),fontsize=11)
    fig.tight_layout(rect=(0,0,1,.95),pad=1.3,w_pad=1,h_pad=1.3)
    fig.savefig(ROOT/'figures/R1016_daily_operation.png',dpi=230,facecolor='white')
    (ROOT/'experiments/R1016_operation/methods_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    report=ROOT.parent/'reports/progress_report_1016.tex'
    text=report.read_text()
    start=text.index('\\section{最適化期間による1日の運用の違い}')
    first_figure=text.index('\\begin{figure}',start)
    heading='\\section{最適化期間による1日の運用の違い}'
    text=text[:start]+heading+'\n'+INTRO+'\n\n'+text[first_figure:]
    figure_end=text.index('\\end{figure}',start)
    caption_start=text.index('\\caption{',start)
    caption_end=text.index('\n',caption_start)
    assert caption_start<figure_end
    text=text[:caption_start]+'\\caption{'+CAPTION+'}'+text[caption_end:]
    # The unchanged numeric table below the figure still refers to LP only.
    text=text.replace('\\caption{7月22日の最大買電と24時のSOC}', '\\caption{7月22日の最大買電と24時のSOC（LP）}')
    report.write_text(text)
    print('Figure 1: 8 independently evaluated trajectories; 30-day DP73 marked as timeout.')


if __name__=='__main__':
    main()
