#!/usr/bin/env python3
"""(first 15 minutes only) Who assists whom: role-to-role assist flows per team (kills by the team, frames, first ~19 min). -> data/processed/assist_network.csv"""
import sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis")); sys.path.insert(0, str(ROOT / "scripts"))
import json, roam_events as re_
rec = re_.rec
CODES = {"GEN", "HLE", "T1", "DK", "AL", "BLG", "TES", "IG", "G2", "MKOI", "TLAW", "LYON", "TSW", "CFO", "LOS"}
games = pd.read_csv(rec.PROC / "roam_games.csv"); games = games[games.used == 1]; rows = []; gcount = {}
for gid, teams in zip(games.game_id, games.teams):
    d = json.loads((rec.PROBE / f"crawl_{gid}.json").read_text()); frames = sorted(d["frames"], key=lambda f: rec.parse(f["rfc460Timestamp"]))
    ts = [rec.parse(f["rfc460Timestamp"]) for f in frames]; ros = rec.roster(d["meta"]); re_.fix_names(ros, teams.split("/"))
    tag = {}
    for p in ros.values(): tag.setdefault(p["team"], p["name"].split()[0])
    clock, _ = rec.make_clock(frames, ts, None); ev = rec.increments(frames, ts); assign, assist_for, *_ = rec.match(ev, ros)
    for side in ("blue", "red"):
        if tag.get(side) in CODES: gcount[tag[side]] = gcount.get(tag[side], 0) + 1
    for di, (ki, _) in assign.items():
        if clock(ev["deaths"][di][0]) >= 900: continue
        killer = ev["kills"][ki][1]; side = ros[killer]["team"]
        if tag.get(side) not in CODES: continue
        kr = ros[killer]["role"]; rows.append((tag[side], gid, "kill", kr, kr))
        for pid, _lag in assist_for.get(di, []): rows.append((tag[side], gid, "assist", ros[pid]["role"], kr))
df = pd.DataFrame(rows, columns=["team", "game", "type", "src", "dst"])
kills = df[df.type == "kill"].groupby(["team", "dst"]).size().rename("kills"); asst = df[df.type == "assist"].groupby(["team", "src", "dst"]).size().rename("n").reset_index()
tk = df[df.type == "kill"].groupby("team").size(); asst["per_kill"] = asst.apply(lambda r: r.n / tk[r.team], axis=1)
asst.to_csv(rec.PROC / "assist_network.csv", index=False); kills.reset_index().to_csv(rec.PROC / "assist_network_kills.csv", index=False)
print(tk.to_dict(), gcount)
print(asst.sort_values("per_kill", ascending=False).head(12))
