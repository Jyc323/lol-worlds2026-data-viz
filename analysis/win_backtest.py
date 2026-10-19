#!/usr/bin/env python3
"""Rolling-origin backtest of the Swiss win model -> data/processed/win_backtest.json, win_backtest_games.csv"""
import json
from pathlib import Path
import numpy as np, pandas as pd
from win_model import load, fit
R = Path(__file__).resolve().parent.parent; ALPHA, HALF = 0.5, 120
def metrics(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6); return dict(n=int(len(y)), acc=float(((p > .5) == (y == 1)).mean()), logloss=float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), brier=float(np.mean((p - y) ** 2)))
def main():
    g, major = load(); teams = sorted(set(g.b) | set(g.r)); g = g.reset_index(drop=True)
    home = pd.read_csv(R / "data/raw/oe/2026_LoL_esports_match_data_from_OraclesElixir.csv", low_memory=False)
    home = home[home.position == "team"].groupby("teamname").league.agg(lambda s: s.value_counts().index[0])
    cuts = pd.to_datetime(["2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01"]); out = []
    for i, c in enumerate(cuts):
        end = cuts[i + 1] if i + 1 < len(cuts) else g.date.max() + pd.Timedelta(days=1); tr = g[g.date < c]; te = g[(g.date >= c) & (g.date < end)]
        known = set(tr.b) | set(tr.r); te = te[te.b.isin(known) & te.r.isin(known)].copy()
        a, s = fit(tr, teams, ALPHA, HALF, c); te["p"] = 1 / (1 + np.exp(-(te.b.map(a) - te.r.map(a))))   # side-neutral, like the Swiss predictions
        # baseline: raw win rate difference (before cutoff)
        wr = pd.concat([tr.assign(t=tr.b, w=tr.y), tr.assign(t=tr.r, w=1 - tr.y)]).groupby("t").w.agg(["mean", "size"])
        te["p_wr"] = (.5 + (te.b.map(wr["mean"]).fillna(.5) - te.r.map(wr["mean"]).fillna(.5)) * .8).clip(.05, .95)
        te["cut"] = str(c.date()); te["cross"] = (te.b.map(home) != te.r.map(home)); out.append(te)
    t = pd.concat(out); t.to_csv(R / "data/processed/win_backtest_games.csv", index=False); y = t.y.values
    res = dict(overall=metrics(t.p.values, y), coin=metrics(np.full(len(t), .5), y), winrate_diff=metrics(t.p_wr.values, y),
               same_league=metrics(t.p[~t.cross].values, t.y[~t.cross].values), cross_league=metrics(t.p[t.cross].values, t.y[t.cross].values),
               by_cut={k: metrics(v.p.values, v.y.values) for k, v in t.groupby("cut")})
    conf = (t.p - .5).abs(); bins = [0, .05, .1, .2, .5]; lab = ["50-55%", "55-60%", "60-70%", "70%+"]
    t["fav"] = np.where(t.p >= .5, t.p, 1 - t.p); t["fav_won"] = np.where(t.p >= .5, t.y, 1 - t.y)
    res["calibration"] = [dict(bin=l, n=int(((conf > lo) & (conf <= hi)).sum()), pred=float(t.fav[(conf > lo) & (conf <= hi)].mean()), actual=float(t.fav_won[(conf > lo) & (conf <= hi)].mean())) for l, lo, hi in zip(lab, bins[:-1], bins[1:])]
    json.dump(res, open(R / "data/processed/win_backtest.json", "w"), indent=1); print(json.dumps(res, indent=1))
main()
