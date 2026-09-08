"""Separate diagnostic tables, cash provenance and all-scale dual-axis plots."""
from collections import defaultdict
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from matplotlib import font_manager
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1 import run as base
from research.unified_opportunity_risk_v1.analyze import PERIODS,canonical_context
from research.unified_opportunity_risk_v1.exposure_scale.run import HERE,OUT,SCALES,REASONS,label,identity

BENCH_ROOT=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1/qmt_stock_delta')


def export(frame,name):frame.to_csv(OUT/name,index=False)


def cash_provenance(dest,daily):
    attribution=pd.read_parquet(dest/'cash_attribution.parquet')
    assert not attribution.timestamp.duplicated().any()
    bytime=attribution.set_index('timestamp').to_dict('index')
    checks=pd.read_parquet(dest/'checkpoints.parquet').sort_values(['timestamp','checkpoint_id'])
    parts={k:0. for k in REASONS};previous=0.;byday={}
    for row in checks.itertuples():
        cash=max(0.,float(row.cash));delta=cash-previous
        if delta>0:parts['NO_QUALIFYING_OPPORTUNITY']+=delta
        elif previous>0:
            parts={k:v*cash/previous for k,v in parts.items()}
        if row.stage=='UNIFIED_JOINT_FUNDING_COMPLETE':
            allocation=bytime[pd.Timestamp(row.timestamp)]
            assert abs(allocation['cash_after']-cash)<1e-6
            parts={k:allocation[k] for k in REASONS}
        assert abs(sum(parts.values())-cash)<1e-5
        previous=cash;byday[pd.Timestamp(row.timestamp).normalize()]=dict(parts)
    rows=[]
    for row in daily.itertuples():
        values=byday[pd.Timestamp(row.trade_date)]
        assert abs(sum(values.values())-max(0.,row.cash))<1e-5
        rows.append(dict(trade_date=row.trade_date,nav=row.nav,cash=row.cash,**values))
    return pd.DataFrame(rows),attribution


def extra_metrics(dest,start,end):
    d=pd.read_parquet(dest/'daily.parquet');d=d.loc[d.trade_date.between(start,end)]
    gross=d.gross_exposure/d.nav
    return dict(base.metrics(dest,start,end),max_gross=float(gross.max()),days_gross_gt25=int(gross.gt(.25).sum()),days_gross_gt50=int(gross.gt(.5).sum()),
        days_gross_gt75=int(gross.gt(.75).sum()),days_gross_gt90=int(gross.gt(.9).sum()),days_gross_ge99=int(gross.ge(.99).sum()),trading_days=len(d))


def capacity(dest,scale,periods,liquidity,etf):
    a=pd.read_parquet(dest/'admission.parquet');fills=pd.read_parquet(dest/'fills.parquet');buys=fills.loc[fills.side.eq('BUY')].set_index('event_id')
    rows=[]
    for label_,start,end in periods:
        selected=a.loc[a.allocated.gt(0)&a.decision_at.between(start,pd.Timestamp(end)+pd.Timedelta(days=1))]
        for strategy,g in selected.groupby('strategy'):
            ratios=defaultdict(list)
            for r in g.itertuples():
                key=(r.symbol,pd.Timestamp(r.decision_at).normalize())
                if strategy=='SMV6':ratios['order_to_execution_window_volume'].append(float(buys.loc[r.event_id,'quantity'])/etf[key])
                else:
                    info=liquidity.loc[key] if key in liquidity.index else {}
                    for name,col in [('order_to_daily_amount','amount'),('order_to_ADV20','adv20')]:
                        denom=info.get(col,np.nan);ratios[name].append(r.allocated/denom if denom>0 else np.nan)
            for name,values in ratios.items():
                s=pd.Series(values,dtype=float)
                rows.append(dict(scale=scale,period=label_,strategy=strategy,ratio_type=name,orders=len(s),p50=s.quantile(.5),p95=s.quantile(.95),max=s.max(),missing_denominator=int(s.isna().sum()),grade='DESCRIPTIVE_REGISTERED_EXECUTION_FACTS_NO_IMPACT_MODEL'))
    return rows



def hard_defenses():
    rows=[]
    for x in SCALES:
        dest=OUT/'accounts'/label(x);a=pd.read_parquet(dest/'admission.parquet');t=pd.read_parquet(dest/'timeline.parquet').set_index('timestamp')
        highest=0.;count=0
        for when,g in a.loc[a.allocated.gt(0)].groupby('decision_at'):
            state=t.loc[when];top=dict(json.loads(state.top_symbols))
            for symbol in set(g.symbol):
                if symbol in top:
                    ratio=top[symbol]/state.nav;highest=max(highest,ratio)
                    assert ratio<=.1+1e-9,(x,when,symbol,ratio)
                else:
                    # Omitted holdings cannot exceed the smallest of the top 10.
                    assert len(top)==10 and min(top.values())/state.nav<=.1+1e-9
                count+=1
        rows.append(dict(scale=label(x),funded_symbol_timestamp_checks=count,max_newly_funded_security_share_at_timestamp_complete=highest,
                         max_security_share_any_native_timestamp=(t.max_security_exposure/t.nav).max(),status='PASS'))
    export(pd.DataFrame(rows),'hard_defense_audit.csv')


