import runpy
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_current_daily_pit_b.py"
MODULE = runpy.run_path(str(SCRIPT))


def test_daily_partition_root_accepts_frozen_asset_wrapper(tmp_path: Path) -> None:
    wrapped = tmp_path / "wrapped"
    (wrapped / "daily").mkdir(parents=True)
    direct = tmp_path / "direct"
    direct.mkdir()

    resolve = MODULE["_daily_partition_root"]
    assert resolve({"location": str(wrapped)}) == wrapped / "daily"
    assert resolve({"location": str(direct)}) == direct
