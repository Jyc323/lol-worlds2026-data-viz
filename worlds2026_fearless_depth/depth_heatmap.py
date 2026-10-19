#!/usr/bin/env python3
"""Worlds 2026: which team has the deepest champion pools? (fearless draft, plain-language chart)

Fearless rule: a champion used in one game of a series is locked for both teams for the rest of
the series. A Bo5 can therefore force a player to use up to 5 different champions.

Metric ("variety"): for each starter, the expected number of DIFFERENT champions he plays in
K games (default 10), computed by rarefaction from all his 2026 games (every league/tournament).
Rarefaction makes players with 40 games and players with 90 games directly comparable.
Team score = sum over the five starters.

Starters = the player who played each role most in the team's last 30 games.
Players with fewer than K games this season are drawn as a greyed-out box (none this year).

Run:  python3 worlds2026_fearless_depth/depth_heatmap.py [--k 20] [--years 2026]
Writes output/worlds_depth.csv and output/worlds_fearless_depth.png
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from common import INTERNATIONAL, OUT, POS, ROLE_LABEL, SHORT, WORLDS_TEAMS, load, rarefied_distinct


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2026])
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--recent", type=int, default=30)
    args = ap.parse_args()

    df = load(args.years)
    pl = df[df.position.isin(POS)].dropna(subset=["playerid", "champion"]).copy()
    pl["date"] = pd.to_datetime(pl["date"])
    present = set(pl.teamname.unique())
    missing = [t for t in WORLDS_TEAMS if t not in present]
    if missing:
        print("TEAM NAMES NOT FOUND:", missing)
    teams = [t for t in WORLDS_TEAMS if t in present]

    champ_counts = pl.groupby(["playerid", "champion"]).size()
    games = pl.groupby("playerid").size()
    names = pl.groupby("playerid").playername.agg(lambda s: s.mode().iat[0])

    rows = []
    for team in teams:
        tp = pl[pl.teamname == team]
        last = tp.drop_duplicates("gameid").nlargest(args.recent, "date").gameid
        tr = tp[tp.gameid.isin(last)]
        region = tp[~tp.league.isin(INTERNATIONAL)].league.mode()
        region = region.iat[0] if len(region) else tp.league.mode().iat[0]
        for pos in POS:
            sub = tr[tr.position == pos]
            if sub.empty:
                continue
            pid = sub.playerid.value_counts().index[0]
            cc = champ_counts.loc[pid].to_numpy()
            rows.append({"team": team, "region": region, "pos": pos, "playerid": pid, "player": names[pid],
                         "games": int(games[pid]), "own_champs": int(len(cc)),
                         "variety": rarefied_distinct(cc, args.k)})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "worlds_depth.csv", index=False)

    wide = res.pivot(index="team", columns="pos", values="variety")[POS]
    total = wide.sum(axis=1, min_count=1)
    short_n = res[res.games < args.k]
    print(f"k={args.k}; teams {len(teams)}; starters {len(res)}; below k games: {len(short_n)}")
    print(short_n[["team", "pos", "player", "games"]].to_string(index=False))
    print(wide.assign(total=total).sort_values("total", ascending=False).round(1).to_string())

    # ------------------------------------------------------------ chart
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle

    order = total.sort_values(ascending=False).index.tolist()
    n = len(order)
    vals = wide.loc[order, POS].to_numpy(float)
    vmin, vmax = np.nanmin(vals), np.nanmax(vals)
    cmap = LinearSegmentedColormap.from_list("depth", ["#fef3c7", "#fb923c", "#9a3412"])

    fig = plt.figure(figsize=(11.5, 0.5 * n + 3.2), facecolor="white")
    ax = fig.add_axes([0.20, 0.14, 0.62, 0.70])
    ax.set_xlim(0, len(POS))
    ax.set_ylim(n, 0)
    for i, team in enumerate(order):
        for j, pos in enumerate(POS):
            r = res[(res.team == team) & (res.pos == pos)]
            if r.empty:
                continue
            r = r.iloc[0]
            v = r.variety
            if np.isnan(v):
                ax.add_patch(Rectangle((j + .03, i + .05), .94, .9, facecolor="#f3f4f6", edgecolor="white"))
                ax.text(j + .5, i + .38, "not enough\ngames", ha="center", va="center", fontsize=6.5, color="#9ca3af")
                ax.text(j + .5, i + .82, r.player, ha="center", va="center", fontsize=6.5, color="#9ca3af")
                continue
            c = cmap((v - vmin) / (vmax - vmin + 1e-9))
            ax.add_patch(Rectangle((j + .03, i + .05), .94, .9, facecolor=c, edgecolor="white"))
            light = (v - vmin) / (vmax - vmin + 1e-9) < .55
            tc = "#1f2937" if light else "white"
            ax.text(j + .5, i + .40, f"{v:.1f}", ha="center", va="center", fontsize=11, fontweight="bold", color=tc)
            ax.text(j + .5, i + .76, r.player, ha="center", va="center", fontsize=7, color=tc)
    ax.set_yticks(np.arange(n) + .5, [SHORT.get(t, t) for t in order], fontsize=10.5)
    ax.set_xticks(np.arange(len(POS)) + .5, [ROLE_LABEL[p] for p in POS], fontsize=10.5, fontweight="bold")
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)

    # total bars
    axb = fig.add_axes([0.84, 0.14, 0.13, 0.70], sharey=ax)
    tv = total.loc[order].to_numpy()
    avg = tv.mean()
    dv = tv - avg
    lim = np.abs(dv).max() * 1.45
    axb.barh(np.arange(n) + .5, dv, height=.8, color=np.where(dv >= 0, "#c2410c", "#64748b"))
    axb.axvline(0, color="#374151", lw=1)
    for i, v in enumerate(dv):
        axb.text(v + (.08 if v >= 0 else -.08) * lim / 1.45 * 1.0, i + .5, f"{v:+.1f}", va="center",
                 ha="left" if v >= 0 else "right", fontsize=9, color="#374151")
    axb.set_xlim(-lim, lim)
    axb.set_title("vs. average team", fontsize=10.5, fontweight="bold", loc="left")
    axb.axis("off")

    fig.text(0.03, 0.965, "Worlds 2026 Swiss Stage: whose champion pool runs deepest?", fontsize=19, fontweight="bold", color="#111827")
    fig.text(0.03, 0.925, "Worlds uses fearless draft: a champion played in one game is banned for both teams for the rest of the series.\n"
             "A deep team can keep finding comfortable champions in game 4 and 5. A shallow team runs out.",
             fontsize=10.5, color="#374151", va="top")
    fig.text(0.03, 0.095, f"How to read: each box is one starter. The big number is how many DIFFERENT champions he plays in {args.k} individual games "
             f"(2026 season, leagues and international events).\nDarker = wider pool. Bars on the right: the team's five-player total minus the average of these 15 teams\n(orange = more different champions than average, grey = fewer). Teams are ordered by that total.",
             fontsize=9.5, color="#374151", va="top")
    fig.text(0.03, 0.04, f"Source: Oracle's Elixir, {', '.join(map(str, args.years))} season. Starters = most-played player per role in the team's "
             f"last {args.recent} games. Estimated by rarefaction from all of the player's games; a greyed-out box = fewer than {args.k} games.\n"
             "A wider pool is not the same as a better team: it only shows how many options a player has shown he can play.",
             fontsize=7.5, color="#6b7280", va="top")
    out = OUT / "worlds_fearless_depth.png"
    fig.savefig(out, dpi=170)
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
