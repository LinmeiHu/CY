"""Record actual checks and package large, reproducible result tables."""
import gzip
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd
from .audit import HERE,sha256,write_json
from . import report_v2


def tracked_outputs():
    return {str(p.relative_to(HERE)):sha256(p) for p in sorted(HERE.rglob('*')) if p.is_file() and 'cache' not in p.relative_to(HERE).parts and '__pycache__' not in p.parts and p.suffix not in ['.log','.xml','.pyc'] and p.name not in ['.DS_Store','output_manifest.sha256','render_determinism.csv']}


def package():
    ignore=HERE/'.gitignore';lines=ignore.read_text().splitlines();rows=[]
    previous_path=HERE/'output/compressed_artifacts.json'
    previous={r['csv']:r for r in json.loads(previous_path.read_text())} if previous_path.exists() else {}
    if '.DS_Store' not in lines:lines.append('.DS_Store')
    for p in sorted((HERE/'output').glob('*.csv')):
        if p.stat().st_size<20_000_000:continue
        local=str(p.relative_to(HERE));digest=sha256(p)
        prior=previous.get(local)
        if prior and prior['csv_sha256']==digest and all((HERE/r['path']).exists() and sha256(HERE/r['path'])==r['sha256'] for r in prior['archives']):
            rows.append(prior)
            if local not in lines:lines.append(local)
            continue
        dest=p.with_suffix('.csv.gz')
        with p.open('rb') as src,dest.open('wb') as raw:
            with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=6) as compressed:shutil.copyfileobj(src,compressed)
        local=str(p.relative_to(HERE))
        if local not in lines:lines.append(local)
        archives=[dest]
        if dest.stat().st_size>90_000_000:
            archives=[]
            with dest.open('rb') as stream:
                i=0
                while block:=stream.read(80_000_000):
                    part=Path(str(dest)+f'.part{i:03d}');part.write_bytes(block);archives.append(part);i+=1
            name=str(dest.relative_to(HERE))
            if name not in lines:lines.append(name)
        rows.append(dict(csv=local,csv_sha256=sha256(p),csv_bytes=p.stat().st_size,archives=[dict(path=str(x.relative_to(HERE)),sha256=sha256(x)) for x in archives]))
    ignore.write_text('\n'.join(lines)+'\n');write_json(HERE/'output/compressed_artifacts.json',rows)


def verify_archives():
    rows=[]
    for item in json.loads((HERE/'output/compressed_artifacts.json').read_text()):
        compressed=HERE/(item['csv']+'.gz')
        if len(item['archives'])>1:
            assembled=hashlib.sha256()
            for part in item['archives']:
                with (HERE/part['path']).open('rb') as stream:
                    while block:=stream.read(1024*1024):assembled.update(block)
            assert assembled.hexdigest()==sha256(compressed)
        observed=hashlib.sha256()
        with gzip.open(compressed,'rb') as stream:
            while block:=stream.read(1024*1024):observed.update(block)
        assert observed.hexdigest()==item['csv_sha256']==sha256(HERE/item['csv'])
        rows.append(dict(csv=item['csv'],csv_sha256=item['csv_sha256'],archive_parts=len(item['archives']),decompression_status='PASS'))
    pd.DataFrame(rows).to_csv(HERE/'output/compressed_artifact_verification.csv',index=False)


def main():
    cases=[]
    for case in ET.parse(HERE/'output/tests_v2.xml').getroot().iter('testcase'):
        status='SKIPPED' if case.find('skipped') is not None else 'PASS'
        if case.find('failure') is not None or case.find('error') is not None:status='FAIL'
        cases.append(dict(name=case.attrib['classname']+'::'+case.attrib['name'],status=status))
    assert cases and not any(c['status']=='FAIL' for c in cases)
    primary_passed=sum(c['status']=='PASS' for c in cases);primary_skipped=sum(c['status']=='SKIPPED' for c in cases)
    supplemental=HERE/'output/registered_mcb_test.xml'
    assert supplemental.exists()
    supplemental_passed=0
    for node in ET.parse(supplemental).getroot().iter('testcase'):
        assert node.find('failure') is None and node.find('error') is None and node.find('skipped') is None
        name=node.attrib['classname']+'::'+node.attrib['name']
        matches=[c for c in cases if c['name']==name]
        assert len(matches)==1 and matches[0]['status']=='SKIPPED'
        matches[0].update(status='PASS',primary_status='SKIPPED',supplemental_evidence='registered_mcb_test.xml; explicit frozen registered input configuration')
        supplemental_passed+=1
    verification=pd.read_csv(HERE/'output/input_hash_verification.csv');assert verification.status.eq('PASS').all()
    actual=pd.read_csv(HERE/'output/continuous_determinism.csv');assert actual.status.eq('PASS').all()
    write_json(HERE/'output/test_results_v2.json',dict(primary_passed=primary_passed,primary_skipped=primary_skipped,supplemental_passed=supplemental_passed,passed=sum(c['status']=='PASS' for c in cases),skipped=sum(c['status']=='SKIPPED' for c in cases),tests=cases,supplemental_command='FIVE_STRATEGY_INPUT_CONFIG=research/five_strategy_exit_risk_v1/input_config.json PYTHONPATH=.:src /opt/anaconda3/bin/python -m pytest -q tests/reproduction/test_mcb_external.py --basetemp=research/scaling_regime_v1/cache/pytest_registered_mcb --junitxml=research/scaling_regime_v1/output/registered_mcb_test.xml',command='PYTHONPATH=.:src /opt/anaconda3/bin/python -m pytest -q tests research --junitxml=research/scaling_regime_v1/output/tests_v2.xml'))
    coverage=[]
    for c in cases:
        if 'scaling_regime_v1' in c['name']:coverage.append(dict(requirement=c['name'].split('::')[-1],test=c['name'],status=c['status'],evidence='Actual tests_v2.xml; account receipts and additive CSV assertions'))
    pd.DataFrame(coverage).to_csv(HERE/'output/requirement_test_coverage.csv',index=False)
    report_v2.run();before=tracked_outputs();report_v2.run();after=tracked_outputs();assert before==after
    pd.DataFrame([dict(path=k,before_sha256=v,after_sha256=after[k],status='PASS',scope='Independent deterministic report regeneration from fixed actual calculated outputs') for k,v in before.items() if k.endswith('.md') or k in ['output/main_question_status_v2.csv','output/final_decision_matrix.csv','output/completion_v2.json']]).to_csv(HERE/'output/render_determinism.csv',index=False)
    package();verify_archives();final=tracked_outputs();final['output/render_determinism.csv']=sha256(HERE/'output/render_determinism.csv')
    (HERE/'output/output_manifest.sha256').write_text(''.join(f'{digest}  {name}\n' for name,digest in sorted(final.items())))
    print('FINAL_RESEARCH_MANIFEST_PASS',len(final),'TESTS',len(cases),flush=True)


if __name__=='__main__':main()
