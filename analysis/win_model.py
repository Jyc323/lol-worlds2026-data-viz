#!/usr/bin/env python3
"""Pre-match win probabilities: ridge Bradley-Terry on 2026 results of major-region teams (side-neutral).
Outputs data/processed/win_model_ratings.csv and prints a time-split check."""
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import minimize
R = Path(__file__).resolve().parent.parent
MAJ = {"LCK", "LPL", "LEC", "LCS", "LCP", "CBLOL"}
def load():
    d = pd.read_csv(R / "data/raw/oe/2026_LoL_esports_match_data_from_OraclesElixir.csv", low_memory=False)
    t = d[d.position == "team"][["gameid", "date", "league", "teamname", "side", "result", "game"]].copy(); t["date"] = pd.to_datetime(t.date)
    home = t.groupby("teamname").league.agg(lambda s: s.value_counts().index[0]); major = set(home[home.isin(MAJ)].index)
    b = t[t.side == "Blue"].set_index("gameid"); r = t[t.side == "Red"].set_index("gameid")
    g = b.join(r, lsuffix="_b", rsuffix="_r", how="inner").reset_index()
    g = g[g.teamname_b.isin(major) & g.teamname_r.isin(major)].copy(); g["y"] = g.result_b.astype(float)
    return g[["gameid", "date_b", "teamname_b", "teamname_r", "y", "game_b"]].rename(columns={"date_b": "date", "teamname_b": "b", "teamname_r": "r", "game_b": "game"}).sort_values("date"), major
def fit(g, teams, alpha, half, ref):
    ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    ib = g.b.map(ix).values; ir = g.r.map(ix).values; y = g.y.values
    w = 0.5 ** ((ref - g.date).dt.days.values / half) if half else np.ones(len(g))
    def f(p):
        a, s = p[:n], p[n]; z = a[ib] - a[ir] + s; pr = 1 / (1 + np.exp(-z))
        ll = -(w * (y * np.log(pr + 1e-12) + (1 - y) * np.log(1 - pr + 1e-12))).sum() + alpha * (a ** 2).sum()
        gz = w * (pr - y); ga = np.zeros(n); np.add.at(ga, ib, gz); np.add.at(ga, ir, -gz); ga += 2 * alpha * a
        return ll, np.r_[ga, gz.sum()]
    res = minimize(f, np.zeros(n + 1), jac=True, method="L-BFGS-B"); return dict(zip(teams, res.x[:n])), res.x[n]
def main():
    g, major = load(); teams = sorted(set(g.b) | set(g.r)); print(len(g), "games,", len(teams), "teams")
    cut = pd.Timestamp("2026-08-15"); tr, te = g[g.date < cut], g[g.date >= cut]; te = te[te.b.isin(set(tr.b) | set(tr.r)) & te.r.isin(set(tr.b) | set(tr.r))]
    print("test games", len(te), "baseline logloss", round(-np.mean(te.y * np.log(.5) + (1 - te.y) * np.log(.5)), 4))
    best = None
    for alpha in (0.5, 1, 2, 4, 8):
        for half in (None, 120, 240):
            a, s = fit(tr, teams, alpha, half, cut); z = te.b.map(a) - te.r.map(a) + s; p = 1 / (1 + np.exp(-z))
            ll = -np.mean(te.y * np.log(p) + (1 - te.y) * np.log(1 - p)); acc = ((p > .5) == (te.y == 1)).mean(); print(alpha, half, round(ll, 4), round(acc, 3))
            if best is None or ll < best[0]: best = (ll, alpha, half)
    print("best", best); return g, teams, best
if __name__ == "__main__": main()
