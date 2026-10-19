#!/usr/bin/env python3
"""How the Swiss round 1 numbers are made -> charts/swiss_r1_method.png"""
import sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); from theme import *
R = Path(__file__).resolve().parent.parent; st = pd.read_csv(R / "data/processed/swiss_r1_strength.csv"); pr = pd.read_csv(R / "data/processed/swiss_r1_predictions.csv"); rc(plt)
S = dict(zip(st.team, st.strength)); TAG = {"MKOI": "KOI"}
fig = plt.figure(figsize=(12, 7.6), dpi=150)
fig.text(.04, .965, "How the win chances are calculated", fontsize=24, fontweight="bold", va="top")
fig.text(.04, .905, "Step 1: every team gets a strength score from its 2026 results.   Step 2: the gap between two scores becomes a win chance.", fontsize=11.5, color=MUT, va="top")
a1 = fig.add_axes([.10, .22, .30, .60]); st = st.sort_values("strength"); cols = [BLUE] * len(st)
a1.barh([TAG.get(t, t) for t in st.team], st.strength, color=cols, height=.7, zorder=3); a1.set_xlim(-.75, 1.7)
for i, v in enumerate(st.strength): a1.text(v + (.04 if v >= 0 else -.04), i, f"{v:.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=9.5, color=MUT)
a1.set_title("Step 1: strength score (higher = stronger)", loc="left", fontsize=12, fontweight="bold"); a1.axvline(0, color=MUT, lw=1)
for s in a1.spines.values(): s.set_visible(False)
a1.tick_params(length=0, labelsize=10.5, pad=34); a1.set_xticks([])
a2 = fig.add_axes([.52, .22, .44, .60]); x = np.linspace(-1.9, 1.9, 200); a2.plot(x, 100 / (1 + np.exp(-x)), color=MUT, lw=2.4, zorder=2)
LAB = {"TL-CFO": (1.25, 77.2), "BLG-KOI": (1.25, 74.3), "GEN-IG": (1.25, 71.4), "HLE-TES": (.8, 65.2), "TSW-LYON": (-.17, 42.2), "LOS-T1": (-.7, 28.6)}
for _, r in pr.iterrows():
    d = S[r.team_a] - S[r.team_b]; a2.scatter([d], [r.p_a * 100], s=90, color=BLUE if abs(r.p_a - .5) >= .1 else AQUA, edgecolor=FG, lw=.8, zorder=4)
    k = f"{TAG.get(r.team_a, r.team_a)}-{TAG.get(r.team_b, r.team_b)}"
    if k in LAB: a2.text(*LAB[k], k, fontsize=9, ha="left")
a2.text(.12, 46.5, "G2-DK and AL-KC", fontsize=9, ha="left")
a2.axhline(50, color=GRID, lw=1.2, zorder=1); a2.axvline(0, color=GRID, lw=1.2, zorder=1); a2.set_xlim(-1.9, 1.9); a2.set_ylim(10, 90)
a2.set_title("Step 2: score gap -> chance that the first-named team wins", loc="left", fontsize=12, fontweight="bold")
a2.set_xlabel("Score of first team minus score of second team", color=FG); a2.set_ylabel("Win chance (%)", color=FG)
for s in a2.spines.values(): s.set_visible(False)
a2.tick_params(length=0)
r = pr[(pr.team_a == "LOS") & (pr.team_b == "T1")].iloc[0]; d = S["LOS"] - S["T1"]
fig.text(.52, .13, f"Example: T1 scores {S['T1']:.2f} and LOS {S['LOS']:.2f}.\nThe gap is {-d:.2f}, which the curve turns into a {(1 - r.p_a) * 100:.0f}% chance for T1.", fontsize=10.5, va="top", linespacing=1.4)
fig.text(.04, .13, "Scores are fitted so that, across 2,824 games, the teams\nthat won tend to have the bigger score. Recent games\ncount more (half weight after 120 days).", fontsize=10.5, va="top", linespacing=1.4)
fig.text(.04, .048, "Games: 2026, teams from the six major leagues plus international events, to Oct 10. On 506 later games it had not seen, the same method picked the winner\n62% of the time. Source: Oracle's Elixir. Not included: patch, roster changes, draft, side. Association, not cause.", fontsize=8.8, color=MUT, va="top", linespacing=1.45)
fig.savefig(R / "charts/swiss_r1_method.png", facecolor=BG); print("ok")
