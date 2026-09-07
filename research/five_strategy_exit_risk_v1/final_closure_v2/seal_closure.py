"""Focused validation, report, and a non-self-referential deliverable manifest."""
import json
import os
import subprocess
import sys
from pathlib import Path
from run_closure import HERE,ROOT,sha,write_json
from build_report import run as report

def run():
    env=dict(os.environ,PYTHONPATH='src')
    command=[sys.executable,'-m','pytest','-q','tests/unit/test_smv6.py',str(HERE/'tests/test_closure.py')]
    result=subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True)
    (HERE/'validation.txt').write_text('COMMAND: PYTHONPATH=src '+' '.join(command)+'\n\n'+result.stdout+result.stderr)
    print(result.stdout+result.stderr)
    assert result.returncode==0
    report()
    cfg=json.loads((HERE/'run_config.json').read_text());out=Path(cfg['external_root'])
    external={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name not in ['output_manifest.sha256','closure_external_hashes.json']}
    write_json(out/'closure_external_hashes.json',external)
    write_json(HERE/'external_output_manifest.json',dict(path=str(out/'closure_external_hashes.json'),sha256=sha(out/'closure_external_hashes.json'),files=len(external)))
    files=[p for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='output_manifest.sha256']
    (HERE/'output_manifest.sha256').write_text(''.join(f'{sha(p)}  {p.relative_to(HERE)}\n' for p in files))

if __name__=='__main__':run()
