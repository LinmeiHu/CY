import json
from types import SimpleNamespace
import pandas as pd
import pytest
from five_strategy_bundle.strategies import mcb, smv6_frozen, smv6
from research.shared_capital_v1.universe import CONTRACT, assert_stock_membership


def test_registered_boards_and_metadata_not_prefix_guessing():
    c=json.loads(CONTRACT.read_text()); registry=c['stock_input']['members']
    for symbol,board in [('600000.SH','MAIN'),('000001.SZ','MAIN'),('300001.SZ','CHINEXT'),('302132.SZ','CHINEXT')]:
        assert_stock_membership(pd.DataFrame([dict(symbol=symbol,sleeve=board)]),registry)
    for symbol,board in [('688001.SH','STAR'),('830799.BJ','BEIJING'),('510300.SH','ETF'),('300001.SZ','MAIN'),('688001.SH','MAIN')]:
        with pytest.raises(ValueError,match='outside frozen'):
            assert_stock_membership(pd.DataFrame([dict(symbol=symbol,sleeve=board)]),registry)
    with pytest.raises(ValueError,match='null'):
        assert_stock_membership(pd.DataFrame([dict(symbol=None,sleeve='MAIN')]),registry)


def test_mcb_native_same_completed_close_requires_main_and_chinext(tmp_path):
    def native(boards,dates=None):
        rows=[]
        for i,b in enumerate(boards):
            day=pd.Timestamp('2020-01-02')+pd.Timedelta(days=0 if dates is None else dates[i])
            rows.append(dict(event_id=str(i),source_event_id='P'+str(i),sleeve=b,causal_industry='I',signal_date=day,decision_at=day+pd.Timedelta(hours=15)))
        return mcb.build_v72(pd.DataFrame(rows),tmp_path/'v72.parquet')
    assert len(native(['MAIN','CHINEXT']))==2
    assert native(['MAIN','MAIN']).empty
    assert native(['MAIN','STAR']).empty
    assert native(['MAIN','BEIJING']).empty
    assert native(['MAIN','CHINEXT'],[0,1]).empty


def test_frozen_etf_pool_intersection_and_listing(monkeypatch):
    context=SimpleNamespace(pool_raw=smv6.raw_pool(),pool_raw_set=set(smv6.raw_pool()))
    platform=SimpleNamespace(list_dates={'510300.SH':pd.Timestamp('2012-01-01'),'588000.SH':pd.Timestamp('2020-11-16'),'999999.SH':pd.Timestamp('2000-01-01')},current_date=pd.Timestamp('2018-01-01'))
    monkeypatch.setattr(smv6_frozen,'get_all_securities',lambda kind:smv6.ShadowPlatform.get_all_securities(platform,kind),raising=False)
    assert smv6_frozen.get_active_pool(context)==['510300.SH']
    platform.current_date=pd.Timestamp('2021-01-01')
    assert smv6_frozen.get_active_pool(context)==['510300.SH','588000.SH']
    assert all(x.startswith(('1','5')) for x in context.pool_raw)


def test_ifcgr_registered_parent_population_does_not_broaden():
    from research.shared_capital_v1.run_shared_capital_v1 import HERE
    parent=pd.read_parquet(HERE/'cache/ogr/signals.parquet')
    children=pd.concat([pd.read_parquet(HERE/'cache/ifcgr'/p/'signals.parquet') for p in ['2018_2021','2022_2023']])
    # Compare identity plus symbol; matching id alone could conceal a symbol change.
    keys=['gap_id','symbol']
    assert not parent[keys].isna().any().any()
    assert set(map(tuple,children[keys].to_numpy())) <= set(map(tuple,parent[keys].to_numpy()))
