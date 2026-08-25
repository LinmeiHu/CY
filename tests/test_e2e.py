from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from cyq_game.cli import main
from cyq_game.data import EventStore, replay_state


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_demo_activation(
    root: Path,
    *,
    bars: Path,
    industries: Path,
    fundamentals: Path,
) -> tuple[Path, Path]:
    registry_path = root / "registry.json"
    assets = [
        ("DEMO-BARS", "market_bars_daily", bars),
        ("DEMO-INDUSTRIES", "industry_memberships", industries),
        ("DEMO-FUNDAMENTALS", "fundamentals", fundamentals),
    ]
    registry_path.write_text(
        json.dumps(
            {
                "registry_id": "CYQ-E2E-DEMO-1",
                "global_gate": {
                    "strict_archival_pit_ready": False,
                    "free_causal_research_ready": False,
                    "backtest_authorized": False,
                },
                "assets": [
                    {
                        "asset_id": asset_id,
                        "name": asset_id.lower(),
                        "kind": kind,
                        "status": "DEMO_ONLY",
                        "pit_grade": "TEST",
                        "physical_state": "MATERIALIZED",
                        "location": str(path),
                        "source": "synthetic-demo",
                        "lineage": {},
                    }
                    for asset_id, kind, path in assets
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    registry_sha256 = _sha256(registry_path)
    manifest_path = root / "input-manifest.json"
    bindings = [
        ("daily_bars", "DEMO-BARS", bars, "demo-bars-v1"),
        ("industry_memberships", "DEMO-INDUSTRIES", industries, "demo-industry-v1"),
        (
            "fundamentals",
            "DEMO-FUNDAMENTALS",
            fundamentals,
            "demo-fundamentals-v1",
        ),
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_id": "CYQ-E2E-DEMO-SNAPSHOT-1",
                "registry_id": "CYQ-E2E-DEMO-1",
                "registry_sha256": registry_sha256,
                "purpose": "SOFTWARE_TEST",
                "hard_valid": True,
                "scope": {"start": "2024-01-02", "end": "2024-06-28"},
                "bindings": [
                    {
                        "role": role,
                        "asset_id": asset_id,
                        "path": str(path),
                        "source": "synthetic-demo",
                        "snapshot_id": snapshot_id,
                        "available_at_policy": "explicit record timestamp",
                        "sha256": _sha256(path),
                    }
                    for role, asset_id, path, snapshot_id in bindings
                ],
                "audits": {
                    name: {
                        "status": "PASS",
                        "evidence": f"software-test:{name}",
                    }
                    for name in (
                        "coverage",
                        "duplicates",
                        "time_travel",
                        "consistency",
                        "cross_table",
                    )
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return registry_path, manifest_path


def test_cli_build_backtest_and_deterministic_replay(tmp_path: Path) -> None:
    csv_path = tmp_path / "demo.csv"
    industry_path = tmp_path / "industries.csv"
    fundamental_path = tmp_path / "fundamentals.csv"
    database = tmp_path / "pit.sqlite3"
    run_dir = tmp_path / "runs"
    config_path = tmp_path / "research.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "mode": "research",
                "database_path": str(database),
                "event_store_path": str(run_dir / "events.jsonl"),
                "run_dir": str(run_dir),
                "seed": 7,
                "live_trading_enabled": False,
                "initial_cash": 1_000_000,
                "benchmark": "000985.CSI",
                "backtest": {
                    "final_holdout_fraction": 0.20,
                    "purge_days": 5,
                    "embargo_days": 5,
                    "allow_holdout_access": False,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "generate-demo",
            "--output",
            str(csv_path),
            "--industry-output",
            str(industry_path),
            "--fundamental-output",
            str(fundamental_path),
            "--start",
            "2024-01-02",
            "--end",
            "2024-06-28",
            "--seed",
            "7",
        ]
    ) == 0
    registry_path, manifest_path = _write_demo_activation(
        tmp_path,
        bars=csv_path,
        industries=industry_path,
        fundamentals=fundamental_path,
    )
    assert main(
        [
            "build-pit",
            "--input",
            str(csv_path),
            "--start",
            "2024-01-02",
            "--end",
            "2024-06-28",
            "--config",
            str(config_path),
            "--registry",
            str(registry_path),
            "--input-manifest",
            str(manifest_path),
            "--software-test",
            "--industry-memberships",
            str(industry_path),
            "--fundamentals",
            str(fundamental_path),
        ]
    ) == 0
    assert main(
        [
            "backtest",
            "--config",
            str(config_path),
            "--strategy",
            "cyq_game_v5",
            "--registry",
            str(registry_path),
            "--input-manifest",
            str(manifest_path),
            "--software-test",
            "--walk-forward",
            "--final-holdout-locked",
            "--run-id",
            "smoke",
        ]
    ) == 0
    assert main(
        ["replay", "--run-id", "smoke", "--deterministic", "--config", str(config_path)]
    ) == 0
    assert main(
        [
            "backtest",
            "--config",
            str(config_path),
            "--registry",
            str(registry_path),
            "--input-manifest",
            str(manifest_path),
            "--software-test",
            "--walk-forward",
            "--final-holdout-locked",
            "--history-start",
            "2024-01-02",
            "--start",
            "2024-04-01",
            "--end",
            "2024-06-28",
            "--run-id",
            "pre-roll-smoke",
        ]
    ) == 0
    pre_roll_dir = run_dir / "pre-roll-smoke"
    pre_roll_summary = json.loads(
        (pre_roll_dir / "summary.json").read_text(encoding="utf-8")
    )
    pre_roll_decisions = [
        json.loads(line)
        for line in (pre_roll_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert pre_roll_summary["history_start"] == "2024-01-02"
    assert pre_roll_summary["evaluation_start"] == "2024-04-01"
    assert pre_roll_decisions
    assert min(row["trade_date"] for row in pre_roll_decisions) >= "2024-04-01"
    assert all(row["order_generation_reason"] != "CHIP_WARMUP" for row in pre_roll_decisions)
    assert main(
        [
            "robustness",
            "--config",
            str(config_path),
            "--registry",
            str(registry_path),
            "--input-manifest",
            str(manifest_path),
            "--software-test",
            "--final-holdout-locked",
            "--run-id",
            "robustness-smoke",
        ]
    ) == 0

    artifact_dir = run_dir / "smoke"
    summary = json.loads((artifact_dir / "summary.json").read_text(encoding="utf-8"))
    diagnostics = json.loads(
        (artifact_dir / "research_diagnostics.json").read_text(encoding="utf-8")
    )
    assert summary["holdout_tainted"] is False
    assert summary["final_holdout_accessed"] is False
    decisions = [
        json.loads(line)
        for line in (artifact_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {row["industry"] for row in decisions} == {
        "DEMO-INDUSTRIAL",
        "DEMO-TECH",
    }
    assert all(row["sector_alpha_enabled"] is False for row in decisions)
    assert all(
        row["sector_sizing_confidence"] == row["sector_state"]["reliability"]
        for row in decisions
    )
    assert all(row["fundamental_coverage"] == 1.0 for row in decisions)
    assert all(row["fundamental_source"] == "synthetic-demo" for row in decisions)
    assert all(row["fundamental_snapshot_id"] for row in decisions)
    assert all(row["fundamental_state"]["composite"] > 0.0 for row in decisions)
    assert diagnostics["methodology"].startswith("development-sample")
    robustness = json.loads(
        (run_dir / "robustness-smoke" / "robustness.json").read_text(encoding="utf-8")
    )
    assert robustness["variant_count"] == 7
    assert robustness["final_holdout_locked"] is True
    assert all(row["status"] == "COMPLETE" for row in robustness["variants"])
    assert all(not row["holdout_tainted"] for row in robustness["variants"])
    assert all(
        Path(row["run_dir"], "summary.json").is_file()
        for row in robustness["variants"]
    )

    shadow_config_path = tmp_path / "shadow.yaml"
    shadow_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    shadow_config["mode"] = "shadow"
    shadow_config["shadow"] = {
        "cash_tolerance": 0.01,
        "quantity_tolerance": 0,
        "max_snapshot_age_seconds": 60,
    }
    shadow_config_path.write_text(
        yaml.safe_dump(shadow_config, sort_keys=True), encoding="utf-8"
    )
    replayed = replay_state(EventStore(artifact_dir / "events.jsonl").read_all())
    checked_at = datetime(2026, 8, 18, 8, tzinfo=UTC)

    def account_payload(snapshot_id: str, cash: float) -> dict[str, object]:
        positions = dict(replayed["final_positions"])
        available = dict(replayed["final_available_quantities"])
        return {
            "as_of": checked_at.isoformat(),
            "source": "read-only-test-export",
            "snapshot_id": snapshot_id,
            "cash": cash,
            "positions": {
                symbol: {
                    "quantity": quantity,
                    "available_quantity": available[symbol],
                    "frozen_quantity": quantity - available[symbol],
                }
                for symbol, quantity in positions.items()
            },
        }

    account_path = tmp_path / "account.json"
    account_path.write_text(
        json.dumps(account_payload("account-pass", float(replayed["final_cash"]))),
        encoding="utf-8",
    )
    assert main(
        [
            "shadow-reconcile",
            "--config",
            str(shadow_config_path),
            "--run-id",
            "smoke",
            "--account-snapshot",
            str(account_path),
            "--checked-at",
            checked_at.isoformat(),
        ]
    ) == 0

    account_path.write_text(
        json.dumps(account_payload("account-fail", float(replayed["final_cash"]) + 1.0)),
        encoding="utf-8",
    )
    reconcile_args = [
        "shadow-reconcile",
        "--config",
        str(shadow_config_path),
        "--run-id",
        "smoke",
        "--account-snapshot",
        str(account_path),
        "--checked-at",
        checked_at.isoformat(),
    ]
    assert main(reconcile_args) == 4
    assert main(
        [
            "kill-switch-status",
            "--config",
            str(shadow_config_path),
            "--run-id",
            "smoke",
        ]
    ) == 4
    assert main(
        [
            "kill-switch-reset",
            "--config",
            str(shadow_config_path),
            "--run-id",
            "smoke",
            "--approval-id",
            "TEST-APPROVAL",
            "--reason",
            "test evidence reviewed",
            "--released-at",
            checked_at.isoformat(),
        ]
    ) == 0
    assert main(
        [
            "kill-switch-status",
            "--config",
            str(shadow_config_path),
            "--run-id",
            "smoke",
        ]
    ) == 0
