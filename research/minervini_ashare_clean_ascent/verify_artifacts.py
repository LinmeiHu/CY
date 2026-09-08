"""Read-only identity check. Never regenerates an expected hash after failure."""
import json
from pathlib import Path
from .common import HERE,sha

def run():
    manifest=json.loads((HERE/'artifact_manifest.json').read_text());count=0
    for section in ['inputs','sources','outputs']:
        for r in manifest[section]:
            p=Path(r['path']);assert p.exists(),str(p);assert sha(p)==r['sha256'],str(p);count+=1
    print('ARTIFACT_IDENTITY_PASS',count,'files')
if __name__=='__main__':run()
