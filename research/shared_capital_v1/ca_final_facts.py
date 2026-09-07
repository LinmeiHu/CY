"""Extract reviewed official date tables and exercise isolated held-lot transitions."""
import json,re
from copy import deepcopy
from pathlib import Path
import duckdb
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE,sha256
from research.shared_capital_v1.shared_account.engine import PhysicalAccount,Intent
from research.shared_capital_v1.shared_account.price_space import raw_intent
from research.shared_capital_v1.shared_account.corporate_actions import ShareConversion,CashDistribution


def run():
    manifest=json.loads((HERE/'manifests/corporate_action_official_backfill_v1.json').read_text())
    config=json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    con=duckdb.connect();facts=[]
    for doc in manifest['documents']:
        if 'raw_path' not in doc:raise ValueError('official document unresolved')
        if sha256(doc['raw_path'])!=doc['source_hash']:raise ValueError('official document hash changed')
        if sha256(doc['text_path'])!=doc['text_sha256']:raise ValueError('official extraction hash changed')
        t=Path(doc['text_path']).read_text()
        dates=[str(pd.Timestamp(x).date()) for x in re.findall(r'20\d\d/\d{1,2}/\d{1,2}',t[:1600])]
        registered=con.execute('SELECT * FROM read_parquet(?) WHERE symbol=? AND effective_date=?::DATE',[config['qd010_distributions'],doc['symbol'],doc['ex_date']]).fetchdf()
        if len(registered)!=1 or len(dates)<3:raise ValueError('ambiguous official date extraction')
        r=registered.iloc[0]
        if dates[:2] != [str(r.record_date.date()),doc['ex_date']]:raise ValueError('official vs registered date conflict')
        cash=float(r.cash_per_share_gross); ratio=float(r.share_multiplier)-1
        if cash and (len(dates)<4 or dates[3]!=str(r.pay_date.date())):raise ValueError('official payment date conflict')
        facts.append(dict(symbol=doc['symbol']+'.SH',action_id=r.event_id,action_type=r.event_type,
            announcement_date=doc['document_date'],record_date=dates[0],ex_date=dates[1],tradable_date=dates[2],
            accounting_effective_date=dates[1],accounting_semantics='Economic pending entitlement on evidenced ex-date; not an assertion of broker credit timestamp',
            share_credit_date=None,cash_payment_date=dates[3] if cash else None,
            share_ratio=ratio,cash_ratio=cash,ratio_source='registered official p_sysapi1139; primary purpose of backfill is explicit listing/payment date',
            source_url=doc['source_url'],source_grade=doc['source_grade'],raw_hash=doc['source_hash'],retrieved_at=doc['retrieved_at'],
            historical_announcement_available_at=str(r.known_at),available_at=doc['retrieved_at'],
            status='OFFICIAL_EXECUTION_DATES_VERIFIED_ACCOUNT_INTEGRATION_PENDING',alpha_use='PROHIBITED'))
    facts=pd.DataFrame(facts);facts.to_csv(HERE/'output/corporate_action_official_backfill_facts.csv',index=False)
    audit=pd.read_csv(HERE/'output/corporate_action_execution_completeness.csv',dtype={'accounting_effective_date':object,'tradable_date':object})
    for i,r in audit.iterrows():
        f=facts.loc[facts.action_id.eq(r.action_id)]
        if not f.empty:
            f=f.iloc[0]
            for field in ['accounting_effective_date','tradable_date','cash_payment_date','source_grade','available_at','raw_hash']:
                audit.loc[i,field]=f[field]
            audit.loc[i,'source']=f.source_url
            audit.loc[i,'first_missing_field']='continuous_raw_account_reconstruction'
    audit.to_csv(HERE/'output/corporate_action_execution_completeness.csv',index=False)
    probes=[]
    for strategy,symbol,ex in [('ATRDR','600622.SH','2017-06-30'),('MCB','603368.SH','2020-06-24')]:
        fact=facts.loc[facts.symbol.eq(symbol)&facts.ex_date.eq(ex)].iloc[0]
        fills=pd.read_parquet(HERE/'cache'/strategy.lower()/'native_continuous/fills.parquet')
        buy=fills.loc[fills.symbol.eq(symbol)&fills.side.eq('BUY')&fills.entry.lt(ex)].iloc[-1]
        daily=con.execute('SELECT * FROM read_parquet(?) WHERE symbol=? AND trade_date BETWEEN ?::DATE AND ?::DATE ORDER BY trade_date',[config['daily_hist'],symbol,str(pd.Timestamp(buy.entry).date()),fact.tradable_date]).fetchdf()
        d=daily.iloc[0]
        i=Intent(strategy,'BULL' if strategy=='ATRDR' else 'MCB','DEMAND',buy.event_id,'',symbol,buy.decision_at,buy.entry,(),float(buy.quantity),float(buy.price),.002,price_basis='NATIVE_COORDINATE')
        raw=raw_intent(i,raw_price=float(d.open),coordinate_factor=float(d.coordinate_factor))
        histories=[]
        for future in [False,True]:
            account=PhysicalAccount('OGR');account.fund([raw],{s:1e6 for s in account.strategies},'P0',buy.entry)
            shares=ShareConversion(account);cash=CashDistribution(account)
            record=pd.Timestamp(fact.record_date)+pd.Timedelta(hours=15);when=pd.Timestamp(ex)+pd.Timedelta(hours=9,minutes=30)
            # The historical document date is used only to reconstruct legal
            # execution. Retrieval timestamp remains explicit in the fact file.
            known=pd.Timestamp(fact.historical_announcement_available_at)
            shares.record(fact.action_id,symbol,fact.share_ratio,record,known)
            cash.record(fact.action_id,symbol,fact.cash_ratio,record,known,ex_date=when,payment_date=when)
            prior=float(daily.loc[daily.trade_date.eq(fact.record_date),'close'].iloc[0]);account.mark({symbol:prior})
            before=account.checkpoint(record,'RECORD_MARK')['nav']
            exprice=float(daily.loc[daily.trade_date.eq(ex),'open'].iloc[0])
            shares.transition(fact.action_id,'ACCOUNTING_EFFECTIVE_DATE',when,known,ex_price=exprice)
            cash.pay(fact.action_id,when,known)
            histories.append(deepcopy((account.cash,account.positions,account.pending_positions,account.lots)))
            if future:
                listing=pd.Timestamp(fact.tradable_date)+pd.Timedelta(hours=9,minutes=30)
                # Minimal pending/tradable model: pending includes any credited
                # but nontradable shares; no distinct credit-day claim is made.
                shares.transition(fact.action_id,'SHARE_ARRIVAL_DATE',listing,known)
                shares.transition(fact.action_id,'TRADABLE_DATE',listing,known)
                account.mark({symbol:float(daily.iloc[-1].open)})
                account.checkpoint(listing,'LISTING_MARK')
        if histories[0]!=histories[1]:raise ValueError('company-action prefix failure')
        q=raw.native_requested_quantity
        expected=q*((1+fact.share_ratio)*exprice+fact.cash_ratio-prior)
        after=histories[0][0]+q*(1+fact.share_ratio)*exprice
        if abs(after-before-expected)>1e-6:raise ValueError('CA market-move reconciliation failed')
        probe=dict(strategy=strategy,symbol=symbol,action_id=fact.action_id,native_coordinate_quantity=float(buy.quantity),
            raw_quantity=q,entry_notional=float(buy.funded_notional),pending_new=q*fact.share_ratio,
            total_economic_quantity=q*(1+fact.share_ratio),cash_credit=q*fact.cash_ratio,
            record_to_ex_open_nav_move=expected,quantity_scope='ISOLATED_MAPPING_OF_VERIFIED_NATIVE_FUNDED_PREFIX; not a corrected continuous physical budget',
            prefix_status='PASS_ISOLATED_OFFICIAL_TIMELINE',continuous_account_status='NOT_RECONSTRUCTED')
        probes.append(probe)
        text=f'''# {symbol} 最终公司行动取证与工程状态

OFFICIAL_EXECUTION_FACT_STATUS = VERIFIED
CONTINUOUS_ACCOUNT_CLOSURE = ENGINEERING_INCOMPLETE

官方实施公告：{fact.source_url}
证据等级：{fact.source_grade}。SHA256：`{fact.raw_hash}`。
登记日 {fact.record_date} 收盘；除权日 {ex}；新增无限售股上市 {fact.tradable_date}；现金发放 {fact.cash_payment_date}。
每股新增 {fact.share_ratio:.9g} 股、现金 {fact.cash_ratio:.9g} 元。经济权益在除权日纳入 pending；这不是推定券商股份到账日。上市前 pending 不可卖。

原生已资助事件 `{buy.event_id}`，入场 {buy.entry}，原生坐标数量 {buy.quantity:.12f}，原生请求含费用金额 {buy.funded_notional:.12f}。
按同日价格/coordinate_factor 显式等额映射，原始数量 {q:.12f}；新增 pending {q*fact.share_ratio:.12f}；上市后总可交易数量 {q*(1+fact.share_ratio):.12f}。
这是原生已资助前缀的单笔映射，不是已经修正全历史资金反馈后的最终持仓量。更早的原始现金/分红反馈仍须完整重建，不能把这张表冒充共同 P0。

数量时间线：登记收盘 Q={q:.12f}；除权开盘 tradable={q:.12f}, pending={q*fact.share_ratio:.12f}；上市开盘 tradable={q*(1+fact.share_ratio):.12f}, pending=0。
现金权益 {q*fact.cash_ratio:.12f}；登记收盘至除权开盘的市场移动 NAV 影响 {expected:.12f}，与 Q*((1+r)*raw_open+dividend-previous_close) 一致，误差小于 1e-6。
理论除权价格下 NAV 守恒由聚焦测试验证，实际市场移动不被抹掉。

历史前缀：单笔实证转换在只跑至除权日与追加上市日两次运行中，现金、原始数量、pending 和虚拟 lot 完全相同。
上市前退出：旧连续引擎在除权前停止，不能据此宣称完整重建账户没有退出；单笔公司行动探针没有策略退出决策，不能用于收益比较。

仍须完成：连续 raw 数量/现金重建、合法原生退出在已失效坐标谱系后的映射、全部持仓事件覆盖、正式边界与独立 P0 对账。官方日期缺失已解决，不能再把以上工程欠项报告为缺少官方上市日期。
'''
        (HERE/'reports'/f'ca_{symbol[:6]}_final_closure.md').write_text(text)
    pd.DataFrame(probes).to_csv(HERE/'output/official_ca_position_probes.csv',index=False)
    con.close();return facts

if __name__=='__main__':run()
