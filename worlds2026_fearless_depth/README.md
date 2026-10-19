# Worlds 2026: how deep are the champion pools?

Two charts made for a Worlds 2026 (Season 16) preview thread.

| Chart | File |
|---|---|
| Champion-pool depth of the 15 Swiss Stage teams, by role, with each team vs. the 15-team average | `output/worlds_fearless_depth.png` |
| Pool depth vs. win rate for 226 teams in 27 leagues (Swiss Stage teams marked) | `output/depth_vs_winrate.png` |

## Why it matters
Worlds uses fearless draft: a champion played in one game of a series is locked for both teams for the rest of that series. Teams with narrow pools run out of comfortable picks in a Bo5.

## Metric
*Depth* = for each starter, the expected number of **different champions in 10 individual games** (not series), computed by rarefaction from all of his 2026 games, so players with 40 and 90 games are comparable. A team's depth is the sum over its five starters.

- Starters = most-played player per role in the team's last 30 games (all competitions). This is not the official Worlds roster.
- Data: 2026 pre-Worlds games (regional leagues, playoffs, international events). No Worlds games. Play-In teams (Karmine Corp, Cloud9, MVK, FURIA) are excluded from chart 1.
- Chart 2: win rate and depth are both measured relative to the team's league average; teams with at least 30 games, leagues with at least 6 teams; 90% bootstrap interval (seed fixed).
- Association, not cause: stronger teams may simply have more freedom to play their comfort picks.

## Reproduce
```bash
pip install -r worlds2026_fearless_depth/requirements.txt
# put 2026_LoL_esports_match_data_from_OraclesElixir.csv in data/raw/oe/  (or set OE_DIR)
python3 worlds2026_fearless_depth/run_all.py
```
`output/meta.json` records the data file's md5, the latest game date and all parameters, so a chart can be traced back to the exact data it came from.

Data source: [Oracle's Elixir](https://oracleselixir.com/tools/downloads).
