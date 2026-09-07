"""Fail-closed native continuous stock-account boundary probe."""
import json
from pathlib import Path
import pandas as pd
from five_strategy_bundle.execution.daily import load_daily
from research.shared_capital_v1.build_inputs import execution_paths
from research.shared_capital_v1.stock_p0 import HERE, replay


def run():
    config = json.loads((HERE.parent / 'five_strategy_exit_risk_v1/input_config.json').read_text())
    inputs = {k: Path(v) for k, v in config['inputs'].items()}
    rows = []
    for strategy in ('ATRDR', 'MCB'):
        entries = pd.read_parquet(HERE / 'cache' / strategy.lower() / 'precapital_entry_population.parquet')
        daily = load_daily(execution_paths(inputs), entries.symbol.tolist())
        account, intents, rejected, nav, blocker = replay(strategy, entries, daily, '2014-01-01', '2023-12-31', boundaries=('2018-01-01', '2022-01-01'))
        root = HERE / 'cache' / strategy.lower() / 'native_continuous'
        root.mkdir(parents=True, exist_ok=True)
        for name, frame in [('nav', nav), ('intents', intents), ('fills', pd.DataFrame(account.fills)), ('last_known_lots', pd.DataFrame(account.lots.values()))]:
            frame.to_parquet(root / f'{name}.parquet', index=False)
        (root / 'boundary_snapshots.json').write_text(json.dumps(account.boundary_snapshots, default=str, indent=2))
        for period, boundary in [('2018_2021', '2018-01-01'), ('2022_2023', '2022-01-01')]:
            snapshot = account.boundary_snapshots.get(boundary)
            reached = snapshot is not None
            rows.append({'strategy': strategy, 'period': period, 'boundary': boundary,
                'native_origin': '2014-01-01', 'mode': 'NATIVE_CONTINUOUS',
                'status': 'NATIVE_BOUNDARY_RECONSTRUCTED_REFERENCE_COMPARISON_PENDING' if reached else 'ACCOUNTING_BLOCKED',
                'first_blocker': blocker, 'last_valid_date': str(nav.trade_date.max().date()),
                'last_valid_nav': float(nav.nav.iloc[-1]), 'last_valid_cash': float(nav.cash.iloc[-1]),
                'last_known_open_lots': len(account.lots), 'funded_entries_before_block': sum(f['side']=='BUY' for f in account.fills),
                'boundary_nav': snapshot['nav'] if snapshot else None, 'boundary_cash': snapshot['cash'] if snapshot else None, 'boundary_holdings': json.dumps(snapshot['positions'], sort_keys=True) if snapshot else None,
                'qualification': 'last known state is not a valid boundary snapshot after unresolved action'})
        print(rows[-2:], flush=True)
    pd.DataFrame(rows).to_csv(HERE / 'output/native_initial_state_probe.csv', index=False)


if __name__ == '__main__':
    run()
