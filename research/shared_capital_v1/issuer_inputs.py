"""Registered announcement routing closure; never read accepted trades."""
import json
from pathlib import Path

import duckdb
import pandas as pd

from five_strategy_bundle.strategies import ifcgr
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.run_shared_capital_v1 import sha256, write_json
from research.shared_capital_v1.validation import require_keys

HERE = Path(__file__).resolve().parent
FACT_ROOT = Path('/Users/linmei/Documents/CY/data/staging/CY-062-V29R2-ISSUER-FACT-ROLLFORWARD-2022-2026-V1')


def verify_source(out):
    manifest_path = FACT_ROOT / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    checked = []
    for item in manifest["inventory"]:
        path = Path(item["path"])
        if path.is_relative_to(FACT_ROOT):
            actual = sha256(path)
            if actual != item["sha256"]:
                raise ValueError(f"issuer input hash mismatch: {path}")
            checked.append({"path": str(path), "sha256": actual})
    con = duckdb.connect()
    try:
        route = con.execute("SELECT * FROM read_parquet(?) WHERE available_at < TIMESTAMP '2024-01-01'", [str(FACT_ROOT / "announcement_route_index.parquet")]).fetchdf()
        stats = con.execute("SELECT count(*), min(available_at), max(available_at), count(*) FILTER(WHERE available_at >= TIMESTAMP '2022-01-01' AND available_at < TIMESTAMP '2024-01-01') FROM read_parquet(?)", [str(FACT_ROOT / "announcement_route_index.parquet")]).fetchone()
    finally:
        con.close()
    require_keys(route, ["announcement_key"], "CY062 route")
    required = ["announcement_id", "symbol", "available_at", "raw_record_sha256", "snapshot_id"]
    if route[required].isna().any(axis=None) or not route.hard_valid.all():
        raise ValueError("issuer route critical fields invalid")
    # Legacy classifier expects causal_available_at. The CY062 route already
    # carries the official availability, conservatively max'ed with SSE query
    # membership date +1d by the registered routing contract.
    causal = pd.to_datetime(route.available_at)
    sse = route.exchange.eq("SSE")
    causal.loc[sse] = pd.concat([causal.loc[sse], pd.to_datetime(route.loc[sse, "source_query_date"]).dt.normalize() + pd.Timedelta(days=1)], axis=1).max(axis=1)
    route["causal_available_at"] = causal
    cache = HERE / "cache/issuer"
    cache.mkdir(parents=True, exist_ok=True)
    route = route.loc[route.causal_available_at.lt("2024-01-01")]
    route.to_parquet(cache / "announcement_route_index.parquet", index=False)
    for name in ("source_capture", "sse_full_history_capture"):
        source_path = FACT_ROOT / name / "source_manifest.json"
        source = json.loads(source_path.read_text())
        titles = FACT_ROOT / name / "announcements.parquet"
        digest = sha256(titles)
        if digest != source["hashes"]["announcements_parquet"]:
            raise ValueError(f"issuer title hash mismatch: {titles}")
        checked.append({"path": str(titles), "sha256": digest})
    coverage = {
        "candidate": "CY062_RAW_VIA_REGISTERED_CY063_CY065_CORRECTION_CHAIN",
        "source_identity": str(manifest_path), "manifest_sha256": sha256(manifest_path),
        "route_sha256": manifest["route_index"]["sha256"], "row_count": stats[0],
        "min_available_at": str(stats[1]), "max_available_at": str(stats[2]),
        "rows_2022_2023": stats[3], "announcement_id": "announcement_id",
        "issuer_id": "symbol", "available_at": "max(available_at,SSE source_query_date+1d)",
        "pit_grade": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        "revision_deletion_limit": "CURRENT_ENUMERATION_NO_COMPLETE_REVISION_OR_DELETION_VINTAGES",
        "schema": "|".join(route.columns), "query_coverage": json.dumps(manifest["coverage"], sort_keys=True),
        "status": "PIT_B_SOURCE_FOUND_PARENT_WINDOW_COVERAGE_REQUIRES_RECONCILIATION",
    }
    pd.DataFrame([coverage]).to_csv(out / "ifcgr_data_coverage.csv", index=False)
    write_json(out / "issuer_source_hashes.json", checked)
    return coverage


def select_later(parents):
    universe = set(pd.read_parquet(FACT_ROOT / "universe.parquet").symbol)
    sse_universe = set(pd.read_parquet(FACT_ROOT / "sse_full_universe.parquet").symbol)
    windows = parents[["gap_id", "symbol", "signal_time"]].copy()
    windows["window_start"] = pd.to_datetime(windows.signal_time) - pd.Timedelta(days=120)
    windows["coverage_valid"] = [
        (row.symbol in sse_universe if row.symbol.endswith(".SH") else row.symbol in universe and row.window_start >= pd.Timestamp("2021-10-18"))
        and pd.Timestamp(row.signal_time) <= pd.Timestamp("2023-12-31 23:59:59")
        for row in windows.itertuples()
    ]
    windows.to_csv(HERE / "output/ifcgr_parent_window_coverage.csv", index=False)
    if not windows.coverage_valid.all():
        raise ValueError("DATA_INPUT_MISSING: new parent issuer/window outside registered coverage")
    select = corrected_function(ifcgr.select_issuer_facts, [
        ("WHERE r.causal_available_at<TIMESTAMP '2022-01-01'", "WHERE r.causal_available_at<TIMESTAMP '2024-01-01'"),
    ])
    return select(parents, HERE / "cache/issuer/announcement_route_index.parquet",
                  FACT_ROOT / "sse_full_history_capture/announcements.parquet", FACT_ROOT / "source_capture/announcements.parquet")


if __name__ == "__main__":
    print(json.dumps(verify_source(HERE / "output"), indent=2))
