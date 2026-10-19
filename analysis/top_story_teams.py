"""Per current Worlds top laner (games pooled across teams, no minimum): win-rate swing of his lane lead vs the same games' other four roles."""
import json, numpy as np, pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
LE={"LPL","LCK","LEC","LCS","LCP","CBLOL","FST","MSI","EWC"}
R=["top","jng","mid","bot","sup"]
CUR={"AL":"Breathe","IG":"TheShy","BLG":"Bin","TES":"ZUIAN","G2":"BrokenBlade","GEN":"Kiin","HLE":"Zeus","T1":"Doran","DK":"Siwoo","KOI":"Myrwn","TL":"Morgan","LYON":"Dhokla","TSW":"Pun","CFO":"Rest","LOS":"Zest"}
cols=["gameid","league","side","position","teamname","playername","result","golddiffat15","kills","assists","teamkills"]
d=pd.read_csv(ROOT/"data/raw/oe/2026_LoL_esports_match_data_from_OraclesElixir.csv",low_memory=False,usecols=cols)
d=d[d.league.isin(LE)&(d.position!="team")].copy()
d["kp"]=(d.kills+d.assists)/d.teamkills.replace(0,np.nan)
w=d.pivot_table(index=["gameid","side"],columns="position",values="golddiffat15")[R].dropna()
res=d.groupby(["gameid","side"]).result.first()
kp=d.pivot_table(index=["gameid","side"],columns="position",values="kp")[R]
top=d[d.position=="top"].set_index(["gameid","side"])[["playername","teamname"]]
rng=np.random.default_rng(11)
def swing(lead,y):
    a=y[lead>0];b=y[lead<0]
    return a.mean()-b.mean() if len(a) and len(b) else np.nan
out=[]
for team,pl in CUR.items():
    idx=[i for i in w.index if i in top.index and top.loc[i,"playername"].lower()==pl.lower()]
    idx=pd.MultiIndex.from_tuples(idx)
    W=w.loc[idx];y=res.loc[idx].to_numpy().astype(float)
    n=len(W)
    def stat(ii):
        t=swing(W["top"].to_numpy()[ii],y[ii])
        o=np.nanmean([swing(W[r].to_numpy()[ii],y[ii]) for r in R[1:]])
        return t,o
    t,o=stat(np.arange(n))
    bs=np.array([stat(rng.integers(0,n,n)) for _ in range(600)])
    diff=bs[:,0]-bs[:,1]
    out.append(dict(team=team,player=pl,n=n,win=float(y.mean()),swing_top=t,top_lo=float(np.nanpercentile(bs[:,0],5)),top_hi=float(np.nanpercentile(bs[:,0],95)),swing_oth=o,diff=t-o,diff_lo=float(np.nanpercentile(diff,5)),diff_hi=float(np.nanpercentile(diff,95)),
      top_ahead=float((W["top"]>0).mean()),avg_lead=float(W["top"].mean()),kp_top=float(kp.reindex(idx)["top"].mean()),kp_oth=float(kp.reindex(idx)[R[1:]].mean().mean()),
      teamN=int(pd.Series(top.loc[idx,"teamname"]).nunique())))
o=pd.DataFrame(out).sort_values("diff");pd.set_option("display.width",250)
print(o.round(3).to_string())
json.dump(out,open(ROOT/"data/processed/top_story_teams.json","w"),indent=1,default=float)
