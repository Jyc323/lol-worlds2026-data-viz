#!/usr/bin/env python3
"""Team style map: 15 Worlds 2026 direct-entry teams, Oracle's Elixir 2026 team rows (no Worlds games). -> data/processed/style_map.csv/json"""
import json
from pathlib import Path
import numpy as np, pandas as pd
R = Path(__file__).resolve().parent.parent
TEAMS = {"Gen.G": "GEN", "Hanwha Life Esports": "HLE", "T1": "T1", "Dplus Kia": "DK", "Anyone's Legend": "AL", "Bilibili Gaming": "BLG", "Top Esports": "TES", "Invictus Gaming": "IG",
         "G2 Esports": "G2", "Movistar KOI": "KOI", "Team Liquid": "TL", "LYON": "LYON", "Team Secret Whales": "TSW", "CTBC Flying Oyster": "CFO", "LØS": "LOS"}
d = pd.read_csv(R / "data/raw/oe/2026_LoL_esports_match_data_from_OraclesElixir.csv", low_memory=False)
t = d[(d.position == "team") & d.teamname.isin(TEAMS)].copy(); t["len"] = t.gamelength / 60
t["kills_pm"] = t.kills / t.len; t["deaths_pm"] = t.deaths / t.len
F = {"golddiffat15": "Gold lead at 15 min", "ckpm": "Kills per minute (both teams)", "len": "Game length (min)", "firsttower": "First tower rate", "firstblood": "First blood rate",
     "dragons": "Dragons per game", "heralds": "Heralds per game", "void_grubs": "Void grubs per game", "barons": "Barons per game"}
for c in F: t[c] = pd.to_numeric(t[c], errors="coerce")
g = t.groupby("teamname")[list(F)].mean(); g["games"] = t.groupby("teamname").size(); g["win"] = t.groupby("teamname").result.mean()
print(g.round(2).to_string())
X = g[list(F)]; Z = (X - X.mean()) / X.std(); U, S, Vt = np.linalg.svd(Z.values, full_matrices=False)
pc = U[:, :2] * S[:2]; var = S ** 2 / (S ** 2).sum(); print("explained", var[:3].round(3))
for k in range(2): print("PC", k + 1, {F[c]: round(v, 2) for c, v in zip(F, Vt[k])})
out = g.copy(); out["pc1"], out["pc2"] = pc[:, 0], pc[:, 1]; out["team"] = [TEAMS[i] for i in out.index]; out.to_csv(R / "data/processed/style_map.csv")
json.dump({"features": F, "load1": dict(zip(F, map(float, Vt[0]))), "load2": dict(zip(F, map(float, Vt[1]))), "var": var[:2].tolist()}, open(R / "data/processed/style_map.json", "w"), indent=1)
