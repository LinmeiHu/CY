"""Separately label segmented comparators, legacy differences and new Top plot."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .audit import HERE,ROOT,PARENT,ROLL,write_json
from .accounts import END,folder
from .economics import require_identity,annual,read,KEY


def segmented():
    require_identity();rows=[]
    for gap in ['OGR','IFCGR']:
        for mode in ['independent','confirmation_tag']:
            new=folder(gap,mode,'NATIVE','FULL_BOOK_NORMALIZATION',END)
            cont,a,_,_=read(new,observations=False)
            old=ROOT/'research/shared_capital_v1/cache/scenarios'/gap/'2022_2023'/mode/'P0'
            # Shared-study names are different; the comparison needs the daily
            # ledger and explicit initial states, never chained annual returns.
            seg=pd.read_parquet(old/'daily.parquet').sort_values('trade_date').reset_index(drop=True)
            opening={s:json.loads((ROOT/'research/shared_capital_v1/output'/f'{s.lower()}_initial_state_2022.json').read_text())['nav'] for s in ['ATRDR','MCB',gap,'SMV6']}
            for year in [2022,2023]:
                c=cont.loc[cont.trade_date.dt.year.eq(year)]
                p=seg.loc[seg.trade_date.dt.year.eq(year)]
                cprev=cont.loc[cont.trade_date.lt(c.trade_date.iloc[0])].iloc[-1]
                earlier=seg.loc[seg.trade_date.lt(p.trade_date.iloc[0])]
                pprev=earlier.iloc[-1] if len(earlier) else None
                component={}
                for s in opening:
                    cn=float(c[s+'_nav'].iloc[-1]-cprev[s+'_nav'])
                    sn=float(p[s+'_nav'].iloc[-1]-(pprev[s+'_nav'] if pprev is not None else opening[s]))
                    component[s]=dict(continuous_pnl=cn,segmented_pnl=sn,pnl_difference=cn-sn,opening_nav_difference=float(cprev[s+'_nav']-(pprev[s+'_nav'] if pprev is not None else opening[s])))
                copen=float(cprev.nav);popen=float(pprev.nav) if pprev is not None else sum(opening.values())
                cpnl=float(c.nav.iloc[-1]-copen);spnl=float(p.nav.iloc[-1]-popen)
                assert abs(sum(v['pnl_difference'] for v in component.values())-(cpnl-spnl))<1e-5
                rows.append(dict(gap=gap,mcb_mode=mode,year=year,continuous_opening_nav=copen,segmented_opening_nav=popen,
                    initial_state_carry=copen-popen,continuous_pnl=cpnl,segmented_pnl=spnl,pnl_difference=cpnl-spnl,
                    continuous_return=float(c.nav.iloc[-1]/copen-1),segmented_return=float(p.nav.iloc[-1]/popen-1),
                    SMV6_state_pnl_difference=component['SMV6']['pnl_difference'],other_strategy_pnl_difference=sum(v['pnl_difference'] for k,v in component.items() if k!='SMV6'),
                    MCB_snapshot_predicate='No candidate-set change in 2022/2023; separately verified original guard',
                    fees_difference=float(c.fees.iloc[-1]-cprev.fees-(p.fees.iloc[-1]-(pprev.fees if pprev is not None else 0))),
                    positions_difference_cny=float(c.gross_exposure.iloc[-1]-p.gross_exposure.iloc[-1]),
                    strategy_components=json.dumps(component,sort_keys=True),
                    interpretation='Opening NAV difference plus annual P&L difference equals end NAV difference; fees already inside P&L, exposure is a state not another additive cause'))
    pd.DataFrame(rows).to_csv(HERE/'output/segmented_vs_continuous_2022_2023.csv',index=False)


def legacy():
    require_identity();rows=[]
    top=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
    for r in top.itertuples():
        identity=dict(gap=r.gap,mcb_mode=r.mcb_mode,target=r.target,mechanic='FULL_BOOK_NORMALIZATION')
        actual=folder(r.gap,r.mcb_mode,r.target,'FULL_BOOK_NORMALIZATION',END)
        old=ROLL/'combinations'/f'{r.gap}_{r.mcb_mode}_{r.target}'
        a=pd.DataFrame(annual(actual,identity));b=pd.DataFrame(annual(old,identity))
        joined=a.merge(b,on=KEY+['year'],suffixes=('_authoritative','_legacy'))
        for y in joined.itertuples():
            row=dict(rank=r.rank,**identity,year=y.year,authoritative_return=y.annual_return_authoritative,legacy_return=y.annual_return_legacy,
                authoritative_MaxDD=y.MaxDD_authoritative,legacy_MaxDD=y.MaxDD_legacy,
                annual_pnl_difference=y.net_pnl_authoritative-y.net_pnl_legacy,
                opening_nav_difference=y.opening_nav_authoritative-y.opening_nav_legacy,
                ending_nav_difference=y.closing_nav_authoritative-y.closing_nav_legacy,
                fee_difference=y.fees_authoritative-y.fees_legacy,
                SMV6_boundary_protocol='SAME_CONTINUOUS_CARRY; zero protocol change relative to legacy',
                MCB_snapshot_qualification='Restored original guard; candidate equivalence separately proven, no qualification-only signal change',
                other_runtime='Original industry taxonomy restored after 2026-08-13; same source changes ATRDR candidates',
                account_state_compounding='Exact opening/ending NAV bridge reported; not isolated as an independent cause',
                scaling_path='Actual corrected Native reference and actual scaled feedback; coupled response to changed industry inputs',
                causal_attribution_status='JOINT_CONTROLLED_INPUT_REPAIR; no arbitrary split of interacting path effects')
            assert abs(row['ending_nav_difference']-row['opening_nav_difference']-row['annual_pnl_difference'])<1e-5
            if y.year<2026:assert abs(row['ending_nav_difference'])<1e-5,'Unexpected pre-taxonomy legacy difference'
            rows.append(row)
    pd.DataFrame(rows).to_csv(HERE/'output/legacy_vs_authoritative_rollforward.csv',index=False)


def plot():
    require_identity()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
    fig,axes=plt.subplots(2,1,figsize=(13,8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    top=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
    for r in top.itertuples():
        path=folder(r.gap,r.mcb_mode,r.target,'FULL_BOOK_NORMALIZATION',END)
        d,a,_,_=read(path,observations=False)
        label=f'#{r.rank} {r.gap} / {r.mcb_mode} / {r.target}'
        axes[0].plot(d.trade_date,d.nav/a['initial_cash'],label=label,lw=1.5)
        axes[1].plot(d.trade_date,100*(d.nav/d.nav.cummax().clip(lower=a['initial_cash'])-1),lw=1)
    axes[0].set_title('AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1\n2018-01-01 to 2026-09-04 | Historical 2018-2021 Top selection retained',loc='left',fontsize=14,pad=14)
    axes[0].set_ylabel('NAV / actual initial NAV');axes[1].set_ylabel('Drawdown (%)');axes[1].set_xlabel('Trading date')
    for ax in axes:
        ax.grid(alpha=.18);ax.spines[['top','right']].set_visible(False)
        ax.axvline(pd.Timestamp('2022-01-01'),color='#666666',ls=':',lw=.8)
        ax.axvline(pd.Timestamp('2024-01-01'),color='#666666',ls=':',lw=.8)
    axes[0].legend(loc='upper left',fontsize=9)
    fig.text(.08,.01,'Actual continuous accounts. 2026 is YTD. Post-hoc diagnostic; no new sealed validation.',fontsize=9,color='#555555')
    fig.tight_layout(rect=(0,.025,1,1))
    path=HERE/'reports/top5_authoritative_continuous_protocol_v1.png';fig.savefig(path,dpi=180);plt.close(fig)
    return path


if __name__=='__main__':segmented();legacy();plot()
