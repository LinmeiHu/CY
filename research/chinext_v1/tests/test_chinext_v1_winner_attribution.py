from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
ATTRIBUTION = REPORTS / "chinext_v1_trade_attribution.csv"
SUMMARY = REPORTS / "chinext_v1_winner_attribution_summary.json"
PHASE1B = REPORTS / "chinext_v1_pit_replay_summary.json"

ALL_TRADE_IDENTITY_SHA256 = "a426c90f6f2dd818559fb29c8a3cc2deb0a9ca201f2dc1fa38dfae1d0a30202c"
TOP20_IDENTITY_SHA256 = "c26be41db07cabe824063afe873055a623263d7f46a49a55bba7dc009ab82283"


def identity_digest(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode()).hexdigest()


def test_frozen_winner_attribution_core_reproduces_phase1b() -> None:
    rows = list(csv.DictReader(ATTRIBUTION.open(encoding="utf-8", newline="")))
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    phase1b = json.loads(PHASE1B.read_text(encoding="utf-8"))

    assert len(rows) == summary["trade_count"] == 111
    assert len({row["trade_id"] for row in rows}) == 111
    assert identity_digest([row["trade_id"] for row in rows]) == ALL_TRADE_IDENTITY_SHA256
    assert Counter(row["winner_group"] for row in rows) == {
        "GROUP_A": 10,
        "GROUP_B": 10,
        "GROUP_C": 91,
    }

    top20 = sorted(rows, key=lambda row: int(row["pnl_rank"]))[:20]
    assert identity_digest([row["trade_id"] for row in top20]) == TOP20_IDENTITY_SHA256
    assert [row["symbol"] for row in top20] == [
        row["symbol"] for row in phase1b["pnl_concentration"]["top20_trades"]
    ]

    concentration = summary["concentration"]
    assert concentration["top1"] == pytest.approx(0.13276317884259606)
    assert concentration["top5"] == pytest.approx(0.4096434064997181)
    assert concentration["top10"] == pytest.approx(0.6230487574354671)
    assert concentration["top20"] == pytest.approx(0.8425435214865872)
    assert concentration["return_ex_best10"] == pytest.approx(0.03609161875000022)
    assert concentration["return_ex_best20"] == pytest.approx(-0.3219529632499998)
    assert summary["right_tail"]["skewness_sample"] == pytest.approx(4.072902711951647)
    assert summary["identity"]["formal_replay_executions_this_phase"] == 0
    assert summary["identity"]["pit_rebuilt"] is False
    assert summary["identity"]["strategy_modified"] is False
