"""Create a compact audit package with representative account bytes."""
import argparse,csv,hashlib,io,json,subprocess,zipfile
from pathlib import Path
import pandas as pd
from .common import HERE,OUT,V3,V4,sha,dump

REP={'BASE_T1':V3/'A_D08_C_10_E10','FIXED_T2':V3/'B_D08_C_10_DELAY1','E3_QUARTER':OUT/'accounts/E3_QUARTER_BAND_C10_E10_CA','E3_QUARTER_S1':OUT/'accounts/E3_QUARTER_S1_C10_E10'}

def manifest():
    rows=[]
    for key,path in REP.items():
        assert len(pd.read_parquet(path/'nav.parquet'))==970
        for p in sorted(path.iterdir()):
            if p.is_file():rows.append(dict(account=key,path=str(p),bytes=p.stat().st_size,sha256=sha(p)))
    pd.DataFrame(rows).to_csv(HERE/'ACCOUNT_ARTIFACT_MANIFEST.csv',index=False)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest-only',action='store_true');args=ap.parse_args();manifest()
    if args.manifest_only:return
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip();dest=Path('/Users/linmei/Downloads')/f'USIC_V5_D08入场时点研究审核包_{head[:10]}.zip';files={}
    def add(path,name):
        p=Path(path)
        if p.is_file():files[name]=p
    for p in HERE.iterdir():add(p,'research/'+p.name)
    for name in ['event_timeline.parquet','matched_all_events.parquet','matched_common_trades.parquet'] :add(OUT/name,'diagnostics/'+name)
    for p in OUT.glob('*.log'):add(p,'logs/'+p.name)
    for p in (OUT/'official_ca').glob('*'):add(p,'official_ca/'+p.name)
    for key,path in REP.items():
        for p in path.iterdir():add(p,'accounts/'+key+'/'+p.name)
    for p in (OUT/'accounts').glob('*/result.json'):add(p,'attempts/'+p.parent.name+'/result.json')
    add(V4/'handoff/reference/V3_REPORT.md','reference/V3_REPORT.md');add(Path('/Users/linmei/Documents/CY-worktrees/usic-market-router-v4-20260908/research/usic_market_router_v4/REPORT.md'),'reference/V4_REPORT.md')
    included=set(files.values());omitted=[]
    for p in OUT.rglob('*'):
        if p.is_file() and p not in included and p.name not in ['DELIVERY_STATUS.json','PACKAGE_CHECK.json']:omitted.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)))
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=['path','bytes','sha256']);w.writeheader();w.writerows(omitted)
    extras={'OMITTED_BYTES.csv':buf.getvalue().encode(),'README.md':b'Read research/REPORT.md first. Four representative accounts include complete input, NAV, orders, trades, audit, holdings, open positions, result and identity where applicable. No raw market matrix or sealed data is included.\n'}
    rows=[dict(path=n,bytes=p.stat().st_size,sha256=sha(p)) for n,p in files.items()]+[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in extras.items()]
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for n,p in files.items():z.write(p,n)
        for n,b in extras.items():z.writestr(n,b)
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(rows,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for r in rows:
            b=z.read(r['path']);assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']
    dump(OUT/'PACKAGE_CHECK.json',dict(path=str(dest),sha256=sha(dest),bytes=dest.stat().st_size,files_verified=len(rows),representative_accounts=list(REP),omitted_files=len(omitted),all_passed=True,commit=head));print(dest)

if __name__=='__main__':main()
