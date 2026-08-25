#!/usr/bin/env python3
"""Record the user-authorized 2023 outcome read for a diagnostic chartbook."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage

EVENT_TYPE = "OPERATOR_HOLDOUT_ACCESS_OVERRIDE"
PARAMETER_ID = "9baed76ec299161c"
AUTHORIZATION_TEXT = "允许，你画给我吧"


def main() -> int:
    config = MarkupRetestConfig.load(
        "configs/markup_retest_main_chinext_2020_2023_v1.yaml"
    )
    ledger = TrialLedger(config.trial_ledger)
    identity = "|".join(
        (
            EVENT_TYPE,
            config.sha256,
            PARAMETER_ID,
            "2023-01-01/2023-06-16",
            "DIAGNOSTIC_POST_EXIT_CHART_ONLY",
        )
    )
    payload: dict[str, Any] = {
        "event_id": hashlib.sha256(identity.encode()).hexdigest(),
        "status": "USER_AUTHORIZED_OUTCOME_ACCESS",
        "recorded_at": datetime.now().astimezone().isoformat(),
        "config_sha256": config.sha256,
        "parameter_id": PARAMETER_ID,
        "authorization_channel": "CODEX_SIDE_CONVERSATION",
        "authorization_text": AUTHORIZATION_TEXT,
        "requested_use": "DIAGNOSTIC_POST_EXIT_CANDLESTICK_CHARTBOOK",
        "authorized_data_window": {
            "start": "2023-01-01",
            "end": "2023-06-16",
            "symbols": ["300076.SZ"],
        },
        "holdout_accessed": True,
        "holdout_outcomes_observed": True,
        "used_for_parameter_selection_or_thresholds": False,
        "selection_was_frozen_before_access": True,
        "freeze_decision_before_access": "NO_TRADE",
        "retuning_authorized": False,
        "edge_card_authorized": False,
        "kelly_authorized": False,
        "formal_2023_untouched_claim_allowed": False,
        "consequences": [
            "2023_PRICE_OUTCOMES_ARE_NOW_OBSERVED",
            "2023_CANNOT_BE_CLAIMED_AS_UNTOUCHED_HOLDOUT",
            "CHART_OUTCOMES_MAY_NOT_BE_USED_TO_RETUNE_OR_SELECT_PARAMETERS",
            "REPORT_MUST_DISCLOSE_THE_OVERRIDE",
        ],
    }
    entry = _append_idempotent(ledger, payload)
    report = {
        "schema_version": 1,
        "event_type": EVENT_TYPE,
        "ledger_sequence": entry.sequence,
        "payload": payload,
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "holdout_chartbook_access_20260825.json"
    )
    _write_immutable(target, report)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "ledger_sequence": entry.sequence,
                "holdout_outcomes_observed": True,
                "manifest": str(target.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _append_idempotent(
    ledger: TrialLedger, payload: Mapping[str, Any]
):
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != EVENT_TYPE:
            raise ValueError("holdout override event_id collision")
        stable_keys = set(payload) - {"recorded_at"}
        if any(entry.payload.get(key) != payload.get(key) for key in stable_keys):
            raise ValueError("holdout override payload collision")
        return entry
    return ledger.append(EVENT_TYPE, payload)


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing["payload"]["event_id"] != payload["payload"]["event_id"]:
            raise FileExistsError(f"immutable holdout manifest differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
