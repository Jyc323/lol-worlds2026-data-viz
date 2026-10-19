#!/usr/bin/env python3
"""Swiss round 1 win probabilities -> charts/swiss_r1_predictions.png"""
import sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); from theme import *
R = Path(__file__).resolve().parent.parent; df = pd.read_csv(R / "data/processed/swiss_r1_predictions.csv"); rc(plt)
TAG = {"MKOI": "KOI"}
rows = []
for _, r in df.iterrows():
    if r.p_a >= .5: rows.append((TAG.get(r.team_a, r.team_a), TAG.get(r.team_b, r.team_b), r.p_a, r.lo, r.hi, r.games_a, r.games_b))
    else: rows.append((TAG.get(r.team_b, r.team_b), TAG.get(r.team_a, r.team_a), 1 - r.p_a, 1 - r.hi, 1 - r.lo, r.games_b, r.games_a))
rows.sort(key=lambda x: -x[2]); n = len(rows)
fig = plt.figure(figsize=(12, 8.2), dpi=150); ax = fig.add_axes([.17, .17, .66, .63])
fig.text(.04, .965, "Worlds 2026, Swiss round 1: who is favoured?", fontsize=24, fontweight="bold", va="top")
fig.text(.04, .905, "Each dot is the favourite's chance to win its best-of-one, from team strength estimated on 2026 results.\nBar = 90% range. The closer the dot is to the centre line, the closer to a coin flip.", fontsize=11.5, color=MUT, va="top", linespacing=1.4)
ax.axvline(50, color=MUT, lw=1.2, zorder=1); ax.set_xlim(10, 90); ax.set_ylim(-.7, n - .3)
for i, (fav, dog, p, lo, hi, gf, gd) in enumerate(rows):
    y = n - 1 - i; ax.add_patch(plt.Rectangle((10, y - .42), 80, .84, color=GRID if i % 2 == 0 else BG, zorder=0, lw=0))
    ax.plot([lo * 100, hi * 100], [y, y], color=NEUTRAL, lw=3, solid_capstyle="round", zorder=2, alpha=.8)
    ax.scatter([p * 100], [y], s=190, color=BLUE if p >= .6 else AQUA, edgecolor=FG, lw=.9, zorder=4)
    ax.text(p * 100, y + .33, f"{p * 100:.0f}%", ha="center", fontsize=11.5, fontweight="bold")
    ax.text(8.8, y, fav, ha="right", va="center", fontsize=14, fontweight="bold"); ax.text(91.2, y, dog, ha="left", va="center", fontsize=14, color=MUT)
    ax.text(8.8, y - .27, f"{gf} games", ha="right", va="center", fontsize=8, color=MUT); ax.text(91.2, y - .27, f"{gd} games", ha="left", va="center", fontsize=8, color=MUT)
for s in ax.spines.values(): s.set_visible(False)
ax.set_yticks([]); ax.set_xticks([10, 20, 30, 40, 50, 60, 70, 80, 90]); ax.set_xticklabels([f"{v}%" for v in (10, 20, 30, 40, 50, 60, 70, 80, 90)]); ax.tick_params(length=0)
ax.set_xlabel("Favourite's chance to win", color=FG, fontsize=11.5)
fig.text(.04, .112, "Blue = clear favourite (60% or more); green = near coin flip. Dot position is the model's best guess; the grey bar shows how far it could be off.\nSide choice is not known, so each number is side-neutral.", fontsize=10, va="top", linespacing=1.4)
fig.text(.04, .058, "How it was built: each team gets a strength score from 2,824 games of 59 teams in the six major leagues and international events (to Oct 10, 2026), with recent games counting more\nand opponent strength taken into account. On games it had not seen (Aug 15 to Oct 10, 506 games) it picked the winner 62% of the time. Not accounted for: patch, roster\nchanges, draft and form. Leagues are linked only through international games, so cross-region gaps are the least certain. Source: Oracle's Elixir. Association, not cause.", fontsize=8.6, color=MUT, va="top", linespacing=1.45)
fig.savefig(R / "charts/swiss_r1_predictions.png", facecolor=BG); print("ok")
