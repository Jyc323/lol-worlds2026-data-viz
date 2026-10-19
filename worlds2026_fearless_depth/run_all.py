#!/usr/bin/env python3
"""Regenerate both charts and write output/meta.json (data fingerprint + parameters).

    python3 worlds2026_fearless_depth/run_all.py

Needs the Oracle's Elixir 2026 CSV in data/raw/oe/ (or set OE_DIR).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import scipy
import matplotlib

import depth_heatmap
import depth_vs_winrate
from common import OUT, RAW, SEED, WORLDS_TEAMS

YEAR = 2026
K = 10
RECENT = 30


def main() -> int:
    csv = RAW / f"{YEAR}_LoL_esports_match_data_from_OraclesElixir.csv"
    if not csv.exists():
        print(f"missing {csv}; see README for how to get it")
        return 1
    md5 = hashlib.md5(csv.read_bytes()).hexdigest()
    df = pd.read_csv(csv, low_memory=False, usecols=["gameid", "date"])
    for mod in (depth_heatmap, depth_vs_winrate):
        sys.argv = [mod.__name__, "--k", str(K)] + (["--recent", str(RECENT)] if mod is depth_heatmap else [])
        if mod.main():
            return 1
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_file": csv.name, "data_md5": md5, "games_in_file": int(df.gameid.nunique()),
        "latest_game_date": str(df.date.max()),
        "params": {"k_games": K, "starters_from_last_n_team_games": RECENT, "min_team_games_winrate_chart": depth_vs_winrate.MIN_GAMES,
                   "bootstrap_seed": SEED},
        "swiss_stage_direct_teams": WORLDS_TEAMS,
        "play_in_teams_excluded": sorted(depth_vs_winrate.PLAYIN),
        "versions": {"pandas": pd.__version__, "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print("wrote", OUT / "meta.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
