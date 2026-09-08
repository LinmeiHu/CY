"""Extend the same read-only root trace to the G50/G75 attribution references."""
from concurrent.futures import ProcessPoolExecutor
from .capital_trace import trace
from .economics import cases,require_identity
from .audit import HERE,write_json


def main():
    require_identity()
    selected=[c for c in cases() if c[3]=='FULL_BOOK_NORMALIZATION' and c[2] in ['G50','G75']]
    with ProcessPoolExecutor(max_workers=2) as pool:results=list(pool.map(trace,selected))
    write_json(HERE/'output/root_capital_trace_extra_receipts.json',results)


if __name__=='__main__':main()
