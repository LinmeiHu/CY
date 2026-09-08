import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image,ImageDraw
from .build import HERE,EXT

def main():
 out=HERE/'visual/representative_cases';out.mkdir(exist_ok=True)
 a=pd.read_csv(HERE/'visual/visual_year_spreads.csv');r=pd.read_csv(HERE/'visual/visual_repeatability.csv');dims=r.dimension.tolist()
 fig,axes=plt.subplots(1,2,figsize=(12,5),gridspec_kw={'width_ratios':[1.3,1]})
 v=a.pivot(index='dimension',columns='year',values='winner_minus_loser').reindex(dims);im=axes[0].imshow(v,vmin=-.5,vmax=.5,cmap='RdBu');axes[0].set_xticks(range(5),v.columns);axes[0].set_yticks(range(8),dims)
 for i in range(8):
  for j in range(5):axes[0].text(j,i,f'{v.iloc[i,j]:.2f}',ha='center',va='center',fontsize=9)
 axes[0].set_title('Blind semantic: winner minus loser (score units)');fig.colorbar(im,ax=axes[0],shrink=.65)
 axes[1].barh(np.arange(8)-.17,r.exact,.32,label='Exact');axes[1].barh(np.arange(8)+.17,r.spearman,.32,label='Spearman');axes[1].set_yticks(range(8),dims);axes[1].invert_yaxis();axes[1].set_xlim(0,1);axes[1].set_title('81 hidden repeat pairs');axes[1].legend();fig.tight_layout();fig.savefig(HERE/'visual/visual_evidence_summary.png',dpi=150);plt.close(fig)
 f=pd.read_csv(HERE/'visual/formal_labels_revealed.csv');page=Image.new('RGB',(1320,3*535),'white');rows=[]
 for i,d in enumerate(['direction','quieting','spike_distribution']):
  for j,label in enumerate(['WINNER','LOSER']):
   z=f.loc[f.label.eq(label)&f[d].ge(1)].sort_values('blind_id').iloc[0];bid=z.blind_id;im=Image.open(EXT/'visual/charts'/(bid+'.png'));page.paste(im,(j*660,i*535+35));ImageDraw.Draw(page).text((j*660+20,i*535+10),f'{d} >= +1 | {label} | {bid}',fill='black');rows.append(dict(dimension=d,label=label,blind_id=bid,selection='lexicographically first formal case score>=1; no outcome magnitude selection'))
 page.save(out/'archetypes_and_counterexamples.png');pd.DataFrame(rows).to_csv(out/'case_selection.csv',index=False)
 s=pd.read_parquet(EXT/'visual/revealed_discovery_sample.parquet');stats=[]
 for feature in ['log_cap','log_adv20','ret20','ret60','vol60']:
  z=s.pivot(index='triplet_id',columns='label',values=feature)
  for label in ['NEUTRAL','LOSER']:
   d=z[label]-z.WINNER;stats.append(dict(feature=feature,control=label,mean_difference=d.mean(),median_abs_difference=d.abs().median(),p90_abs_difference=d.abs().quantile(.9)))
 pd.DataFrame(stats).to_csv(HERE/'visual/matching_quality.csv',index=False)
if __name__=='__main__':main()
