"""Execution-only registered actions, activated by actual record-date ownership.

Loading the registry does not certify hypothetical holdings. Completeness rows
are emitted only when the account owns a lot at the record checkpoint.
"""
import json
from pathlib import Path
from math import isfinite
import duckdb
import pandas as pd
from .corporate_actions import ShareConversion, CashDistribution

HERE = Path(__file__).resolve().parents[1]


def registered_actions():
    config = json.loads((HERE.parent / 'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    frames = []
    with duckdb.connect() as con:
        for key in ('qd010_distributions', 'qd010_rights'):
            frame = con.execute("SELECT * FROM read_parquet(?) WHERE effective_date BETWEEN '2014-01-01' AND '2023-12-31'", [config[key]]).fetchdf()
            frame['registered_source'] = config[key]
            frames.append(frame)
    frame = pd.concat(frames, ignore_index=True)
    if frame.event_id.isna().any() or frame.event_id.duplicated().any():
        raise ValueError('null/duplicate registered corporate-action identity')
    official = pd.read_csv(HERE / 'output/corporate_action_official_backfill_facts.csv').set_index('action_id')
    frame['tradable_date'] = frame.share_credit_date
    frame['evidence_hash'] = frame.response_sha256
    frame['evidence_source'] = frame.source_api
    frame['evidence_grade'] = 'OFFICIAL_EX_POST_EXECUTION_FACT'
    frame['retrieved_at'] = frame.fetched_at
    for index, row in frame.iterrows():
        if row.event_id in official.index:
            fact = official.loc[row.event_id]
            # Terms retain the registered exact ratios; the document adds dates.
            for column, source in [('tradable_date','tradable_date'), ('pay_date','cash_payment_date')]:
                frame.at[index, column] = pd.Timestamp(fact[source])
            frame.at[index,'evidence_hash'] = fact.raw_hash
            frame.at[index,'evidence_source'] = fact.source_url
            frame.at[index,'retrieved_at'] = fact.retrieved_at
    return frame


class HeldActions:
    def __init__(self, account, registry, strategy, cash_credit):
        self.account, self.strategy, self.cash_credit = account, strategy, cash_credit
        self.shares, self.dividends = ShareConversion(account), CashDistribution(account)
        self.records = {pd.Timestamp(day): group.to_dict('records') for day,group in registry.groupby('record_date')}
        self.active, self.audit, self.timeline = {}, [], []
        self.rebased_symbols = set()

    def _capture(self, action, when, phase):
        lots = [l for l in self.account.lots.values() if l['strategy'] == self.strategy and l['symbol'] == action['symbol']]
        self.timeline.append(dict(strategy=self.strategy, symbol=action['symbol'], action_id=action['event_id'],
            timestamp=when, phase=phase, raw_quantity_total=sum(l['quantity']+l.get('pending_quantity',0.) for l in lots),
            tradable_quantity=sum(l['quantity']-l.get('nontradable_quantity',0.) for l in lots),
            pending_quantity=sum(l.get('pending_quantity',0.)+l.get('nontradable_quantity',0.) for l in lots),
            cash=self.account.sleeve_cash[self.strategy], nav=self.account.sleeve_cash[self.strategy]+self.account.exposure(self.strategy)))

    def record(self, day):
        when = day + pd.Timedelta(hours=15, minutes=1)
        for original in self.records.get(day, []):
            lots = [l for l in self.account.lots.values() if l['strategy']==self.strategy and l['symbol'][:6]==original['symbol']]
            if not lots:
                continue
            action = dict(original, symbol=lots[0]['symbol'])
            eid = action['event_id'] + '|' + self.strategy
            ratio = float(action['share_multiplier'])-1
            cash = float(action['cash_per_share_gross'])
            missing = next((name for name in ('effective_date','known_at') if pd.isna(action[name])), '')
            if action['event_type'] == 'rights_issue': missing = 'native_rights_subscription_execution'
            if not isfinite(ratio) or ratio < 0: missing = missing or 'share_multiplier'
            if not isfinite(cash) or cash < 0: missing = missing or 'cash_per_share_gross'
            if ratio and pd.isna(action['tradable_date']): missing = missing or 'tradable_date'
            if cash and pd.isna(action['pay_date']): missing = missing or 'cash_payment_date'
            if cash and action['pay_date'] != action['effective_date']: missing = missing or 'delayed_dividend_receivable_implementation'
            row = dict(strategy=self.strategy, route='|'.join(sorted({str(l['route']) for l in lots})), symbol=action['symbol'],
                action_id=action['event_id'], action_type=action['event_type'], holding_overlap=True,
                announcement_date=action['announcement_date'], record_date=day, ex_date=action['effective_date'],
                accounting_effective_date=action['effective_date'], tradable_date=action['tradable_date'], cash_payment_date=action['pay_date'],
                share_ratio=ratio, cash_ratio=cash, tradable_quantity_before=sum(l['quantity'] for l in lots),
                pending_quantity_before=sum(l.get('pending_quantity',0.) for l in lots), source=action['evidence_source'],
                source_grade=action['evidence_grade'], available_at=action['retrieved_at'], raw_hash=action['evidence_hash'],
                status='UNRESOLVED' if missing else 'RECORDED', first_missing_field=missing)
            self.audit.append(row)
            if missing:
                raise ValueError(f"HELD_ACTION_UNRESOLVED:{self.strategy}:{action['symbol']}:{action['event_id']}:{missing}")
            action.update(share_ratio=ratio, cash_ratio=cash, board_amounts={})
            for lot in lots:
                board=lot['board']
                action['board_amounts'][board]=action['board_amounts'].get(board,0.)+lot['quantity']*cash
            action['audit_row']=row
            self.active[eid]=action
            if ratio:
                self.shares.record(eid,action['symbol'],ratio,when,action['known_at'],strategy=self.strategy)
            if cash:
                payment=action['pay_date']+pd.Timedelta(hours=9,minutes=30)
                self.dividends.record(eid,action['symbol'],cash,when,action['known_at'],ex_date=payment,payment_date=payment,strategy=self.strategy)
            self._capture(action,when,'RECORD_DATE')

    def open(self, day, prices):
        when=day+pd.Timedelta(hours=9,minutes=30)
        for eid, action in list(self.active.items()):
            if action['effective_date'] == day:
                self.rebased_symbols.add(action['symbol'])
                if action['share_ratio']:
                    self.shares.transition(eid,'ACCOUNTING_EFFECTIVE_DATE',when,action['known_at'],ex_price=prices[action['symbol']])
                if action['cash_ratio']:
                    self.dividends.pay(eid,when,action['known_at'])
                    for board, amount in action['board_amounts'].items(): self.cash_credit(board,amount)
                self._capture(action,when,'EX_DATE')
            if action['share_ratio'] and action['tradable_date'] == day:
                for phase in ('SHARE_ARRIVAL_DATE','TRADABLE_DATE'):
                    self.shares.transition(eid,phase,when,action['known_at'])
                self._capture(action,when,'TRADABLE_DATE')
            final=max(action['effective_date'], action['tradable_date'] if action['share_ratio'] else action['effective_date'])
            if day >= final:
                action['audit_row']['status']='APPLIED'
                del self.active[eid]
