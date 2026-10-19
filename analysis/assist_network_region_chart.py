#!/usr/bin/env python3
"""Assist network fingerprints of the 15 Worlds teams, grouped by home league -> charts/assist_network_region.png.
Arrow = assisting player -> player who got the kill (first 15 min). Thickness = assists per team kill. Colour = region."""
import sys, textwrap
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np, pandas as pd
from matplotlib.patches import FancyArrowPatch
sys.path.insert(0, str(Path(__file__).resolve().parent)); from theme import *
R = Path(__file__).resolve().parent.parent; P = R / "data/processed"; rc(plt)
a = pd.read_csv(P / "assist_network.csv"); k = pd.read_csv(P / "assist_network_kills.csv")
ROLES = ["top", "jungle", "mid", "bottom", "support"]; SH = dict(top="TOP", jungle="JNG", mid="MID", bottom="BOT", support="SUP")
NAME = {"MKOI": "KOI", "TLAW": "TL"}; THR = .10
VIOLET = "#7a62c9"
from matplotlib.colors import to_rgb
LO, HI = .10, .27
def shade(col, w):
    """pale tint of the region colour for rare pairs -> deep shade for frequent pairs"""
    t = min(max((w - LO) / (HI - LO), 0), 1); c = np.array(to_rgb(col)); pale = c * .30 + .70; deep = c * .86
    return tuple(pale + (deep - pale) * t)
# home league of each team in 2026 (from Oracle's Elixir team rows)
REG = {"LCK": (BLUE, ["GEN", "HLE", "T1", "DK"]), "LPL": (ORANGE, ["AL", "BLG", "TES", "IG"]), "LEC": (AQUA, ["G2", "MKOI"]),
       "LCS": (MAGENTA, ["TLAW", "LYON"]), "LCP": (YELLOW, ["CFO", "TSW"]), "CBLOL": (VIOLET, ["LOS"])}
# (row, first column) for each region
PLACE = {"LCK": (0, 0), "LPL": (1, 0), "LEC": (2, 0), "LCS": (2, 2), "LCP": (3, 0), "CBLOL": (3, 2)}
assert sorted(t for _, ts in REG.values() for t in ts) == sorted(a.team.unique())
ang = dict(zip(ROLES, np.deg2rad([90, 162, 234, 306, 18]))); pos = {r: (np.cos(ang[r]), np.sin(ang[r])) for r in ROLES}
W, H = 14.4, 17.6; TOP, BOT, SIDE = 2.75, 1.35, .45; cw = (W - 2 * SIDE) / 4; rh = (H - TOP - BOT) / 4
fig = plt.figure(figsize=(W, H), dpi=130); fx = lambda x: x / W; fy = lambda y: y / H
def wrap(s, n): return "\n".join(textwrap.wrap(s, n))
fig.text(fx(SIDE), fy(H - .35), "Who assists whom in the first 15 minutes?", fontsize=27, fontweight="bold", va="top")
fig.text(fx(SIDE), fy(H - 1.0), wrap("Each arrow points from the player who assisted to the player who got the kill. Thicker and darker arrow = happens more often (assists per team kill). Hue = the league the team plays in.", 125), fontsize=12.5, color=MUT, va="top", linespacing=1.4)
fig.text(fx(SIDE), fy(H - 1.65), wrap("No arrow = fewer than 10 assists per 100 team kills for that pair, not necessarily zero. Dot size = share of the team's kills. Same scale in every panel.", 125), fontsize=12.5, color=MUT, va="top", linespacing=1.4)
for reg, (col, teams) in REG.items():
    r0, c0 = PLACE[reg]; ytop = H - TOP - r0 * rh
    x0 = SIDE + c0 * cw; x1 = x0 + len(teams) * cw
    fig.text(fx(x0 + 6 / 72), fy(ytop - .08), reg, fontsize=17, fontweight="bold", color=col, va="top")
    fig.text(fx(x1 - .06), fy(ytop - .14), f"{len(teams)} team{'s' if len(teams) > 1 else ''}", fontsize=10.5, color=MUT, va="top", ha="right")
    fig.add_artist(plt.Line2D([fx(x0 + .06), fx(x1 - .06)], [fy(ytop - .42)] * 2, color=col, lw=2.2))
    for j, t in enumerate(teams):
        ax = fig.add_axes([fx(x0 + j * cw), fy(ytop - rh), fx(cw), fy(rh - .45)]); ax.set_xlim(-1.5, 1.5); ax.set_ylim(-1.4, 1.8); ax.axis("off"); ax.set_aspect("equal", adjustable="box", anchor="C")
        ax.text(0, 1.78, NAME.get(t, t), ha="center", va="top", fontsize=18, fontweight="bold")
        d = a[(a.team == t) & (a.src != a.dst) & (a.per_kill >= THR)].sort_values("per_kill")
        for _, r in d.iterrows():
            xa, ya = pos[r.src]; xb, yb = pos[r.dst]; w = r.per_kill
            ax.add_patch(FancyArrowPatch((xa, ya), (xb, yb), connectionstyle="arc3,rad=0.22", arrowstyle="-|>", mutation_scale=10 + 40 * w, lw=1 + 30 * w, color=shade(col, w), alpha=1, shrinkA=13, shrinkB=13))
        kt = k[k.team == t].set_index("dst").kills; sh = kt / kt.sum()
        for ro in ROLES:
            ax.scatter(*pos[ro], s=60 + 3400 * sh.get(ro, 0), color="#e7e6e2", edgecolor=MUT, lw=1.2, zorder=5); ax.text(*pos[ro], SH[ro], ha="center", va="center", fontsize=6.4, fontweight="bold", zorder=6)
# thickness legend (neutral grey, since colour = region)
lx = W - SIDE - 3 * 1.35 - .1
for i, w in enumerate((.10, .20, .30)):
    ax0 = fig.add_axes([fx(lx + i * 1.35), fy(1.0), fx(1.15), fy(.35)]); ax0.axis("off"); ax0.set_xlim(0, 1); ax0.set_ylim(0, 1)
    ax0.add_patch(FancyArrowPatch((.02, .5), (.80, .5), arrowstyle="-|>", mutation_scale=10 + 40 * w, lw=1 + 30 * w, color=shade("#6b6a66", w), alpha=1)); ax0.text(.45, -.35, f"{int(w * 100)} per 100 kills", ha="center", fontsize=9, color=MUT)
fig.text(fx(SIDE), fy(.62), wrap("Source: Riot lolesports live-stats frames, kills and assists rebuilt per second for 1,413 games of the 15 Worlds 2026 teams (Jan 14 - Oct 10, 2026), minutes 0-15 only; no Worlds games. Region = league the team plays in during 2026 (Oracle's Elixir). Association, not cause.", 150), fontsize=9.3, color=MUT, va="top", linespacing=1.4)
fig.savefig(R / "charts/assist_network_region.png", facecolor=BG); print("ok")
