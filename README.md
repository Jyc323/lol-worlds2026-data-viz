# LoL Worlds 2026: data and charts

Python analysis and charts behind my threads on X ([@jiayuliiop8](https://x.com/jiayuliiop8)): new angles on League of Legends esports, built from large public datasets. Every chart states its sample size and caveats; findings are associations, not causes. No Worlds 2026 games are in the data.

## Threads and where to find the code

| Date | Thread | Charts (`charts/`) | Code |
|---|---|---|---|
| Oct 14 | Whose champion pool runs deepest? (15 Swiss Stage teams; pool depth vs win rate in 226 teams) | `worlds_fearless_depth.png`, `depth_vs_winrate.png` | `worlds2026_fearless_depth/` (own README) |
| Oct 16 | Is the top laner the least decisive role? (2,639 games) | `top_story_1_ahead.png` … `top_story_4_teams.png` | `analysis/top_story_roles.py`, `top_story_teams.py`, `top_story_charts.py` |
| Oct 17 | How do the 15 teams play? (style map, 9 numbers, 1,413 games) | `style_map.png` | `analysis/style_map.py`, `style_map_chart.py` |
| Oct 17 | Who assists whom in the first 15 minutes? | `assist_network_region.png` | `analysis/assist_network.py`, `assist_network_region_chart.py`, `analysis/roam_events.py`, `scripts/` |
| Oct 18 | Swiss round 1: who is favoured? (strength score to win chance, backtest) | `swiss_r1_predictions.png`, `swiss_r1_method.png`, `win_model_backtest.png` | `analysis/win_model.py`, `win_predict*.py`, `win_method_chart.py`, `win_backtest*.py` |

## Data

- **Oracle's Elixir** 2026 match data ([download](https://oracleselixir.com/tools/downloads)). Not redistributed here: put the CSV in `data/raw/oe/` (or use `scripts/fetch_oracles_elixir.py`).
- **Riot lolesports live stats** (unofficial endpoints), crawled per second with `scripts/crawl_teams.py` / `crawl_game.py` and rebuilt into kills and assists by `scripts/reconstruct_events.py`. `scripts/validate_batch.py` checks the rebuild against the Oracle's Elixir totals. Raw frames (`data/probe/`) are not in the repo.
- `data/processed/` holds the small result tables the charts are drawn from, so the chart scripts run without the raw data.

## Reproduce

```bash
pip install -r requirements.txt
# charts only, from the processed tables:
python3 analysis/style_map_chart.py
python3 analysis/top_story_charts.py
python3 analysis/assist_network_region_chart.py
python3 analysis/win_predict_chart.py && python3 analysis/win_method_chart.py && python3 analysis/win_backtest_chart.py
python3 worlds2026_fearless_depth/run_all.py        # needs the Oracle's Elixir CSV
# full rebuild (needs the CSV): style_map.py, top_story_roles.py, top_story_teams.py, win_predict.py, win_backtest.py
```

Charts are written to `charts/`. Scripts find the repo root from their own location, so run them from any directory.

## Caveats

League games, not Worlds. Rosters, patch, side and draft are mostly not modelled. Frames carry no map positions, and team tower counts in the frames disagree with Oracle's Elixir in some games, so towers are not used as ground truth.
