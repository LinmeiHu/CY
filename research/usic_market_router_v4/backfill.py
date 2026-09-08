"""Minimal reuse of completed CY CNINFO implementation-announcement retrieval."""
import subprocess,json,re
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
from .common import HERE,OUT,sha,dump
from ..usic_multichampion_ashare_v3.legacy_replay import load_actions

def fetch():
    gaps=[pd.read_csv(p) for p in list(OUT.glob('accounts/*/action_gaps.csv'))+list(OUT.glob('FIX_*/action_gaps.csv'))+list(OUT.glob('R*/action_gaps.csv'))]
    if not gaps:return
    needed=pd.concat(gaps).drop_duplicates('action_id');actions=load_actions().set_index('event_id');root=OUT/'official_ca';root.mkdir(exist_ok=True)
    manifest=[]
    for g in needed.to_dict('records'):
        a=actions.loc[g['action_id']];symbol=a.symbol;day=str(a.announcement_date.date());query=root/f'{symbol}_{day}.json'
        if not query.exists():
            params=dict(pageNum=1,pageSize=30,column='szse' if symbol.startswith(('00','30')) else 'sse',tabName='fulltext',searchkey=symbol,seDate=f'{day}~{day}',isHLtitle='false')
            subprocess.run(['curl','--compressed','--fail','--max-time','30','-sS','https://www.cninfo.com.cn/new/hisAnnouncement/query','-H','Referer: https://www.cninfo.com.cn/','-d',urlencode(params),'-o',str(query)],check=True)
        data=json.loads(query.read_text())
        if not data.get('announcements') and symbol.startswith('60'):
            params=dict(pageNum=1,pageSize=30,column='sse',tabName='fulltext',searchkey={'603392':'万泰生物','603466':'风语筑','603319':'湘油泵','600845':'宝信软件'}.get(symbol,symbol),seDate=f'{(pd.Timestamp(day)-pd.Timedelta(days=1)).date()}~{day}',isHLtitle='false')
            query=root/f'{symbol}_{day}_name_range_v3.json'
            if not query.exists():subprocess.run(['curl','--compressed','--fail','--max-time','30','-sS','https://www.cninfo.com.cn/new/hisAnnouncement/query','-H','Referer: https://www.cninfo.com.cn/','-d',urlencode(params),'-o',str(query)],check=True)
            data=json.loads(query.read_text())
        matches=[x for x in (data.get('announcements') or []) if x['secCode']==symbol and any(k in x['announcementTitle'] for k in ['权益分派实施公告','权益分配实施公告','利润分配实施公告'])]
        if len(matches)!=1:print('NO_UNIQUE',symbol,day,[x['announcementTitle'] for x in (data.get('announcements') or [])]);continue
        url='https://static.cninfo.com.cn/'+matches[0]['adjunctUrl'];pdf=root/f'{symbol}_{day}.pdf';txt=pdf.with_suffix('.txt')
        if not pdf.exists():subprocess.run(['curl','--fail','--max-time','30','-sS',url,'-o',str(pdf)],check=True)
        assert pdf.read_bytes().startswith(b'%PDF')
        if not txt.exists():
            with txt.open('w') as f:subprocess.run(['bash','/Users/linmei/.codex/skills/markitdown/scripts/markitdown.sh','-S',str(pdf)],stdout=f,check=True)
        text=txt.read_text();flat=re.sub(r'\s+','',text)
        for pat in ['可流通','上市日','上市流通','新增可','转增股份','起始交易日']:
            for x in re.finditer(pat,flat):print(symbol,day,pat,flat[max(0,x.start()-60):x.start()+120],flush=True)
        manifest.append(dict(action_id=g['action_id'],symbol=symbol,document_date=day,effective_date=str(a.effective_date.date()),source_url=url,raw_path=str(pdf),raw_hash=sha(pdf),text_path=str(txt),text_hash=sha(txt),query_hash=sha(query),alpha_use='PROHIBITED',grade='OFFICIAL_EX_POST_EXECUTION_FACT'))
    previous=json.loads((HERE/'official_sources.json').read_text()) if (HERE/'official_sources.json').exists() else []
    merged={x['action_id']:x for x in previous+manifest};dump(HERE/'official_sources.json',list(merged.values()))
if __name__=='__main__':fetch()
