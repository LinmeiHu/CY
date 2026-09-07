import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import risk_review as r


def test_actual_fill_return_ignores_producer_fee_shortcut():
    a=pd.DataFrame(dict(qty=[2.],exit_price=[65.],entry_outlay=[200.4],net_return=[-.354]))
    assert r.realized_returns(a).iloc[0]==pytest.approx(2*65*.998/200.4-1)
    a['net_return']=999
    assert r.realized_returns(a).iloc[0]<0
    o=pd.DataFrame(dict(gap_id=['x'],qty=[2.],exit_raw_price=[65.],entry_outlay=[200.4],
        entry_date=[pd.Timestamp('2020-01-02')],exit_date=[pd.Timestamp('2020-01-06')],
        cash_events_json=[json.dumps([dict(date='2020-01-03',cash_per_share=1.),dict(date='2020-01-07',cash_per_share=999.)])]))
    assert r.realized_returns(o).iloc[0]==pytest.approx((2*65*.998+2)/200.4-1)
    assert r.realized_returns(o.set_index('gap_id')).iloc[0]==pytest.approx((2*65*.998+2)/200.4-1)


def test_common_calendar_only_extends_uninvested_cash():
    dates=pd.date_range('2020-01-01',periods=5)
    d=pd.DataFrame(dict(trade_date=dates))
    n=pd.DataFrame(dict(trade_date=dates[1:4],nav=[.99,1.02,1.04],cash=[.49,.50,1.04],gross_exposure=[.50,.52,0.]))
    x=r.align_cash_calendar(n,d,dates[0],dates[-1])
    assert x.nav.tolist()==[1.,.99,1.02,1.04,1.04]
    with pytest.raises(AssertionError,match='invested'):
        r.align_cash_calendar(n.assign(gross_exposure=[.50,.52,.1]),d,dates[0],dates[-1])
    with pytest.raises(AssertionError,match='Missing internal'):
        r.align_cash_calendar(n.drop(index=1),d,dates[0],dates[-1])


def test_completed_risk_accounts_reconcile_and_never_finance():
    done=json.loads((r.OUT/'completed.json').read_text())
    e=pd.read_csv(r.HERE/'risk_cash_reuse_decomposition.csv')
    assert done['account_replays']==len(e)==20
    parts=e[['common_event_exit_pnl_delta','common_event_quantity_pnl_delta','newly_funded_pnl','cancelled_event_pnl']].sum(axis=1)
    assert np.allclose(e.total_account_nav_delta,parts,rtol=0,atol=1e-9)
    assert e.decomposition_residual.abs().le(1e-9).all()
    a=pd.read_csv(r.HERE/'risk_no_financing_audit.csv')
    assert len(a)==40
    assert (a.negative_cash_timestamps+a.exposure_violation_timestamps).sum()==0
    assert a.min_cash.ge(-1e-10).all() and a.max_gross_ratio.le(1+1e-10).all()
    c=pd.read_csv(r.HERE/'risk_account_comparison.csv')
    assert c.start.eq(c.baseline_start).all() and c.end.eq(c.baseline_end).all()
    assert c.days.eq(c.baseline_days).all()
    assert c.evidence.eq(r.EVIDENCE).all()
