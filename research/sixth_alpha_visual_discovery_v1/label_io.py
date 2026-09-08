from .build import HERE
import pandas as pd

def open_notes(sheet,notes):
 idx=pd.read_csv(HERE/'visual/contact_sheet_index.csv');ids=idx.loc[idx.stage.eq('open')&idx.sheet.eq(sheet),'blind_id'].tolist();assert len(ids)==len(notes)
 p=HERE/'visual/open_coding_raw_labels.csv';df=pd.DataFrame(dict(blind_id=ids,note=notes,sheet=sheet))
 if p.exists():
  old=pd.read_csv(p);assert not set(ids)&set(old.blind_id);df=pd.concat([old,df])
 df.to_csv(p,index=False)

def formal(sheet,codes):
 import json
 dims=[d['name'] for d in json.loads((HERE/'visual/visual_codebook_v1.json').read_text())['dimensions']]
 idx=pd.read_csv(HERE/'visual/contact_sheet_index.csv');ids=idx.loc[idx.stage.eq('formal')&idx.sheet.eq(sheet),'blind_id'].tolist();codes=codes.split();assert len(ids)==len(codes),(sheet,len(ids),len(codes))
 rows=[]
 for bid,code in zip(ids,codes):
  assert len(code)==len(dims) and set(code)<=set('01234x'),code
  rows.append(dict(blind_id=bid,sheet=sheet,**{d:(None if x=='x' else int(x)-2) for d,x in zip(dims,code)}))
 p=HERE/'visual/formal_visual_labels.csv';df=pd.DataFrame(rows)
 if p.exists():
  old=pd.read_csv(p);assert not set(ids)&set(old.blind_id);df=pd.concat([old,df])
 df.to_csv(p,index=False)
