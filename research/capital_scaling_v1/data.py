"""Bounded, hash-bound native requests and sparse legal execution quotes."""
import json
import os
from pathlib import Path

import duckdb
import pandas as pd

from five_strategy_bundle.io import sha256, write_json
from research.shared_capital_v1.common_p0_v06 import load_inputs, PERIODS
from research.shared_capital_v1.build_inputs import execution_paths
from .preflight import HERE, PARENT, ROOT

EXTERNAL = Path('/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_v1')


def cache_identity():
    return dict(inputs=sha256(HERE/'input_manifest.json'), period='2018-01-01/2023-12-31',
                strategy_version=sha256(PARENT/'contracts/strategy_universe_v1.json'),
                producer_version=dict(quotes=sha256(Path(__file__)), execution_paths=sha256(Path(execution_paths.__code__.co_filename))),
                configuration_hash=sha256(PARENT.parent/'five_strategy_exit_risk_v1/input_config.json'))


def prepare_quotes():
    if not os.path.ismount('/Volumes/quant'):
        raise ValueError('verified external volume is not mounted')
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    frame_path, receipt = EXTERNAL/'legal_quotes.parquet', EXTERNAL/'legal_quotes.identity.json'
    identity = cache_identity()
    if frame_path.exists() and receipt.exists():
        old = json.loads(receipt.read_text())
        if old['identity'] == identity and old['sha256'] == sha256(frame_path):
            return frame_path
    inputs = {k: Path(v) for k, v in json.loads((PARENT.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    entries = [pd.read_parquet(PARENT/'cache'/s/'precapital_entry_population.parquet')[['symbol']] for s in ('atrdr', 'mcb')]
    gap = pd.read_parquet(PARENT/'cache/ogr/outcomes.parquet')
    registry = pd.concat([*entries, gap[['symbol']]]).drop_duplicates()
    # The prior native target observation is completed before the next minute
    # open. 15:00 target exits wait until the next session's legal opening.
    times = sorted({pd.Timestamp(t)+pd.Timedelta(minutes=1) for t in gap.exit_time.dropna()
                    if pd.Timestamp(t).hour < 15 and (pd.Timestamp(t)+pd.Timedelta(minutes=1)).time() < pd.Timestamp('15:00').time()}
                   | {pd.Timestamp(t) for t in gap.entry_time.dropna() if pd.Timestamp(t).time() != pd.Timestamp('09:30').time()})
    checkpoints = pd.DataFrame({'timestamp': times})
    columns = 'symbol,trade_date,open,close,trade_status,current_day_data_tradable,market_rule_valid,up_limit_price,down_limit_price'
    with duckdb.connect() as con:
        con.execute('SET threads=4')
        con.register('registry', registry)
        parts = ' UNION ALL '.join(f"SELECT {columns},{i} AS priority FROM read_parquet('{p}') JOIN registry USING(symbol) WHERE trade_date BETWEEN '2018-01-01' AND '2023-12-31'" for i, p in enumerate(execution_paths(inputs)))
        con.execute(f'CREATE TEMP TABLE daily AS WITH d AS ({parts}) SELECT * EXCLUDE(priority) FROM d QUALIFY row_number() OVER(PARTITION BY symbol,trade_date ORDER BY priority)=1')
        rows = [con.execute("SELECT symbol,trade_date+INTERVAL '9 hours 30 minutes' AS timestamp,open AS price, current_day_data_tradable AND market_rule_valid AND trade_status=1 AND round(open*100)<round(up_limit_price*100) AS buy, current_day_data_tradable AND market_rule_valid AND trade_status=1 AND round(open*100)>round(down_limit_price*100) AS sell FROM daily WHERE trade_status=1 AND isfinite(open) AND open>0").fetchdf()]
        con.register('checkpoints', checkpoints)
        for year in range(2018, 2024):
            print('Sparse native-clock quotes', year, flush=True)
            raw = inputs['raw_minute_root']/f'{year}_day_parquet_none.parquet'
            rows.append(con.execute("""SELECT r.qmt_code AS symbol,r.bar_end_time AS timestamp,r.open AS price,
                d.current_day_data_tradable AND d.market_rule_valid AND d.trade_status=1 AND round(r.open*100)<round(d.up_limit_price*100) AS buy,
                d.current_day_data_tradable AND d.market_rule_valid AND d.trade_status=1 AND round(r.open*100)>round(d.down_limit_price*100) AS sell
                FROM read_parquet(?) r JOIN checkpoints c ON r.bar_end_time=c.timestamp
                JOIN daily d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
                WHERE r.period='1m' AND r.adjust='none' AND isfinite(r.open) AND r.open>0 AND r.volume>0""", [str(raw)]).fetchdf())
    quotes = pd.concat(rows, ignore_index=True).sort_values(['timestamp', 'symbol'])
    if quotes[['timestamp', 'symbol']].duplicated().any():
        raise ValueError('duplicate quote identity')
    if quotes[['price', 'buy', 'sell']].isna().any(axis=None):
        raise ValueError('missing execution quote fields')
    temp = frame_path.with_suffix('.tmp.parquet')
    quotes.to_parquet(temp, index=False)
    temp.replace(frame_path)
    write_json(receipt, dict(identity=identity, sha256=sha256(frame_path), rows=len(quotes)))
    return frame_path


def load():
    print('Loading verified bounded parent inputs', flush=True)
    references = {str(p.resolve()): sha256(p) for p in sorted((PARENT/'cache/common_p0').rglob('*.parquet'))}
    baseline_artifacts = pd.read_csv(PARENT/'output/scenario_artifact_manifest.csv')
    baseline_artifacts = baseline_artifacts.loc[baseline_artifacts.policy.eq('P0')]
    for r in baseline_artifacts.itertuples(index=False):
        path = PARENT/r.path
        actual = sha256(path)
        if actual != r.sha256:
            raise ValueError('sealed native artifact hash drift: '+str(path))
        references[str(path.resolve())] = actual
    receipt = HERE/'native_reference_manifest.json'
    if receipt.exists() and json.loads(receipt.read_text()) != references:
        raise ValueError('native sizing reference cache identity drift')
    if not receipt.exists():
        write_json(receipt, references)
    data = load_inputs(execution_hardening=HERE/'contracts/execution_hardening_v1.json')
    data['native_home'], data['native_requests'] = {}, {}
    for gap in ('OGR', 'IFCGR'):
        for period, _, _ in PERIODS:
            folder = PARENT/'cache/common_p0'/gap/period
            home = pd.read_parquet(folder/'account_timeline.parquet').set_index('timestamp')
            before = pd.read_parquet(folder/'home_before_funding.parquet').set_index('timestamp')
            home.loc[before.index, before.columns] = before
            data['native_home'][(period, gap)] = home
            for strategy in ('ATRDR', 'MCB', gap):
                requests = pd.read_parquet(folder/f'{strategy.lower()}_intents.parquet')
                if requests.event_id.duplicated().any() or requests.event_id.isna().any():
                    raise ValueError('native request identity')
                for row in requests.to_dict('records'):
                    data['native_requests'][(period, gap, strategy, row['event_id'])] = row
    path = prepare_quotes()
    print('Loading sparse quotes', flush=True)
    frame = pd.read_parquet(path)
    data['quotes'] = {pd.Timestamp(t): {r.symbol: dict(price=r.price, buy=bool(r.buy), sell=bool(r.sell)) for r in group.itertuples(index=False)} for t, group in frame.groupby('timestamp', sort=True)}
    data['quote_hash'] = sha256(path)
    return data


if __name__ == '__main__':
    from .preflight import run as preflight
    preflight()
    prepare_quotes()
