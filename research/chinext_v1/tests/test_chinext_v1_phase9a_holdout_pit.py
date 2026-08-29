import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_holdout_2022_2023_master_manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_holdout_identity_and_no_replay():
    d = load_manifest()
    assert d["purpose"] == "CHINEXT_V1_TEMPORAL_HOLDOUT_PIT_2022_2023"
    assert d["date_range"] == ["2022-01-04", "2023-12-29"]
    assert d["warmup_start_required"] == "2021-07-08"
    assert d["trade_date_count"] == 484
    assert d["current_survivor_used"] is False
    assert d["governance"]["formal_strategy_replay_executions"] == 0
    assert d["governance"]["strategy_results_used"] is False


def test_holdout_artifacts_and_snapshot_audits():
    d = load_manifest()
    for item in d["artifacts"].values():
        path = Path(item["path"])
        assert path.is_file()
        assert sha256(path) == item["sha256"]
    expected = {
        "2022-01-04": (1090, "c8fef6d6439ea6b3fd798e0282d8db725c412661132df2b0c910dc67a7b9aadb"),
        "2022-06-30": (1154, "80b74860c2b2644ad8dbfa507051d1360b8e9829f0fd045eaa0c46ea48e3eae2"),
        "2023-01-03": (1232, "c20381eb7959dbd43f3e0c6f95b3f18bd7d2a04c068c046ed3124b48d9f2debd"),
        "2023-06-30": (1282, "68b7e6dccb140fab30e0d754286a09d60ba3faf1215afb65ed3c38397e0a49ed"),
        "2023-12-29": (1333, "b637232bae219e0583e6dc0b563af78311b4fe4757623d1e13daa1283c9adba2"),
    }
    for day, (count, digest) in expected.items():
        row = d["fixed_snapshot_audit_dates"][day]
        assert (row["membership_count"], row["membership_set_sha256"]) == (count, digest)


def test_holdout_pit_cases_and_prior_artifact_unchanged():
    d = load_manifest()
    cases = d["critical_cases"]
    assert all(row["pass"] for row in cases.values() if "pass" in row)
    assert d["holdout_statistics"]["fail_closed_row_count"] == 11904
    assert d["holdout_statistics"]["future_listed_exclusion_count"] == 0
    assert d["prior_2024_2025_artifact_hashes_before_build"][
        str(ROOT / "research/chinext_v1/data/pit_2024_2025/manifest.json")
    ] == "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"
