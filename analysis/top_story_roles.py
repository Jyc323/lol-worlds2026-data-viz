"""Plain-language evidence that the top laner's lead matters least. Oracle's Elixir 2026 (LPL LCK LEC LCS LCP CBLOL FST MSI EWC; no Worlds).
Rows are team-sides (two per game); ranges are 90% bootstrap over games.   python3 analysis/top_story_roles.py -> data/processed/top_story_roles.json"""
import json, numpy as np, pandas as pd
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
LE={"LPL","LCK","LEC","LCS","LCP","CBLOL","FST","MSI","EWC"}
R=["top","jng","mid","bot","sup"]
cols=["gameid","league","side","position","result","golddiffat15","kills","assists","teamkills"]
d=pd.read_csv(ROOT/"data/raw/oe/2026_LoL_esports_match_data_from_OraclesElixir.csv",low_memory=False,usecols=cols)
d=d[d.league.isin(LE)&(d.position!="team")].copy()
d["kp"]=(d.kills+d.assists)/d.teamkills.replace(0,np.nan)
w=d.pivot_table(index=["gameid","side"],columns="position",values="golddiffat15")[R].dropna()
y=d.groupby(["gameid","side"]).result.first().loc[w.index].to_numpy().astype(float)
g=w.index.get_level_values(0).to_numpy(); tot=w.sum(axis=1)
rng=np.random.default_rng(5)
groups=[np.where(g==u)[0] for u in pd.unique(g)]
def rate(mask,B=800):
    m=np.asarray(mask); est=y[m].mean(); bs=[]
    for _ in range(B):
        ii=np.concatenate([groups[k] for k in rng.integers(0,len(groups),len(groups))]); mm=m[ii]
        if mm.sum(): bs.append(y[ii][mm].mean())
    return dict(rate=float(est),lo=float(np.percentile(bs,5)),hi=float(np.percentile(bs,95)),n=int(m.sum()))
out={"n_games":int(len(set(g))),"n_rows":int(len(w))}
for thr in (500,1000,1500):
    out[f"ahead_{thr}"]={r:rate((w[r]>=thr).to_numpy()) for r in R}
out["tug_top_ahead_team_behind"]={r:rate(((w[r]>=500)&(tot-w[r]<=-1000)).to_numpy()) for r in R}
out["tug_top_behind_team_ahead"]={r:rate(((w[r]<=-500)&(tot-w[r]>=1000)).to_numpy()) for r in R}
kpw=d.pivot_table(index=["gameid"],columns="position",values="kp",aggfunc="mean")
kps={}
for r in R:
    v=d[d.position==r].dropna(subset=["kp"]);kps[r]=dict(mean=float(v.kp.mean()),n=int(len(v)))
out["kill_participation"]=kps
json.dump(out,open(ROOT/"data/processed/top_story_roles.json","w"),indent=1)
print(json.dumps(out,indent=1)[:2500])
