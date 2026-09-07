"""Standalone PIT-B issuer-fact cooldown applied to same-run OGR parents."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from ..errors import ReproductionError
from ..io import _sql_path
from .issuer_classifier import CLASSIFICATION_VERSION, OPEN, classify


def select_issuer_facts(entries: pd.DataFrame, route_index: Path, sse_titles: Path, szse_titles: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    parents = entries.copy(); parents["signal_time"] = pd.to_datetime(parents.signal_time); parents["signal_date"] = pd.to_datetime(parents.signal_date).dt.normalize()
    windows = parents[["gap_id", "symbol", "signal_time"]].copy(); windows["window_start"] = windows.signal_time - pd.Timedelta(days=120)
    con = duckdb.connect(); con.register("windows", windows)
    try:
        routes = con.execute(f"""
          SELECT DISTINCT r.* FROM read_parquet('{_sql_path(route_index)}') r
          JOIN windows w ON r.symbol=w.symbol AND r.causal_available_at BETWEEN w.window_start AND w.signal_time
          WHERE r.causal_available_at<TIMESTAMP '2022-01-01'
          ORDER BY r.causal_available_at,r.symbol,r.announcement_key
        """).fetchdf()
        con.register("routes", routes)
        titles = con.execute(f"""
          SELECT r.*,s.title FROM routes r JOIN (
            SELECT * FROM read_parquet('{_sql_path(sse_titles)}') WHERE exchange='SSE'
            UNION ALL BY NAME SELECT * FROM read_parquet('{_sql_path(szse_titles)}') WHERE exchange='SZSE'
          ) s USING(announcement_key)
          ORDER BY r.causal_available_at,r.symbol,r.announcement_key
        """).fetchdf()
    finally:
        con.close()
    if routes.empty or len(routes) != len(titles) or routes.announcement_key.duplicated().any() or titles.announcement_key.duplicated().any():
        raise ReproductionError("IFCGR title route identity failure")
    for column in ("snapshot_id", "raw_record_sha256", "symbol", "exchange"):
        if not routes.set_index("announcement_key")[column].equals(titles.set_index("announcement_key")[column]):
            raise ReproductionError(f"IFCGR title route lineage mismatch: {column}")
    prepared = titles.rename(columns={"available_at": "original_collector_available_at", "published_at": "original_published_at", "precision": "original_precision", "causal_available_at": "available_at"})
    classified = classify(prepared)
    open_events = classified.loc[classified.action.eq(OPEN)].sort_values(["symbol", "available_at", "announcement_key", "risk_family"], kind="mergesort")
    records = []
    for entry in parents.itertuples(index=False):
        start = pd.Timestamp(entry.signal_time) - pd.Timedelta(days=120)
        matched = open_events.loc[open_events.symbol.eq(entry.symbol) & open_events.available_at.ge(start) & open_events.available_at.le(entry.signal_time)]
        payload = [{"announcement_key": str(row.announcement_key), "announcement_id": str(row.announcement_id), "causal_available_at": pd.Timestamp(row.available_at).isoformat(), "risk_family": str(row.risk_family), "matched_rule": str(row.matched_rule)} for row in matched.itertuples(index=False)]
        keys = sorted({x["announcement_key"] for x in payload}); families = sorted({x["risk_family"] for x in payload})
        records.append({"gap_id": entry.gap_id, "v29r2_signal_time_local": entry.signal_time, "v29r2_window_start_at": start, "v29r2_window_end_at": entry.signal_time, "v29r2_coverage_complete": True, "v29r2_open_transition_count": len(payload), "v29r2_open_announcement_count": len(keys), "v29r2_open_announcement_keys": "|".join(keys), "v29r2_open_risk_families": "|".join(families), "v29r2_open_events_json": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), "v29r2_latest_open_causal_available_at": pd.NaT if matched.empty else matched.available_at.max(), "v29r2_issuer_fact_cooldown_gate": not payload, "v29r2_rejection_reason": "" if not payload else "RECENT_HIGH_PRECISION_OPEN_ISSUER_FACT", "v29r2_feature_uses_post_signal_information": False})
    audited = parents.merge(pd.DataFrame(records), on="gap_id", validate="one_to_one")
    if not classified.classification_version.eq(CLASSIFICATION_VERSION).all(): raise ReproductionError("IFCGR classification version drift")
    return audited.loc[audited.v29r2_issuer_fact_cooldown_gate].copy(), audited.loc[~audited.v29r2_issuer_fact_cooldown_gate].copy(), classified
