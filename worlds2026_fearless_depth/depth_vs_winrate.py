#!/usr/bin/env python3
"""Is a deeper champion pool linked to winning more? (all 2026 teams, Worlds teams marked)

Per team: five starters (most-played player per role over the season), variety = expected number
of different champions in K games (rarefaction), team depth = sum of the five.
Win rate = team's 2026 win rate, measured as the difference from its league's average so that
strong and weak leagues are comparable. Only teams with >= MIN_GAMES games and starters with >= K games.

Caveats printed on the chart: correlation not causation (strong teams may also get more freedom
to pick what they want; weak teams may be forced to flex), and depth is measured over the same season.

Run: python3 worlds2026_fearless_depth/depth_vs_winrate.py [--k 10]
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import INTERNATIONAL, OUT, POS, SEED, WORLDS_TEAMS, load, rarefied_distinct

MIN_GAMES = 30
SWISS = set(WORLDS_TEAMS)
PLAYIN = {"Karmine Corp", "Cloud9", "MVK Esports", "FURIA"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2026])
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)

    df = load(args.years)
    pl = df[df.position.isin(POS)].dropna(subset=["playerid", "champion"])
    tm = df[df.position == "team"]
    dom = tm[~tm.league.isin(INTERNATIONAL)]
    team_league = dom.groupby("teamname").league.agg(lambda s: s.mode().iat[0])
    wr = tm.groupby("teamname").agg(games=("result", "size"), wr=("result", "mean"))
    wr["league"] = team_league
    wr["league"] = wr.league.fillna("other")
    # league baseline: average win rate of its teams over ALL games is 0.5 by construction within a league,
    # but teams also play outside it; demean to be safe
    wr["wr_vs_league"] = wr.wr - wr.groupby("league").wr.transform("mean")

    cc = pl.groupby(["playerid", "champion"]).size()
    gp = pl.groupby("playerid").size()
    names = pl.groupby("playerid").playername.agg(lambda s: s.mode().iat[0])
    rows = []
    for team, tp in pl.groupby("teamname"):
        if team not in wr.index or wr.loc[team, "games"] < MIN_GAMES:
            continue
        tot, ok = 0.0, True
        for pos in POS:
            sub = tp[tp.position == pos]
            if sub.empty:
                ok = False
                break
            pid = sub.playerid.value_counts().index[0]
            v = rarefied_distinct(cc.loc[pid].to_numpy(), args.k)
            if np.isnan(v):
                ok = False
                break
            tot += v
        if ok:
            rows.append({"team": team, "depth": tot})
    d = pd.DataFrame(rows).merge(wr.reset_index(), left_on="team", right_on="teamname")
    d = d[d.league != "other"]
    # only leagues with >= 6 teams so the league baseline means something
    d = d[d.groupby("league").team.transform("size") >= 6].copy()
    d["depth_vs_league"] = d.depth - d.groupby("league").depth.transform("mean")
    d["group"] = np.where(d.team.isin(SWISS), "swiss", np.where(d.team.isin(PLAYIN), "playin", "other"))
    d.to_csv(OUT / "depth_vs_winrate.csv", index=False)

    x, y = d.depth_vs_league.to_numpy(), d.wr_vs_league.to_numpy()
    rho = spearmanr(x, y)[0]
    slope = np.polyfit(x, y, 1)[0]
    bs = []
    for _ in range(args.boot):
        ix = rng.integers(0, len(d), len(d))
        bs.append((spearmanr(x[ix], y[ix])[0], np.polyfit(x[ix], y[ix], 1)[0]))
    bs = np.array(bs)
    rlo, rhi = np.quantile(bs[:, 0], [.05, .95])
    slo, shi = np.quantile(bs[:, 1], [.05, .95])
    print(f"teams {len(d)} in {d.league.nunique()} leagues; Spearman {rho:.2f} [{rlo:.2f},{rhi:.2f}]; "
          f"slope {slope * 100:.2f} pts win rate per +1 champion [{slo * 100:.2f},{shi * 100:.2f}] (90% bootstrap)")
    # same within the Swiss 15 only
    s = d[d.group == "swiss"]
    if len(s) > 5:
        print(f"Swiss 15 only (n={len(s)}): Spearman {spearmanr(s.depth, s.wr)[0]:.2f}")
    # per league
    for lg, g in d.groupby("league"):
        print(f"  {lg:8s} n={len(g):2d} Spearman {spearmanr(g.depth, g.wr)[0]:+.2f}")

    # ---------------- chart ----------------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10.5, 7.6))
    o = d[d.group != "swiss"]
    sw = d[d.group == "swiss"]
    ax.scatter(o.depth_vs_league, o.wr_vs_league * 100, s=38, color="#d1d5db", zorder=2, label="other teams this season")
    ax.scatter(sw.depth_vs_league, sw.wr_vs_league * 100, s=70, color="#c2410c", zorder=3, label="Worlds Swiss Stage teams")
    ab = {"Hanwha Life Esports": "HLE", "Anyone's Legend": "AL", "Bilibili Gaming": "BLG", "Invictus Gaming": "IG",
          "Team Secret Whales": "Secret Whales", "CTBC Flying Oyster": "CFO", "Top Esports": "TES", "Movistar KOI": "MKOI",
          "Dplus Kia": "DK", "Team Liquid": "TL", "G2 Esports": "G2"}
    off = {"AL": (-22, -12), "HLE": (6, 5), "IG": (-16, -12), "CFO": (7, 3), "Gen.G": (-34, 6), "LØS": (7, -11)}
    for _, r in sw.iterrows():
        nm = ab.get(r.team, r.team)
        ax.annotate(nm, (r.depth_vs_league, r.wr_vs_league * 100), textcoords="offset points",
                    xytext=off.get(nm, (6, 4)), fontsize=8.5, color="#7c2d12")
    xs = np.linspace(x.min(), x.max(), 50)
    ax.plot(xs, np.polyval(np.polyfit(x, y * 100, 1), xs), color="#374151", lw=2, zorder=1)
    ax.axhline(0, color="#e5e7eb", lw=1)
    ax.axvline(0, color="#e5e7eb", lw=1)
    ax.set_xlabel(f"Pool depth vs. the team's league average\n(total different champions across 5 starters in {args.k} games each; right = deeper)", fontsize=10)
    ax.set_ylabel("Win rate vs. league average (percentage points)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    verdict = ("Deeper pools go with slightly higher win rates" if rlo > 0 else
               "No clear link between pool depth and win rate" if rlo <= 0 <= rhi else "Deeper pools go with slightly lower win rates")
    fig.text(0.05, 0.965, "Does a deeper champion pool mean more wins?", fontsize=18, fontweight="bold", color="#111827")
    fig.text(0.05, 0.925, f"{verdict}: {len(d)} teams in {d.league.nunique()} leagues, 2026. Each dot is a team.\n"
             f"Each extra champion in the pool goes with {slope * 100:+.1f} points of win rate (90% range {slo * 100:+.1f} to {shi * 100:+.1f}).",
             fontsize=10.5, color="#374151", va="top")
    fig.text(0.05, 0.015, "Source: Oracle's Elixir 2026. Starters = most-played player per role; depth by rarefaction over the whole season. "
             f"Teams with ≥{MIN_GAMES} games, leagues with ≥6 teams.\nAssociation, not cause: better teams may also have more freedom to pick their comfort champions.",
             fontsize=7.5, color="#6b7280", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 0.88))
    out = OUT / "depth_vs_winrate.png"
    fig.savefig(out, dpi=170)
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
