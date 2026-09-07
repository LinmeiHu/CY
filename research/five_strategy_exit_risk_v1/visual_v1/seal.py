"""Validate and hash the bounded research deliverable; never alters parent inputs."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import zipfile
from packets import HERE, PARENT, OUT, OLD, digest, write_json, pd
from quantify import check_freeze


def run():
    root=PARENT.parents[1]
    check_freeze()
    parent=json.loads((PARENT/'completion_manifest.json').read_text())
    inputs=json.loads((PARENT/'input_and_exposure_manifest.json').read_text())
    checks=[]
    for kind,items,base in [('PARENT_RESEARCH',parent['research_files'],PARENT),
                           ('FROZEN_PRODUCTION',inputs['frozen_hashes'],root),
                           ('PARENT_EXTERNAL',inputs['artifacts'],OLD)]:
        for name,info in items.items():
            expected=info if isinstance(info,str) else info['sha256'];actual=digest(base/name)
            checks.append(dict(kind=kind,path=str(base/name),expected_sha256=expected,actual_sha256=actual,unchanged=actual==expected))
            assert actual==expected,(kind,name)
    pd.DataFrame(checks).to_csv(HERE/'input_integrity_audit.csv',index=False)
    command=['/opt/anaconda3/bin/python3','-m','pytest','-q','tests/unit',
        'research/five_strategy_exit_risk_v1/test_v2.py','research/five_strategy_exit_risk_v1/visual_v1/test_visual.py',
        'research/five_strategy_exit_risk_v1/visual_v1/test_risk_review.py']
    import os
    env=os.environ.copy();env['PYTHONPATH']='src'
    result=subprocess.run(command,cwd=root,env=env,text=True,capture_output=True)
    (HERE/'validation.txt').write_text('COMMAND: PYTHONPATH=src '+' '.join(command)+'\n\n'+result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    assert '43 passed' in result.stdout
    risk=json.loads((OUT/'risk_preference_review/completed.json').read_text())
    assert risk['account_replays']==20
    render=pd.read_csv(HERE/'visual_render_manifest.csv')
    assert len(render)==74 and int(render.actually_viewed_by_astra.sum())==39
    exposure=pd.read_csv(HERE/'visual_exposure_manifest.csv')
    for row in exposure.loc[exposure.image_sha256.notna()].itertuples(index=False):
        assert digest(row.image_path)==row.image_sha256,row.image_path
    candidates=json.loads((HERE/'risk_candidates.json').read_text())
    stages=[json.loads(x) for x in (HERE/'visual_stage_audit.jsonl').read_text().splitlines()]
    frozen=next(x for x in stages if x['action']=='SIMPLE_RISK_CHOICES_FROZEN_BEFORE_COUNTEREXAMPLE_IMAGES')
    assert digest(HERE/'risk_candidates.json')==frozen['sha256']
    external={}
    excluded={'artifact_hash_index.json','visual_v1_source_package.zip','visual_v1_source_package.sha256','delivery_receipt.json'}
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.name not in excluded:
            external[str(path.relative_to(OUT))]=dict(bytes=path.stat().st_size,sha256=digest(path))
    write_json(OUT/'artifact_hash_index.json',dict(recorded_at=datetime.now().astimezone().isoformat(),files=external,
        exclusions=sorted(excluded),reason='Index self-reference and separately hashed final source package/receipt'))
    files={}
    for path in sorted(HERE.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.name!='completion_manifest.json':
            files[str(path.relative_to(HERE))]=dict(bytes=path.stat().st_size,sha256=digest(path))
    manifest=dict(run_id='20260907_visual_v1_01',recorded_at=datetime.now().astimezone().isoformat(),
        task_status='MULTIMODAL_AND_RISK_REVIEW_COMPLETE_WITH_KNOWN_ATRDR_QUARANTINE',
        start_head='1628f14a3949244998e0223cc0f419a00e66c856',branch='research/five-strategy-exit-risk-v1',
        baseline_head=inputs['baseline_head'],production_modified=False,new_sealed_validation_opened=False,
        evidence='CASE_BLINDED_CONDITIONAL_ON_PRIOR_RESULT_EXPOSURE; risk preference revised after exposure',
        tests='43 passed',test_command='PYTHONPATH=src '+' '.join(command),
        parent_unchanged=pd.DataFrame(checks).groupby('kind').size().to_dict(),
        account_replays=20,no_financing='PASS',research_prefix_tests='PASS',production_atrdr_prefix='FAIL_KNOWN_QUARANTINED',
        visual_motifs=10,visual_motifs_computed=4,robust_visual_state_features=0,visual_mechanism_candidates=0,
        packet_images=74,actually_viewed_packet_images=39,aggregate_figures_reviewed=2,case_manifest_entries=115,
        research_shortlist=['MCB:profit_0','OGR:atr_1'],inherited_limited=['IFCGR:atr_1'],
        quarantined_conditional=['ATRDR_FAST_BEAR:fixed_0.05'],
        external_root=str(OUT),external_index_sha256=digest(OUT/'artifact_hash_index.json'),
        external_files=len(external),research_files=files,
        caveat='Research completion is not five-strategy production readiness. Source provenance and known execution limitations remain explicit.')
    write_json(HERE/'completion_manifest.json',manifest)
    package=OUT/'visual_v1_source_package.zip'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(HERE.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:z.write(path,'visual_v1/'+str(path.relative_to(HERE)))
    with zipfile.ZipFile(package) as z:assert z.testzip() is None
    (OUT/'visual_v1_source_package.sha256').write_text(digest(package)+'  '+package.name+'\n')
    print(json.dumps(dict(verified_inputs=len(checks),tests='43 passed',small_files=len(files)+1,external_files=len(external),
        packet_images=74,viewed_images=39,accounts=20,package=str(package)),ensure_ascii=False))


if __name__=='__main__':run()
