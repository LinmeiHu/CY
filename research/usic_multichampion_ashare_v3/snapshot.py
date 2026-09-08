"""Verify and copy only authorized, completed V2 input caches; never outcomes."""
import json, shutil, time
from pathlib import Path
from .common import HERE, OUT, CACHE, LEGACY, INV, sha, dump

def main():
    CACHE.mkdir(exist_ok=True)
    invpath = INV/'CY-006-pit-b-daily-v2-2018-2026-20260821.json'
    assert sha(invpath) == 'de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2'
    inv = json.loads(invpath.read_text()); raw = []
    for x in inv['files']:
        year = int(x['path'].split('=')[1][:4])
        if not 2018 <= year <= 2023: continue
        p = Path(inv['root'])/x['path']; assert sha(p) == x['sha256']
        raw.append(dict(path=str(p), sha256=x['sha256']))
    assert len(raw) == 6
    manifest = json.loads((OUT/'inherited/feature_manifest.json').read_text())
    bound = {Path(x['path']).name:x for x in manifest['artifacts']}
    names = sorted(p.name for p in LEGACY.glob('*.npy')) + ['axes.json','market.csv','N_candidates.parquet','N_signals.parquet']
    files = []
    for name in names:
        src, dest = LEGACY/name, CACHE/name
        expected = bound[name]['sha256']
        assert sha(src) == expected, name
        if not dest.exists() or sha(dest) != expected:
            tmp = dest.with_suffix(dest.suffix+'.tmp'); shutil.copyfile(src,tmp)
            assert sha(tmp) == sha(src) == expected, name
            tmp.replace(dest)
        files.append(dict(path=str(dest), source=str(src), sha256=expected))
        print('SNAPSHOT',name,flush=True)
    dump(HERE/'INPUT_MANIFEST.json',dict(raw=raw,cache=files,inventory_sha256=sha(invpath),registry_sha256=sha(HERE.parents[1]/'configs/data_asset_registry.json'),permissions='2018-2019 warmup; 2020-2023 accounts; no post-2023 reads',completed_at=time.time()))

if __name__ == '__main__': main()
