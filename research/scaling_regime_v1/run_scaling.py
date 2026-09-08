"""Authorized unchanged target/mechanic grid after continuous Native passes."""
from concurrent.futures import ProcessPoolExecutor
from .scaling_observer import run_case,freeze
from .economics import require_identity,cases
from .audit import HERE,write_json


def main():
    require_identity();freeze()
    with ProcessPoolExecutor(max_workers=3) as pool:
        receipts=list(pool.map(run_case,[case for case in cases() if case[2]!='NATIVE']))
    write_json(HERE/'output/authoritative_scaling_receipts.json',receipts)


if __name__=='__main__':main()
