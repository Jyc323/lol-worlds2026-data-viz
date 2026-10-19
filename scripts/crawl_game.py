#!/usr/bin/env python3
"""Crawl ONE finished game's livestats window frames end to end and measure it.

Follow-up to probe_data.py, which showed that a call without `startingTime`
returns only the first ~10 frames (game start, all zeros). This script answers:
  - how do frames page (what does startingTime do, how many frames per page)?
  - what is the real frame spacing (the "10 s" claim is unverified)?
  - which gameState values occur, and where does the game end?
  - can deaths / kills / assists be turned into events, and how ambiguous are they?
  - do the final per-player totals look sane (compare with a box score)?

    python3 scripts/crawl_game.py                 # first game in data/probe/game_ids.json
    python3 scripts/crawl_game.py GAME_ID         # a specific game

Output: data/probe/crawl_<gameId>.json (all frames) and crawl_report.md.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics as st
import sys
import time
from collections import Counter
from pathlib import Path

import requests

FEED_BASE = os.environ.get("LOL_FEED_BASE", "https://feed.lolesports.com/livestats/v1")
API_KEY = os.environ.get("LOL_API_KEY", "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z")
OUT = Path(__file__).resolve().parent.parent / "data" / "probe"
MAX_PAGES = 400
REPORT: list[str] = []


def say(s: str = "") -> None:
    print(s)
    REPORT.append(s)


def parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso10(t: dt.datetime) -> str:
    t = t.replace(microsecond=0)
    t = t.replace(second=t.second - t.second % 10)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def window(game_id: str, starting: str | None):
    r = requests.get(f"{FEED_BASE}/window/{game_id}", headers={"x-api-key": API_KEY},
                     params={"startingTime": starting} if starting else None, timeout=30)
    return r


def crawl(game_id: str) -> tuple[list[dict], dict]:
    r = window(game_id, None)
    r.raise_for_status()
    first = r.json()
    meta = first["gameMetadata"]
    frames = {f["rfc460Timestamp"]: f for f in first["frames"]}
    cur = parse(first["frames"][0]["rfc460Timestamp"])
    pages, stalls, log = 1, 0, []
    while pages < MAX_PAGES:
        cur_s = iso10(cur)
        r = window(game_id, cur_s)
        pages += 1
        if r.status_code != 200:
            log.append((cur_s, r.status_code, r.text[:120]))
            say(f"- page {pages} startingTime={cur_s}: HTTP {r.status_code} {r.text[:120]!r}")
            break
        fr = r.json().get("frames", [])
        new = [f for f in fr if f["rfc460Timestamp"] not in frames]
        for f in fr:
            frames[f["rfc460Timestamp"]] = f
        if not fr:
            say(f"- page {pages} startingTime={cur_s}: empty; stopping")
            break
        if pages <= 4:
            say(f"- page {pages} startingTime={cur_s}: {len(fr)} frames "
                f"({fr[0]['rfc460Timestamp']} -> {fr[-1]['rfc460Timestamp']}), {len(new)} new")
        last = parse(fr[-1]["rfc460Timestamp"])
        stalls = stalls + 1 if not new else 0
        if fr[-1].get("gameState") == "finished" or stalls >= 3:
            break
        nxt = parse(iso10(last))
        cur = nxt if nxt > cur else cur + dt.timedelta(seconds=10)
        time.sleep(0.15)
    say(f"- pages fetched: {pages}")
    ordered = [frames[k] for k in sorted(frames)]
    return ordered, meta


def analyse(frames: list[dict]) -> None:
    ts = [parse(f["rfc460Timestamp"]) for f in frames]
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    say(f"- total frames: {len(frames)}; span {ts[0].isoformat()} -> {ts[-1].isoformat()} "
        f"({(ts[-1] - ts[0]).total_seconds() / 60:.1f} min wall-clock)")
    if gaps:
        gc = Counter(round(g, 1) for g in gaps)
        say(f"- gap between consecutive frames: median {st.median(gaps):.2f}s, "
            f"min {min(gaps):.2f}s, max {max(gaps):.2f}s; most common {gc.most_common(5)}")
    states = Counter(f.get("gameState") for f in frames)
    say(f"- gameState counts: {dict(states)}")
    # game clock proxy: first frame where any gold > 0
    fin = frames[-1]
    for side in ("blueTeam", "redTeam"):
        row = [(p["participantId"], p["kills"], p["deaths"], p["assists"], p["creepScore"], p["totalGold"])
               for p in fin[side]["participants"]]
        say(f"- final {side} (id, K, D, A, CS, gold): {row}")
    say(f"- final team kills blue/red: {fin['blueTeam']['totalKills']}/{fin['redTeam']['totalKills']}; "
        f"towers {fin['blueTeam']['towers']}/{fin['redTeam']['towers']}")
    # monotonicity: KDA should never decrease
    bad = 0
    for a, b in zip(frames, frames[1:]):
        for side in ("blueTeam", "redTeam"):
            for pa, pb in zip(a[side]["participants"], b[side]["participants"]):
                if pb["deaths"] < pa["deaths"] or pb["kills"] < pa["kills"] or pb["assists"] < pa["assists"]:
                    bad += 1
    say(f"- frames where a K/D/A counter decreased: {bad}")
    # event reconstruction
    events, multi = [], 0
    for a, b in zip(frames, frames[1:]):
        d = []
        for side in ("blueTeam", "redTeam"):
            for pa, pb in zip(a[side]["participants"], b[side]["participants"]):
                if pb["deaths"] > pa["deaths"]:
                    d.append((side, pb["participantId"], pb["deaths"] - pa["deaths"]))
        if d:
            events.append({"t": b["rfc460Timestamp"], "deaths": d})
            if len(d) > 1 or any(x[2] > 1 for x in d):
                multi += 1
    total_deaths = sum(p["deaths"] for s in ("blueTeam", "redTeam") for p in fin[s]["participants"])
    seen = sum(x[2] for e in events for x in e["deaths"])
    say(f"- death events found by frame delta: {len(events)} windows, {seen} deaths "
        f"(final total {total_deaths}); windows with >1 death: {multi}")
    say("- ambiguity: at this frame spacing, a window with >1 death cannot say who died first.")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    gid = sys.argv[1] if len(sys.argv) > 1 else json.loads((OUT / "game_ids.json").read_text())[0]["game_id"]
    say(f"# Crawl report for game {gid}")
    say(f"Run at {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}")
    frames, meta = crawl(gid)
    (OUT / f"crawl_{gid}.json").write_text(json.dumps({"meta": meta, "frames": frames}))
    say(f"- patchVersion: {meta.get('patchVersion')}")
    analyse(frames)
    (OUT / "crawl_report.md").write_text("\n".join(REPORT) + "\n")
    print(f"\nReport written to {OUT / 'crawl_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
