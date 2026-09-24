"""Extend the frozen PIT-B daily input for an isolated OGR signal check."""
from pathlib import Path
import inspect
from research.shared_capital_v1.causal_adapters import corrected_function
from research.unified_opportunity_risk_v1.rollforward_20260917 import prepare_stock as previous

HERE=Path(__file__).parent
PRIOR=HERE.parent/'rollforward_20260917'

def main():
    previous.HERE=HERE
    previous.CACHE=HERE/'cache'
    previous.END='2026-09-23'
    previous.OLD=PRIOR/'cache/daily_with_snapshot.parquet'
    (HERE/'official_facts').mkdir(exist_ok=True)
    link=HERE/'official_facts/stock_action_combined_delta.parquet'
    if not link.exists():link.symlink_to(PRIOR/'official_facts/stock_action_combined_delta.parquet')
    source=inspect.getsource(previous.main)
    changes=[
        ("market=CACHE/'qmt_market'", "market=CACHE/'market'"),
        ('builder.START=date(2026,9,7);builder.END=date(2026,9,16)', 'builder.START=date(2026,9,17);builder.END=date(2026,9,23)'),
        ("'CANDIDATE_B_20260916_MARKET'", "'OGR_SIGNAL_CHECK_20260923_MARKET'"),
        ('base_daily_root=builder._daily_partition_root(assets[\'CY-033\'])', "base_daily_root=Path('"+str(PRIOR/'cache/pit_full/daily')+"')"),
        ("'CANDIDATE_B_ROLLFORWARD_20260916'", "'OGR_SIGNAL_CHECK_20260923'"),
        ("base_root=builder._daily_partition_root(assets['CY-033'])", "base_root=Path('"+str(PRIOR/'cache/pit_full/daily')+"')"),
        ("quality['day_count']==8", "quality['day_count']==5"),
        ("trade_date<='2026-09-04'", "trade_date<='2026-09-16'"),
    ]
    for old,new in changes:
        if old not in source:raise RuntimeError('Source binding changed: '+old)
    run=corrected_function(previous.main,changes)
    run()

if __name__=='__main__':main()
