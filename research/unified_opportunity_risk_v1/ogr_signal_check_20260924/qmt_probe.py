import json
from pathlib import Path
from xtquant import xtdata

out = Path(__file__).parent / 'qmt_probe.json'
try:
    data = xtdata.get_market_data_ex([], ['300308.SZ'], period='1d', start_time='20260917', end_time='20260923', dividend_type='none', fill_data=False)
    frame = data['300308.SZ']
    out.write_text(json.dumps({'rows': len(frame), 'dates': list(frame.index.astype(str)), 'columns': list(frame.columns)}, ensure_ascii=False))
except Exception as exc:
    out.write_text(json.dumps({'error': repr(exc)}, ensure_ascii=False))