def main():
    from research.scaling_regime_v1.boundary import load_etf
    from research.unified_opportunity_risk_v1.data import OUT as PARENT
    _,minute,_=load_etf('2026-09-04')
    etf={(s,pd.Timestamp(r.trade_date).normalize()):float(r.volume_shares) for s,m in minute.items() for r in m.loc[m.bar_role.eq('OPEN_BAR_09_30')].itertuples()}
    liquidity=pd.read_parquet(PARENT/'liquidity.parquet').set_index(['symbol','trade_date'])
    all_periods=list(PERIODS)+[(str(y),'%d-01-01'%y,'2026-09-04' if y==2026 else '%d-12-31'%y) for y in range(2018,2027)]
    metrics=[];yearly=[];cash=[];paths=[];cap=[];audits=[];population=[]
    baseline=pd.read_parquet(PARENT/'accounts/finalist_evidence/R1_RP100_S10_F1/admission.parquet')
    native_keys=set(zip(baseline.strategy,baseline.symbol,baseline.decision_at))
    for x in SCALES:
        tag=label(x);dest=OUT/'accounts'/tag;receipt=json.loads((dest/'receipt.json').read_text())
        assert receipt['identity']==identity()
        for name,digest in receipt['hashes'].items():assert repair.digest(dest/name)==digest
        d=pd.read_parquet(dest/'daily.parquet');d.trade_date=pd.to_datetime(d.trade_date)
        a=pd.read_parquet(dest/'admission.parquet');checks=pd.read_parquet(dest/'checkpoints.parquet')
        assert checks.cash.ge(-1e-8).all() and checks.gross_exposure.le(checks.nav+1e-8).all()
        assert checks.pnl_delta.abs().max()<1e-6
        assert a.loc[a.allocated.gt(0),'R1'].gt(0).all()
        if x==1.:
            original=PARENT/'accounts/finalist_evidence/R1_RP100_S10_F1'
            old=pd.read_parquet(original/'daily.parquet');new=d.copy()
            for df in [old,new]:df['callback_state_json']=df.callback_state_json.map(canonical_context)
            pd.testing.assert_frame_equal(old,new,check_exact=True)
            pd.testing.assert_frame_equal(pd.read_parquet(original/'fills.parquet'),pd.read_parquet(dest/'fills.parquet'),check_exact=True)
            assert json.loads((original/'account.json').read_text())==json.loads((dest/'account.json').read_text())
        ledger,clock=cash_provenance(dest,d)
        export(ledger,f'{tag}_daily_cash_provenance.csv.gz');export(clock,f'{tag}_decision_cash_waterfall.csv.gz')
        for name,start,end in all_periods:
            m=dict(scale=tag,period=name,**extra_metrics(dest,start,end))
            (metrics if name in {p[0] for p in PERIODS} else yearly).append(m)
            g=ledger.loc[ledger.trade_date.between(start,end)]
            events=clock.loc[clock.timestamp.between(start,pd.Timestamp(end)+pd.Timedelta(days=1))]
            for reason in REASONS:
                cash.append(dict(scale=tag,period=name,reason=reason,average_cash_NAV_share=(g[reason]/g.nav).mean(),
                    share_of_unused_cash_NAV_days=(g[reason]/g.nav).sum()/(g.cash/g.nav).sum(),cash_currency_days=g[reason].sum(),
                    negative_interaction_days=int(g[reason].lt(-1e-6).sum()),decision_waterfall_sum=events[reason].sum(),
                    decision_count_positive=int(events[reason].gt(1e-6).sum()),method='EXCLUSIVE_SIGNED_SNAPSHOT_WATERFALL_WITH_CASH_PROVENANCE; ORDER_DEPENDENT_NOT_SHAPLEY'))
        cap+=capacity(dest,tag,all_periods,liquidity,etf)
        for strategy,g in a.groupby('strategy'):
            keys=set(zip(g.strategy,g.symbol,g.decision_at));oldkeys={k for k in native_keys if k[0]==strategy}
            population.append(dict(scale=tag,strategy=strategy,upstream_request_count=len(g),qualifying_requests=int((g.R1.gt(0)&~g.reason.isin(['ECONOMIC_DUPLICATE','QUALITY_NONPOSITIVE','ACTIVE_SYMBOL','MAX_K','DAILY_CAP'])).sum()),funded_requests=int(g.allocated.gt(0).sum()),state_dependent_request_keys_added=len(keys-oldkeys),state_dependent_request_keys_absent=len(oldkeys-keys),producer_rules='UNCHANGED'))
        paths.append(d.assign(scale=tag,nav_multiple=d.nav/float(receipt.get('initial_cash',json.loads((dest/'account.json').read_text())['initial_cash'])),gross=d.gross_exposure/d.nav)[['scale','trade_date','nav','cash','gross_exposure','nav_multiple','gross']])
        audits.append(dict(scale=tag,days=len(d),min_cash=checks.cash.min(),max_gross=(checks.gross_exposure/checks.nav).max(),max_pnl_delta=checks.pnl_delta.abs().max(),X1_parity='EXACT' if x==1. else 'NOT_BASELINE',status='PASS'))
    export(pd.DataFrame(metrics),'candidate_b_exposure_scale_metrics.csv');export(pd.DataFrame(yearly),'candidate_b_exposure_scale_yearly.csv')
    export(pd.DataFrame(cash),'candidate_b_unused_cash_attribution.csv');export(pd.DataFrame(cap),'candidate_b_exposure_scale_capacity.csv')
    export(pd.DataFrame(audits),'account_validation.csv');export(pd.DataFrame(population),'opportunity_population_audit.csv')
    curves=pd.concat(paths,ignore_index=True);export(curves,'candidate_b_exposure_scale_daily.csv.gz')
    benchmarks=[];bindings={}
    for symbol,name in [('000001.SH','SSE Composite'),('399001.SZ','SZSE Component')]:
        file=BENCH_ROOT/f'{symbol}_1d.parquet';b=pd.read_parquet(file);b=b.loc[b.trade_date.between('2018-01-01','2026-09-04')].sort_values('trade_date')
        assert pd.DatetimeIndex(b.trade_date).equals(pd.DatetimeIndex(paths[0].trade_date))
        assert b.close.gt(0).all();b['normalized_100']=b.close/b.close.iloc[0]*100
        benchmarks.append(b.assign(benchmark=name)[['benchmark','trade_date','close','normalized_100']]);bindings[str(file)]=repair.digest(file)
    benchmark=pd.concat(benchmarks,ignore_index=True);export(benchmark,'benchmark_prices.csv')
    repair.write_json(OUT/'benchmark_manifest.json',dict(source_hashes=bindings,scope='DISPLAY_ONLY_NO_ALPHA_INPUT',normalization='2018-01-02 close = 100',last_included='2026-09-04'))
    hard_defenses()
    plot(curves,benchmark)
    print('8 ACCOUNTS / 48 PERIOD METRICS / 72 YEARLY ROWS; X1 EXACT PARITY')


