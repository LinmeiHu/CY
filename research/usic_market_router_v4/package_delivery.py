"""Package representative account bytes and explicitly inventory omitted research files."""
import csv, io, json, subprocess, zipfile
from pathlib import Path
import pandas as pd
from .common import HERE, OUT, V3, sha, dump

SELECTED = [
    'A_H02_C_10_E10', 'A_D05_C_10_E10', 'A_D08_C_10_E10',
    'A_D08_C_MAX_E10', 'A_H01_C_10_E10', 'R0_POOL_C_10',
    'R1_S1_D08_C_10', 'R1_LEVEL_D08_C_10_CA', 'PAST_ONLY_D08_C_10',
    'R1_S1_D08_C_MAX', 'R4_LEVEL_D08_C_10_CA', 'FIX_A_D09_C_MAX_E10',
]

def account_manifest():
    summary=pd.read_csv(HERE/'scenario_summary.csv'); rows=[]
    for r in summary.to_dict('records'):
        if r['status'] not in ['COMPLETED','VERIFIED_REUSE']:continue
        d=Path(r['output'])
        for p in sorted(d.iterdir()):
            if p.is_file():rows.append(dict(id=r['id'],status=r['status'],path=str(p),bytes=p.stat().st_size,sha256=sha(p),included_representative=r['id'] in SELECTED))
    pd.DataFrame(rows).to_csv(HERE/'ACCOUNT_ARTIFACT_MANIFEST.csv',index=False)
    assert summary.id.is_unique
    assert len(summary[(summary.status=='COMPLETED')&(summary.version_family=='V4_NEW')])==48
    assert len(summary[(summary.status=='COMPLETED')&(summary.version_family=='V3_CORRECTION')])==48
    blocked=summary[summary.status=='BLOCKED_INPUT']
    assert len(blocked)==11
    assert all(x in set(summary[summary.status=='COMPLETED'].id) for x in blocked.resolved_by)
    assert not summary.status.isin(['RUNNING','PLANNED_NOT_EXECUTED']).any()
    return summary

def main():
    summary=account_manifest()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip()
    dest=Path('/Users/linmei/Downloads')/f'USIC_V4_研究审核交接包_{head[:10]}.zip'
    files={}
    def add(p,name):
        p=Path(p)
        if p.is_file():files[name]=p
    for p in HERE.iterdir():add(p,'research/usic_market_router_v4/'+p.name)
    for name in ['REPORT.md','REPRODUCTION.md','completion.json','scenario_summary.csv','ACCOUNT_ARTIFACT_MANIFEST.csv']:
        add(HERE/name,name)
    for name in ['state_daily.parquet','confirmation_state_daily.parquet','routing_decisions.parquet','event_cash_diagnostics.parquet','ranking_unique_candidates.parquet','episodes_corrected.parquet','D09_corrected_signals.parquet','Q3_corrected_signals.parquet']:
        add(OUT/name,'data/'+name)
    for p in OUT.glob('events_*.parquet'):add(p,'data/'+p.name)
    for p in (OUT/'attribution').glob('*.parquet'):add(p,'attribution/'+p.name)
    for p in OUT.glob('*.log'):add(p,'logs/'+p.name)
    for p in (OUT/'official_ca').iterdir():add(p,'official_ca/'+p.name)
    for p in (OUT/'handoff'/'reference').iterdir():add(p,'reference/'+p.name)
    for name in ['INPUT_MANIFEST.json','FEATURE_MANIFEST.json','CORE_FREEZE.json','SPEC.md','SEMANTIC_PREFLIGHT.md']:
        add(HERE.parent/'usic_multichampion_ashare_v3'/name,'reference/'+name)
    add(OUT/'DELIVERY_STATUS.json','DELIVERY_STATUS.json')
    for sid in SELECTED:
        r=summary[summary.id==sid].iloc[0];d=Path(r.output)
        assert len(pd.read_parquet(d/'nav.parquet'))==970
        for p in d.iterdir():add(p,'accounts/'+sid+'/'+p.name)
    # All attempt statuses, including historical blocked/invalidated records.
    for p in (OUT/'accounts').glob('*/result.json'):
        add(p,'attempts/'+p.parent.name+'/result.json')
    included=set(files.values());omitted=[]
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p not in included and p.name not in ['DELIVERY_STATUS.json']:
            omitted.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)))
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=['path','bytes','sha256']);w.writeheader();w.writerows(omitted)
    extras={'OMITTED_BYTES.csv':buf.getvalue().encode(), 'README.md':(
        '# USIC V4 审核交接包\n\n先读 REPORT.md，再读 scenario_summary.csv 与 REPRODUCTION.md。\n'
        'accounts 内含12个代表账户的完整实际字节；其中两个开关候选、一个过去信息程序，其他为基线、压力或纠错对照。\n'
        'data 含全十二路线事件诊断、状态、排名与决策记录；不将独立事件收益相加为账户。\n'
        '未复制的V4研究文件见 OMITTED_BYTES.csv，全部完成/复用账户见 ACCOUNT_ARTIFACT_MANIFEST.csv。\n'
        '原始行情矩阵及外部权益依赖不在附件内，输入身份在reference清单；须使用已有授权数据路径。\n'
        '历史阻塞及作废尝试在attempts保留；无新封存样本、无真实下单、无生产修改。\n'
    ).encode()}
    manifest=[dict(path=n,bytes=p.stat().st_size,sha256=sha(p)) for n,p in sorted(files.items())]
    import hashlib
    manifest += [dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in extras.items()]
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,p in sorted(files.items()):z.write(p,name)
        for name,b in extras.items():z.writestr(name,b)
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(manifest)+1
        for r in manifest:
            b=z.read(r['path']);assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    dump(OUT/'PACKAGE_CHECK.json',dict(path=str(dest),sha256=sha(dest),bytes=dest.stat().st_size,files_verified=len(manifest),representative_accounts=SELECTED,omitted_files=len(omitted),omitted_bytes=sum(r['bytes'] for r in omitted),all_passed=True,commit=head))
    print(json.dumps(json.loads((OUT/'PACKAGE_CHECK.json').read_text()),ensure_ascii=False))

if __name__=='__main__':main()
