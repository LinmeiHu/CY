"""Fail-closed validation for the causal research path (legacy bytes preserved)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from five_strategy_bundle.compare import compare_parquet as core_compare


def require_keys(frame, keys, label):
    if not keys or not set(keys).issubset(frame):
        raise ValueError(f"{label}: missing primary key")
    if frame[keys].isna().any(axis=None):
        raise ValueError(f"{label}: null primary key")
    if frame.duplicated(keys).any():
        raise ValueError(f"{label}: duplicate primary key")


def compare_parquet(actual, golden, identity, values=(), *, atol=0.0):
    keys, values = list(identity), list(values)
    try:
        a = pd.read_parquet(actual, columns=keys + values)
        g = pd.read_parquet(golden, columns=keys + values)
        require_keys(a, keys, "actual")
        require_keys(g, keys, "golden")
        if len(a) != len(g):
            raise ValueError(f"row count mismatch: {len(a)} != {len(g)}")
        result = core_compare(Path(actual), Path(golden), keys, values, atol=atol)
        if result["identity_match_count"] != len(a):
            result["status"] = "FAIL"
        return result
    except (ValueError, KeyError, OSError) as exc:
        return {"status": "FAIL", "first_difference": str(exc)}


def compare_layers(specs):
    """Every supplied spec is required, including its actual and golden paths."""
    if not specs:
        return pd.DataFrame([{"layer": "REQUIRED_LAYERS", "status": "FAIL", "first_difference": "no required layers"}])
    rows = []
    for spec in specs:
        row = compare_parquet(spec["actual"], spec["golden"], spec["keys"], spec.get("values", []), atol=spec.get("atol", 0.0))
        rows.append({"layer": spec["layer"], **row})
    return pd.DataFrame(rows)


def account_validation(frame, expected_dates=None, *, keys=("trade_date",), tolerance=1e-8):
    """Use event keys for checkpoints; a calendar is required for a complete audit."""
    try:
        require_keys(frame, list(keys), "account")
        fields = ["cash", "gross_exposure", "nav"]
        if frame.empty or not set(fields).issubset(frame):
            raise ValueError("empty account or missing values")
        numbers = frame[fields].to_numpy(dtype=float)
        if not np.isfinite(numbers).all():
            raise ValueError("nonfinite account values")
        if (frame.nav <= 0).any() or (frame.cash < -tolerance).any() or (frame.gross_exposure < 0).any():
            raise ValueError("invalid NAV/cash/exposure")
        if (frame.gross_exposure > frame.nav + tolerance).any():
            raise ValueError("financed exposure")
        if not np.allclose(frame.nav, frame.cash + frame.gross_exposure, atol=tolerance, rtol=0):
            raise ValueError("account equation")
        dates = pd.to_datetime(frame.trade_date)
        if dates.isna().any():
            raise ValueError("invalid date")
        if expected_dates is None:
            return {"status": "UNKNOWN", "reason": "required trading calendar not supplied"}
        expected = pd.DatetimeIndex(expected_dates)
        if expected.has_duplicates or expected.hasnans or set(dates) != set(expected):
            raise ValueError("missing or extra required trading-date state")
        if "account_id" in keys:
            for _, account in frame.groupby("account_id", dropna=False):
                if set(pd.to_datetime(account.trade_date)) != set(expected):
                    raise ValueError("missing required account-date state")
        return {"status": "PASS", "reason": "finite unique complete account states"}
    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "FAIL", "reason": str(exc)}


def validation_status(generation, comparison, causal, account):
    states = dict(zip(("GENERATION_STATUS", "COMPARISON_STATUS", "CAUSAL_VALIDATION_STATUS", "ACCOUNT_VALIDATION_STATUS"), (generation, comparison, causal, account)))
    states["status"] = "VALIDATED" if all(v == "PASS" for v in states.values()) else "NOT_VALIDATED"
    return states


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args(argv)
    table = compare_layers(json.loads(args.spec.read_text()))
    print(table.to_json(orient="records"))
    return 0 if table.status.eq("PASS").all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
