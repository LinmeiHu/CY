"""Incremental historical fee regimes; see ACCOUNT_CONTRACT.md for cost assumptions."""
from decimal import Decimal as D
import pandas as pd

def stamp_rate(day,sell):
    assert '2007-01-01'<=day<='2023-12-31'
    if day<'2007-05-30':return D('.001')
    if day<'2008-04-24':return D('.003')
    if day<'2008-09-19':return D('.001')
    if not sell:return D(0)
    return D('.001') if day<'2023-08-28' else D('.0005')

def fees(value,day,sell,quantity,symbol,multiplier=D(1)):
    assert quantity is not None and symbol is not None
    # Old per-face-value periods: 1 yuan face-value upper-envelope proxy.
    # 2007-2012 intentionally retains old conservative SH min1 / 1-per-1000.
    if day<'2013-01-01':transfer=max(D(1),D(quantity)*D('.001')) if symbol.endswith('.SH') else D(0)
    elif day<'2015-08-01':transfer=max(D(1),D(quantity)*D('.0003')) if symbol.endswith('.SH') else D(0)
    else:transfer=value*(D('.00002') if day<'2022-04-29' else D('.00001'))
    # Commission includes exchange/regulatory charges; SZ pre-2015 pass-through included.
    return max(D(5),value*D('.0003')*multiplier)+transfer+value*stamp_rate(day,sell)+value*D('.0005')*multiplier

def maximum_dividend_rate(record_date):return D('.1') if record_date<'2013-01-01' else D('.2')

def dividend_rate(acquired,sold,record_date):
    if record_date<'2013-01-01':return D('.1')
    if sold<=acquired+pd.DateOffset(months=1):return D('.2')
    if sold<=acquired+pd.DateOffset(years=1):return D('.1')
    return D('.05') if record_date<'2015-09-08' else D(0)
