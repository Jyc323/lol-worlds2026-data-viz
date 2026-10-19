#!/usr/bin/env python3
"""Backtest chart -> charts/win_model_backtest.png"""
import sys, json
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent)); from theme import *
R = Path(__file__).resolve().parent.parent; J = json.load(open(R / "data/processed/win_backtest.json")); rc(plt)
fig = plt.figure(figsize=(12, 7.4), dpi=150)
fig.text(.04, .965, "How well did the win model do on games it had not seen?", fontsize=22, fontweight="bold", va="top")
o = J["overall"]; w = J["winrate_diff"]
fig.text(.04, .905, f"Test: retrain each month on earlier games only, then predict the next month ({o['n']:,} games, May to Oct 2026, major-league teams).\nIt picked the winner {o['acc'] * 100:.0f}% of the time; a coin flip gets 50%, and a simple win-rate comparison {w['acc'] * 100:.0f}%.", fontsize=11.5, color=MUT, va="top", linespacing=1.4)
a1 = fig.add_axes([.08, .20, .38, .55]); c = J["calibration"]
a1.plot([48, 80], [48, 80], color=GRID, lw=2, zorder=1); a1.text(70, 69.5, "perfect", color=MUT, fontsize=9, rotation=36)
for r in c:
    a1.scatter([r["pred"] * 100], [r["actual"] * 100], s=40 + r["n"] * .5, color=BLUE, edgecolor=FG, lw=.8, zorder=3)
    a1.text(r["pred"] * 100 + (-1.2 if r["bin"] == "55-60%" else 1.2), r["actual"] * 100 + (1.6 if r["bin"] == "55-60%" else -2.2), f"{r['bin']}  (n={r['n']})", fontsize=9, color=MUT, ha="right" if r["bin"] == "55-60%" else "left")
a1.set_xlim(48, 82); a1.set_ylim(44, 82); a1.set_xlabel("Chance the model gave the favourite (%)", color=FG); a1.set_ylabel("How often the favourite really won (%)", color=FG)
a1.set_title("Does a 70% pick win about 70% of the time?", loc="left", fontsize=12, fontweight="bold")
for s in a1.spines.values(): s.set_visible(False)
a1.tick_params(length=0)
a2 = fig.add_axes([.58, .20, .38, .55]); bc = J["by_cut"]; months = ["May", "Jun", "Jul", "Aug", "Sep", "Oct*"]; vals = [v["acc"] * 100 for v in bc.values()]; ns = [v["n"] for v in bc.values()]
a2.bar(months, vals, color=[NEUTRAL if n < 100 else BLUE for n in ns], width=.65, zorder=3); a2.axhline(50, color=MUT, lw=1.2, zorder=4); a2.set_ylim(40, 75)
for i, (v, n) in enumerate(zip(vals, ns)): a2.text(i, v + .8, f"{v:.0f}%", ha="center", fontsize=10.5, fontweight="bold"); a2.text(i, 41.3, f"n={n}", ha="center", fontsize=8.5, color="white" if n >= 100 else FG)
a2.text(5.45, 50.6, "coin flip", ha="right", fontsize=9, color=MUT); a2.set_title("Share of winners picked, by month", loc="left", fontsize=12, fontweight="bold")
for s in a2.spines.values(): s.set_visible(False)
a2.tick_params(length=0); a2.set_yticks([40, 50, 60, 70]); a2.set_yticklabels([f"{v}%" for v in (40, 50, 60, 70)])
s, x = J["same_league"], J["cross_league"]
fig.text(.04, .125, f"Reading: dots below the line = the model was too confident (its 70%+ picks won {c[3]['actual'] * 100:.0f}%, not {c[3]['pred'] * 100:.0f}%); its 55 to 60% picks won a bit more than predicted.\nMonths swing a lot (56% to 69%) with only 137 to 515 games. Same-league games: {s['acc'] * 100:.0f}% right ({s['n']:,} games); games between teams from\ndifferent leagues: {x['acc'] * 100:.0f}% ({x['n']} games, too few to be sure). *October has only 55 games.", fontsize=9.6, va="top", linespacing=1.45)
fig.text(.04, .052, "Source: Oracle's Elixir, 2026 games between teams of the six major leagues (LCK, LPL, LEC, LCS, LCP, CBLOL), incl. international events.\nSide-neutral probabilities. Not included: patch, rosters, draft. Association, not cause.", fontsize=8.3, color=MUT, va="top")
fig.savefig(R / "charts/win_model_backtest.png", facecolor=BG); print("ok")
