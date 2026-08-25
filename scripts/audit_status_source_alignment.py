import argparse
import json
from pathlib import Path

import duckdb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baostock", required=True)
    p.add_argument("--qmt", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    con = duckdb.connect()
    sql = f"""
    with bs as (
      select symbol, cast(date as date) trade_date,
             cast(tradestatus as integer) bs_trade_status,
             cast(isST as integer) bs_is_st
      from read_csv_auto('{a.baostock}')
    ), q as (
      select symbol, trade_date, trade_status qmt_trade_status,
             cast(is_st as integer) qmt_is_st, hard_valid
      from read_parquet('{a.qmt}', union_by_name=true)
      where trade_date between date '{a.start}' and date '{a.end}'
        and symbol in (select distinct symbol from bs)
    ), j as (
      select bs.symbol, bs.trade_date, bs.bs_trade_status,
             q.qmt_trade_status, bs.bs_is_st, q.qmt_is_st, q.hard_valid,
             case when q.symbol is null then 'missing_qmt'
                  when bs.bs_trade_status != q.qmt_trade_status then 'trade_status_conflict'
                  when bs.bs_is_st != q.qmt_is_st then 'is_st_conflict'
                  else 'agree' end as category
      from bs left join q using(symbol, trade_date)
    )
    select category, count(*) row_count, count(distinct symbol) symbol_count,
           sum(case when hard_valid then 1 else 0 end) hard_valid_rows
    from j group by category order by category
    """
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    conflicts = con.execute(sql.replace(
        "select category, count(*) row_count, count(distinct symbol) symbol_count,\n           sum(case when hard_valid then 1 else 0 end) hard_valid_rows\n    from j group by category order by category",
        "select category, symbol, trade_date, bs_trade_status, qmt_trade_status, bs_is_st, qmt_is_st\n    from j where category != 'agree' order by category, symbol, trade_date limit 100"))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"request": vars(a), "summary": rows,
                               "sample_non_agree": conflicts.fetchall()},
                              ensure_ascii=False, default=str, indent=2) + "\n")
    print(json.dumps({"summary": rows, "output": str(out)}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
