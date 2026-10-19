#!/usr/bin/env python3
"""Worlds 2026 Swiss round 1 (BO1) win probabilities -> data/processed/swiss_r1_predictions.csv"""
from pathlib import Path
import numpy as np, pandas as pd
from win_model import load, fit
R = Path(__file__).resolve().parent.parent; ALPHA, HALF = 0.5, 120
NAME = {"GEN": "Gen.G", "IG": "Invictus Gaming", "TL": "Team Liquid", "CFO": "CTBC Flying Oyster", "AL": "Anyone's Legend", "KC": "Karmine Corp", "G2": "G2 Esports", "DK": "Dplus Kia",
        "HLE": "Hanwha Life Esports", "TES": "Top Esports", "LOS": "LØS", "T1": "T1", "TSW": "Team Secret Whales", "LYON": "LYON", "BLG": "Bilibili Gaming", "MKOI": "Movistar KOI"}
M = [("GEN", "IG"), ("TL", "CFO"), ("AL", "KC"), ("G2", "DK"), ("HLE", "TES"), ("LOS", "T1"), ("TSW", "LYON"), ("BLG", "MKOI")]
def main():
    g, major = load(); teams = sorted(set(g.b) | set(g.r)); ref = g.date.max()
    for k, v in NAME.items(): assert v in teams, v
    a0, _ = fit(g, teams, ALPHA, HALF, ref); rng = np.random.default_rng(7); B = []
    for _ in range(200):
        a, _ = fit(g.sample(len(g), replace=True, random_state=int(rng.integers(1e9))), teams, ALPHA, HALF, ref); B.append(a)
    p = lambda a, x, y: 1 / (1 + np.exp(-(a[NAME[x]] - a[NAME[y]])))
    rows = []
    for x, y in M:
        bs = np.array([p(a, x, y) for a in B]); n = lambda t: int(((g.b == NAME[t]) | (g.r == NAME[t])).sum())
        rows.append(dict(team_a=x, team_b=y, p_a=p(a0, x, y), lo=np.percentile(bs, 5), hi=np.percentile(bs, 95), games_a=n(x), games_b=n(y)))
    o = pd.DataFrame(rows); o.to_csv(R / "data/processed/swiss_r1_predictions.csv", index=False); print(o.round(3).to_string())
    r = pd.Series({k: a0[v] for k, v in NAME.items()}).sort_values(ascending=False); print(r.round(2).to_string()); r.rename("strength").rename_axis("team").reset_index().to_csv(R / "data/processed/swiss_r1_strength.csv", index=False); print("data through", ref.date(), "games", len(g))
if __name__ == "__main__": main()