def plot(curves,benchmark):
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family':'Arial Unicode MS','font.size':11,'axes.spines.top':False})
    colors=['#264653','#2a9d8f','#57a773','#e9c46a','#f4a261','#e76f51','#9b5de5','#111111']
    for metric,title,ylabel,name in [('nav_multiple','Candidate B：仓位倍数响应曲线与市场指数','账户净值（继承的初始账户权益 = 1）','nav'),('drawdown','Candidate B：全部仓位倍数的实际回撤','相对历史高点的回撤','drawdown'),('gross','Candidate B：全部仓位倍数的实际总仓位','多头市值 / NAV','gross')]:
        fig,ax=plt.subplots(figsize=(17,8.5));lines=[]
        for x,color in zip(SCALES,colors):
            g=curves.loc[curves.scale.eq(label(x))];values=g.nav_multiple.to_numpy()
            y=values if metric=='nav_multiple' else values/np.maximum.accumulate(np.r_[1.,values])[1:]-1 if metric=='drawdown' else g.gross.to_numpy()
            lines+=ax.plot(g.trade_date,y,label=label(x),color=color,lw=2 if x in [1.,'MAX_FILL'] else 1.35,alpha=.95)
        ax.set(title=title,ylabel=ylabel,xlim=(pd.Timestamp('2018-01-01'),pd.Timestamp('2026-09-04')));ax.grid(alpha=.18)
        if metric=='nav_multiple':
            right=ax.twinx();right.set_ylabel('指数：首日收盘 = 100（右轴独立刻度）',color='#586174')
            for name_,color,style in [('SSE Composite','#457b9d','--'),('SZSE Component','#d45087',':')]:
                b=benchmark.loc[benchmark.benchmark.eq(name_)];lines+=right.plot(b.trade_date,b.normalized_100,label={'SSE Composite':'上证指数（右轴）','SZSE Component':'深证成指（右轴）'}[name_],color=color,lw=1.8,ls=style,alpha=.75)
            right.grid(False)
        else:ax.yaxis.set_major_formatter(PercentFormatter(1.))
        ax.legend(lines,[line.get_label() for line in lines],loc='upper center',bbox_to_anchor=(.5,-.085),ncol=5,frameon=False)
        fig.suptitle('2018—2026-09-04 | 连续物理账户 | 2024年起为事后诊断 | KEEP_NATIVE 不变',y=.97,fontsize=10,color='#555')
        fig.subplots_adjust(bottom=.19,top=.91,left=.07,right=.91)
        fig.savefig(OUT/f'candidate_b_exposure_scale_{name}.png',dpi=170);plt.close(fig)

if __name__=='__main__':main()
