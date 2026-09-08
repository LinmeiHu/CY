"""Render causal blind charts; sealed mappings are consumed only inside this process."""
from .build import *
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection,PolyCollection
from PIL import Image,ImageDraw,ImageFont
FONT=ImageFont.truetype(matplotlib.get_data_path()+"/fonts/ttf/DejaVuSans.ttf",16)
def header(im,bid):
 dr=ImageDraw.Draw(im);dr.rectangle((0,0,660,31),fill="white");dr.text((330,17),bid,fill="black",font=FONT,anchor="mm");return im

def main():
 c=setup();s=pd.read_parquet(EXT/'visual/sealed_outcome_map.parquet');dup=pd.read_parquet(EXT/'visual/sealed_duplicates.parquet')
 c.register('symbols',s[['symbol']].drop_duplicates())
 d=c.execute(f"select d.* from read_parquet('{DAILY}') d join symbols using(symbol) where trade_date<'2022-01-01' order by symbol,trade_date").fetchdf()
 groups={k:g for k,g in d.groupby('symbol')};dest=EXT/'visual/charts';dest.mkdir(exist_ok=True)
 audit=[]
 for r in s.itertuples():
  hist=groups[r.symbol];hist=hist.loc[hist.trade_date.le(r.trade_date)].tail(250)
  assert len(hist)==250 and hist.history_valid.all() and hist.cal_idx.diff().dropna().eq(1).all()
  assert hist.trade_date.max()==r.trade_date and hist.available_at.le(hist.decision_at).all()
  # Normalization removes any common scale; no future row used in OHLC or volume.
  fig=plt.figure(figsize=(6,4.5),dpi=110);gs=fig.add_gridspec(3,1,height_ratios=[1,3,1],hspace=.13)
  ax0=fig.add_subplot(gs[0]);ax=fig.add_subplot(gs[1]);av=fig.add_subplot(gs[2],sharex=ax)
  ax0.plot(np.arange(-249,1),hist.coord_close/hist.coord_close.iloc[0],lw=.9,color='#374151');ax0.set_xlim(-249,2);ax0.set_xticks([]);ax0.tick_params(labelsize=6)
  z=hist.tail(120);vals=z[['coord_open','coord_high','coord_low','coord_close']].to_numpy()/z.coord_close.iloc[0]*100;x=np.arange(-119,1)
  colors=np.where(vals[:,3]>=vals[:,0],'#16847e','#cc4861')
  ax.add_collection(LineCollection([[(xx,l), (xx,h)] for xx,(_,h,l,_) in zip(x,vals)],colors=colors,linewidths=.6))
  ax.add_collection(PolyCollection([[(xx-.32,o),(xx+.32,o),(xx+.32,cl),(xx-.32,cl)] for xx,(o,h,l,cl) in zip(x,vals)],facecolors=colors,edgecolors=colors,linewidths=.4))
  ax.set_ylim(vals[:,2].min()*.985,vals[:,1].max()*1.015);ax.set_xlim(-120,2);ax.tick_params(labelsize=6,labelbottom=False)
  av.bar(x,z.volume/max(float(hist.volume.median()),1),width=.75,color=colors);av.set_xticks([-120,-60,0],['T-120','T-60','T']);av.tick_params(labelsize=6)
  for a in [ax0,ax,av]:a.axvline(0,color='#111827',lw=.7,linestyle=':');a.grid(alpha=.15);a.spines[['top','right']].set_visible(False)
  fig.subplots_adjust(left=.09,right=.97,bottom=.08,top=.93)
  fig.savefig(dest/(r.blind_id+'.png'));plt.close(fig)
  im=Image.open(dest/(r.blind_id+'.png')).convert('RGB');header(im,r.blind_id).save(dest/(r.blind_id+'.png'))
  audit.append(dict(blind_id=r.blind_id,bars=250,future_candles=0,valid_history=True))
 pd.DataFrame(audit).to_csv(HERE/'visual/chart_causality_audit.csv',index=False)
 for r in dup.itertuples():
  # Replace only ID header: duplicate identity stays sealed.
  im=Image.open(dest/(r.original_id+'.png')).convert('RGB');header(im,r.blind_id).save(dest/(r.blind_id+'.png'))
 order=pd.read_csv(HERE/'visual/blind_order.csv');rows=[];sheetdir=EXT/'visual/contact_sheets';sheetdir.mkdir(exist_ok=True)
 for stage in ['open','formal']:
  ids=order.loc[order.stage.eq(stage),'blind_id'].tolist()
  for n,start in enumerate(range(0,len(ids),16),1):
   page=Image.new('RGB',(2640,1980),'#dddddd')
   for j,bid in enumerate(ids[start:start+16]):
    im=Image.open(dest/(bid+'.png'));page.paste(im,(j%4*660,j//4*495));rows.append(dict(stage=stage,sheet=n,slot=j+1,blind_id=bid))
   page.save(sheetdir/f'{stage}_{n:02d}.jpg',quality=93)
 pd.DataFrame(rows).to_csv(HERE/'visual/contact_sheet_index.csv',index=False)
 print('Rendered',len(s),'primary charts',len(dup),'blind repeats; sheets',len(set((r['stage'],r['sheet']) for r in rows)))
if __name__=='__main__':main()
