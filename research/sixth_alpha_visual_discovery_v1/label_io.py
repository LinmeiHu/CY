from .build import HERE
import pandas as pd

def open_notes(sheet,notes):
 idx=pd.read_csv(HERE/'visual/contact_sheet_index.csv');ids=idx.loc[idx.stage.eq('open')&idx.sheet.eq(sheet),'blind_id'].tolist();assert len(ids)==len(notes)
 p=HERE/'visual/open_coding_raw_labels.csv';df=pd.DataFrame(dict(blind_id=ids,note=notes,sheet=sheet))
 if p.exists():
  old=pd.read_csv(p);assert not set(ids)&set(old.blind_id);df=pd.concat([old,df])
 df.to_csv(p,index=False)
