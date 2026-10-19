#!/usr/bin/env python3
"""Team style map -> charts/style_map.png (colour = win rate, one-hue sequential)"""
import json, sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); from theme import *
R = Path(__file__).resolve().parent.parent; df = pd.read_csv(R / "data/processed/style_map.csv"); rc(plt)
fig = plt.figure(figsize=(12, 7.6), dpi=150); ax = fig.add_axes([.08, .21, .80, .58])
fig.text(.04, .95, "A style map of the 15 Worlds teams", fontsize=24, fontweight="bold", va="top")
fig.text(.04, .885, "Nine game-style numbers per team (gold lead, towers, dragons, heralds, grubs, barons,\nkill pace, game length, first blood) squeezed into two separate directions. Darker red = higher win rate.", fontsize=11.5, color=MUT, va="top")
sc = ax.scatter(df.pc1, df.pc2, c=df.win, cmap=SEQ, s=df.games * 4.2, edgecolor=FG, lw=.8, vmin=.42, vmax=.74, zorder=3)
OFF = {"LYON": (-.55, .12), "KOI": (.12, .08), "T1": (-.1, -.38), "GEN": (.1, .12), "LOS": (-.1, -.35)}
for _, r in df.iterrows():
    o = OFF.get(r.team, (.09, .09)); ax.text(r.pc1 + o[0], r.pc2 + o[1], r.team, fontsize=13, fontweight="bold", zorder=4)
for s in ax.spines.values(): s.set_visible(False)
ax.axhline(0, color=GRID, lw=1.2); ax.axvline(0, color=GRID, lw=1.2); ax.tick_params(length=0, labelbottom=False, labelleft=False)
ax.set_xlabel("Direction 1:  more early map control (first towers, barons, early gold lead)  ->", color=FG, fontsize=12); ax.set_ylabel("Direction 2:  faster, kill-heavy, shorter games  ->", color=FG, fontsize=12)
cb = fig.colorbar(sc, ax=ax, fraction=.025, pad=.02); cb.set_label("Win rate in 2026 games", color=MUT); cb.ax.yaxis.set_tick_params(color=MUT, labelcolor=MUT); cb.outline.set_visible(False)
fig.text(.04, .13, "How to read: teams close together play alike. The two directions are NOT opposites: they are independent,\na team can be high on both, low on both, or high on one.", fontsize=10, va="top")
fig.text(.04, .085, "Direction 1 mixes gold lead, first towers, barons, heralds; direction 2 mixes kills per minute, first blood, short games. They were found by principal component analysis, which picks\nthe two biggest, unrelated ways in which the 15 teams differ. Together they explain 59% of the differences between teams. Dot size = games played.", fontsize=9, color=MUT, va="top")
fig.text(.04, .028, "Source: Oracle's Elixir team rows, 2026 league and international games of the 15 teams (no Worlds games). Association, not cause.", fontsize=8.5, color=MUT, va="top")
fig.savefig(R / "charts/style_map.png", facecolor=BG); print("ok")
