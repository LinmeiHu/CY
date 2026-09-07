"""Official CNINFO original announcements for missing share-listing dates.

Ex-post execution facts only. No output from this module is an alpha input.
"""
import json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE, sha256

RAW=Path('/Volumes/quant/CY_quant_research/five_strategy_shared_capital_v1/official_ca')

def run():
    p=pd.read_csv(HERE/'output/corporate_action_potential_envelope.csv',dtype={'symbol_action':str})
    needed=p.loc[p.share_multiplier.ne(1)&p.share_credit_date.isna(),['symbol_action','announcement_date','effective_date']].drop_duplicates()
    RAW.mkdir(parents=True,exist_ok=True)
    records=[]
    manifest_path=HERE/'manifests/corporate_action_official_backfill_v1.json'
    previous=json.loads(manifest_path.read_text())['documents'] if manifest_path.exists() else []
    pinned={d['raw_path']:d for d in previous if 'raw_path' in d}
    for symbol,day,ex in needed.itertuples(index=False,name=None):
        search = '嘉宝' if (symbol,day)==('600622','2017-06-23') else '恒生电子' if (symbol,day)==('600570','2021-07-12') else symbol
        query=RAW/f'{symbol}_{day}_{search}_query_v2.json'
        if not query.exists():
            params=dict(pageNum=1,pageSize=30,column='sse',tabName='fulltext',searchkey=search,seDate=f'{day}~{day}',isHLtitle='false')
            if symbol=='600570':
                params.pop('searchkey');params['stock']='600570,gssh0600570'
            subprocess.run(['curl','--compressed','--fail','--max-time','30','-sS','https://www.cninfo.com.cn/new/hisAnnouncement/query','-H','Referer: https://www.cninfo.com.cn/','-d',urlencode(params),'-o',str(query)],check=True)
        data=json.loads(query.read_text())
        matches=[a for a in (data.get('announcements') or []) if a['secCode']==symbol and '权益分派实施公告' in a['announcementTitle']]
        if len(matches)!=1:
            records.append(dict(symbol=symbol,ex_date=ex,status='OFFICIAL_QUERY_NO_UNIQUE_IMPLEMENTATION',query_sha256=sha256(query)));continue
        a=matches[0];url='https://static.cninfo.com.cn/'+a['adjunctUrl'];target=RAW/f'{symbol}_{day}.pdf'
        if not target.exists():subprocess.run(['curl','--compressed','--fail','--max-time','30','-sS',url,'-o',str(target)],check=True)
        if not target.read_bytes().startswith(b'%PDF'):raise ValueError('official response is not PDF')
        if str(target) in pinned and sha256(target)!=pinned[str(target)]['source_hash']:
            raise ValueError('pinned official raw changed; explicit provenance review required')
        textfile=target.with_suffix('.txt')
        if not textfile.exists():
            with textfile.open('w') as f:subprocess.run(['markitdown',str(target)],stdout=f,check=True)
        if str(target) in pinned and 'text_sha256' in pinned[str(target)] and sha256(textfile)!=pinned[str(target)]['text_sha256']:
            raise ValueError('pinned official extraction changed')
        records.append(dict(symbol=symbol,ex_date=ex,source_url=url,document_date=day,source_hash=sha256(target),raw_path=str(target),
            text_path=str(textfile),text_sha256=sha256(textfile),query_path=str(query),query_sha256=sha256(query),retrieved_at=datetime.fromtimestamp(target.stat().st_mtime,timezone.utc).isoformat(),
            source_grade='OFFICIAL_EX_POST_EXECUTION_FACT',status='RAW_SAVED_EXTRACTION_REVIEW_REQUIRED',alpha_use='PROHIBITED'))
        print(symbol,day,ex,url,flush=True)
    (HERE/'manifests').mkdir(exist_ok=True)
    target=HERE/'manifests/corporate_action_official_backfill_v1.json'
    target.write_text(json.dumps(dict(version='V1',scope='Missing tradable dates in verified holds plus conservative potential envelope; not a full actual-hold census',documents=records),ensure_ascii=False,indent=2)+'\n')
    return records

if __name__=='__main__':run()
