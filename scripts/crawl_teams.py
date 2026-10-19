#!/usr/bin/env python3
"""Crawl every 2026 game of the chosen teams (default: the 15 teams that start Worlds 2026 in the Swiss stage,
over LCK, LPL, LEC, LCS, LCP, CBLOL, First Stand, MSI, EWC and Americas Cup): the first N minutes of each game,
plus a random share of games in full (those are the validation sample). Games already crawled for the earlier
4-team LCK plan are reused; that plan is kept as data/probe/team_games_lck4.json.

Run on your Mac (the cloud sandbox cannot reach lolesports):
    python3 scripts/crawl_teams.py --dry-run          # list the games and the plan, no crawling
    caffeinate -i python3 scripts/crawl_teams.py 2>&1 | tee data/probe/crawl_teams.log

Defaults: teams as above, games inside the Oracle's Elixir date range, first 19 game minutes
(an early roam at minute 14 needs its 2 minute result window plus the +-3 minute baseline windows),
10 % of games (seed 2026) crawled to the finished frame, 3 workers.

Design:
  * A game is crawled once; a cached file that is complete is reused, so the run can be stopped
    (Ctrl-C) and restarted. A partial file counts as complete when its game clock reached the cut,
    a full file when its last frame is 'finished'.
  * Pages are 10 s of game time. Technical pauses leave empty pages; the crawler steps through them
    and a pause does not count as game time for the cut.
  * Storage is thinned: a frame identical to the previous one except its timestamp is dropped.
    Frames arrive 0.2 s apart but state changes once per second, so this keeps about 1/5 of them
    without losing any state change. Same file name and layout as before (data/probe/crawl_<id>.json),
    plus a "crawl" key describing the mode.
  * The plan is saved first to data/probe/team_games.json. Failures go to data/probe/team_crawl_failed.json.
  * --skip-val: crawl every game as a partial game and skip the validation step (a cached full game is still reused).
  * After crawling, the full games are run through the fixed pass rule (reconstruct_events.analyse) and
    the game clock anchored at the start of the game is compared with the clock anchored on the
    Oracle's Elixir game length. Result: data/probe/team_validation_summary.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import reconstruct_events as rec
import validate_batch as vb

PROBE, PROC = rec.PROBE, rec.PROC
PLAN = PROBE / "team_games.json"
FAILED = PROBE / "team_crawl_failed.json"
SUMMARY = PROBE / "team_validation_summary.md"


# ---------------------------------------------------------------- plan
# Worlds 2026 main event, the 15 teams that start in the Swiss stage (the play-in winner joins later).
# Each team: (codes the lolesports schedule may use, lower-case parts of the team name, exact lower-case names).
TEAM_RULES = {
    "GEN": ({"GEN"}, ["gen.g"], []),
    "HLE": ({"HLE"}, ["hanwha"], []),
    "T1": ({"T1"}, [], ["t1"]),
    "DK": ({"DK", "DPLUS"}, ["dplus"], []),
    "AL": ({"AL"}, ["anyone"], []),
    "BLG": ({"BLG"}, ["bilibili"], []),
    "TES": ({"TES"}, ["top esports"], []),
    "IG": ({"IG", "SIG"}, ["invictus"], []),
    "G2": ({"G2"}, ["g2 esports"], []),
    "KOI": ({"KOI", "MKOI"}, ["movistar koi"], []),
    "TL": ({"TL", "TLAW"}, ["team liquid"], []),
    "LYON": ({"LYON"}, [], ["lyon"]),
    "TSW": ({"TSW"}, ["secret whales"], []),
    "CFO": ({"CFO"}, ["ctbc", "flying oyster"], []),
    "LOS": ({"LOS", "L\u00d8S"}, [], ["los", "l\u00f8s"]),
}
# slug -> lolesports leagueId (data/probe/leagues.json)
LEAGUE_IDS = {
    "lck": "98767991310872058", "lpl": "98767991314006698", "lec": "98767991302996019", "lcs": "98767991299243165",
    "lcp": "113476371197627891", "cblol-brazil": "98767991332355509", "first_stand": "113464388705111224",
    "msi": "98767991325878492", "ewc_lol": "116838530616006090", "americas_cup": "116096325848746167",
}
DEFAULT_TEAMS = list(TEAM_RULES)
DEFAULT_LEAGUES = list(LEAGUE_IDS)
BACKUP = PROBE / "team_games_lck4.json"


def canonical(team: dict) -> str | None:
    code = (team.get("code") or "").upper()
    name = (team.get("name") or "").lower()
    for canon, (codes, parts, exact) in TEAM_RULES.items():
        if code in codes or name in exact or any(p in name for p in parts):
            return canon
    return None


def league_matches(league_id: str, since: str, until: str, max_pages: int) -> list[dict]:
    """Completed matches of one league dated since..until, newest first."""
    import find_lck_game_ids as fl
    found, token = {}, None
    for _ in range(max_pages):
        params = {"hl": "en-US", "leagueId": league_id}
        if token:
            params["pageToken"] = token
        sched = fl.get(f"{fl.API_BASE}/getSchedule", params)["data"]["schedule"]
        events = sched.get("events", [])
        for e in events:
            if e.get("type") == "match" and e.get("state") == "completed" and since <= e["startTime"][:10] <= until:
                found[e["match"]["id"]] = e
        token = (sched.get("pages") or {}).get("older")
        oldest = min((e["startTime"][:10] for e in events), default=None)
        if not token or (oldest is not None and oldest < since):
            break
        time.sleep(0.1)
    return sorted(found.values(), key=lambda e: e["startTime"], reverse=True)


def plan_games(teams: set[str], leagues: list[str], since: str, until: str, max_pages: int, share: float, seed: int,
               old_modes: dict[str, str]) -> tuple[list[dict], dict]:
    """-> (games, info). info: codes seen per team, all teams seen per league, matches per league."""
    import find_lck_game_ids as fl
    games, codes, seen, per_league = [], {t: set() for t in teams}, {}, {}
    for slug in leagues:
        ms = league_matches(LEAGUE_IDS[slug], since, until, max_pages)
        keep = []
        for m in ms:
            tm = m["match"].get("teams", [])
            for t in tm:
                seen.setdefault(slug, {})[t.get("code") or "?"] = t.get("name")
            mine = sorted({c for t in tm if (c := canonical(t)) in teams})
            for t in tm:
                if canonical(t) in teams:
                    codes[canonical(t)].add(t.get("code"))
            if mine:
                keep.append((m, mine))
        per_league[slug] = (len(ms), len(keep))
        print(f"{slug:<13} {len(ms):>4} completed matches {since} -> {until}; {len(keep)} include a wanted team", flush=True)
        for i, (m, mine) in enumerate(sorted(keep, key=lambda x: x[0]["startTime"]), 1):
            try:
                for g in fl.games_of(m):
                    g["league"], g["mine"] = slug, "/".join(mine)
                    games.append(g)
            except Exception as e:  # one bad match must not stop the plan
                print(f"  match {m['match']['id']}: {type(e).__name__}: {e}")
            time.sleep(0.1)
            if i % 50 == 0:
                print(f"  {slug}: {i}/{len(keep)} matches listed ({len(games)} games)", flush=True)
    uniq = {g["game_id"]: g for g in games}
    games = sorted(uniq.values(), key=lambda g: (g["start"], g["number"]))
    # keep the mode of games that were already planned (they may be crawled), sample the rest up to the share
    want_full = max(1, round(share * len(games)))
    kept_full = {g["game_id"] for g in games if old_modes.get(g["game_id"]) == "full"}
    fresh = [g["game_id"] for g in games if g["game_id"] not in old_modes]
    extra = set(random.Random(seed).sample(fresh, min(len(fresh), max(0, want_full - len(kept_full))))) if fresh else set()
    for g in games:
        g["mode"] = "full" if g["game_id"] in kept_full or g["game_id"] in extra else "partial"
    info = {"codes": {t: sorted(c for c in v if c) for t, v in codes.items()}, "per_league": per_league,
            "teams_seen": {k: v for k, v in seen.items()}}
    return games, info


# ---------------------------------------------------------------- crawl
def frame_key(f: dict) -> str:
    return json.dumps({k: v for k, v in f.items() if k != "rfc460Timestamp"}, sort_keys=True)


def crawl_one(gid: str, stop_s: float | None) -> dict:
    """Crawl one game. stop_s = game seconds to stop at (None = until the finished frame)."""
    t_begin = time.time()
    try:
        first = vb.fetch_window(gid)
    except RuntimeError as e:
        if "HTTP 204" in str(e):
            raise RuntimeError("the feed has no frames for this game (HTTP 204)") from None
        raise
    meta = first["gameMetadata"]
    frames: dict[str, dict] = {}
    parsed: dict[str, dt.datetime] = {}
    state = {"t0": None}

    def add(fr):
        new = 0
        for f in fr:
            k = f["rfc460Timestamp"]
            if k not in frames:
                new += 1
                parsed[k] = rec.parse(k)
                if state["t0"] is None and any(p["totalGold"] > 0 for p in rec.players(f).values()):
                    state["t0"] = parsed[k]
            frames[k] = f  # the newest response wins: the last frame is first served as in_game, later as finished
        return new

    def clock_now():
        """Game seconds at the newest frame: wall time since the first gold frame minus 'paused' time."""
        if state["t0"] is None:
            return 0.0
        ks = sorted(frames, key=parsed.get)
        total = (parsed[ks[-1]] - state["t0"]).total_seconds()
        for a, b in zip(ks, ks[1:]):
            if frames[a].get("gameState") == "paused":
                total -= max(0.0, (parsed[b] - max(parsed[a], state["t0"])).total_seconds())
        return total

    add(first["frames"])
    cur = rec.parse(first["frames"][0]["rfc460Timestamp"])
    pages, idle, reached = 1, 0, "limit"
    while pages < vb.MAX_PAGES:
        fr = vb.fetch_window(gid, vb.iso10(cur)).get("frames", [])
        pages += 1
        new = add(fr)
        if fr and fr[-1].get("gameState") == "finished":
            reached = "finished"
            break
        if stop_s is not None and clock_now() >= stop_s:
            reached = "cut"
            break
        if new:
            idle = 0
            nxt = rec.parse(vb.iso10(rec.parse(fr[-1]["rfc460Timestamp"])))
            cur = nxt if nxt > cur else cur + dt.timedelta(seconds=10)
        else:
            idle += 1
            if idle >= vb.MAX_IDLE_PAGES:
                reached = "gap"
                break
            cur += dt.timedelta(seconds=10)
        time.sleep(0.1)

    ordered = sorted(frames.values(), key=lambda f: parsed[f["rfc460Timestamp"]])
    thin, prev = [], None
    for i, f in enumerate(ordered):
        k = frame_key(f)
        if k != prev or i == len(ordered) - 1:  # always keep the last frame
            thin.append(f)
        prev = k
    info = {"v": 2, "mode": "full" if stop_s is None else "partial", "stop_s": stop_s, "reached": reached,
            "raw_frames": len(ordered), "kept_frames": len(thin), "pages": pages}
    path = PROBE / f"crawl_{gid}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"meta": meta, "frames": thin, "crawl": info}))
    os.replace(tmp, path)
    info["secs"] = time.time() - t_begin
    return info


def is_complete(gid: str, stop_s: float | None) -> bool:
    path = PROBE / f"crawl_{gid}.json"
    if not path.exists():
        return False
    d = json.loads(path.read_text())
    frames = d["frames"]
    if not frames:
        return False
    info = d.get("crawl") or {}
    if info and info.get("v") != 2 and info.get("mode") == "full":
        return False  # v1 files lost the finished frame when it shared a timestamp with an in_game frame
    if frames[-1].get("gameState") == "finished":
        return True  # a full crawl satisfies either mode
    if stop_s is None:
        return False
    return info.get("reached") == "cut" and (info.get("stop_s") or 0) >= stop_s


# ---------------------------------------------------------------- validation of the full sample
def clock_offsets(gid: str):
    """Seconds between the start-anchored clock and the OE-anchored clock at 5 / 10 / 15 game minutes."""
    v = json.loads((PROC / f"validation_{gid}.json").read_text())
    if not v.get("gamelength_s"):
        return None
    d = json.loads((PROBE / f"crawl_{gid}.json").read_text())
    frames = sorted(d["frames"], key=lambda f: rec.parse(f["rfc460Timestamp"]))
    ts = [rec.parse(f["rfc460Timestamp"]) for f in frames]
    ca, _ = rec.make_clock(frames, ts, v["gamelength_s"])
    cb, info = rec.make_clock(frames, ts, None)
    out = []
    for m in (5, 10, 15):
        t = info["t0"] + dt.timedelta(seconds=m * 60 + 1)
        out.append(round(cb(t) - ca(t), 1))
    return out


def validate_full(games: list[dict]) -> None:
    full = [g["game_id"] for g in games if g["mode"] == "full" and is_complete(g["game_id"], None)
            and json.loads((PROBE / f"crawl_{g['game_id']}.json").read_text())["frames"][-1].get("gameState") == "finished"]
    if not full:
        print("No complete full games to validate.")
        return
    results = []
    for g in full:
        try:
            results.append(rec.analyse(g, quiet=True, write_report=True))
        except Exception as e:
            results.append({"gid": g, "status": "FAIL", "fails": [f"analysis failed: {type(e).__name__}: {e}"], "notes": []})
    text = vb.summary(results)
    offs = [o for o in (clock_offsets(m["gid"]) for m in results if m.get("gamelength_s") or m["status"] != "FAIL") if o]
    if offs:
        flat = [abs(x) for o in offs for x in o]
        text += (f"\n- Start-anchored clock minus OE-anchored clock at 5/10/15 min ({len(offs)} games): "
                 f"median |offset| {st.median(flat):.1f}s, max {max(flat):.1f}s. "
                 f"Partial games use the start-anchored clock.\n")
    SUMMARY.write_text(text)
    print("\n" + text)


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", nargs="+", default=DEFAULT_TEAMS, help="canonical team names (see TEAM_RULES)")
    ap.add_argument("--leagues", nargs="+", default=DEFAULT_LEAGUES, help="league slugs (see LEAGUE_IDS)")
    ap.add_argument("--minutes", type=float, default=19, help="game minutes to crawl for partial games")
    ap.add_argument("--share", type=float, default=0.10, help="share of games crawled in full (validation sample)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-pages", type=int, default=60, help="schedule pages to page back through, per league")
    ap.add_argument("--since", help="earliest date YYYY-MM-DD (default: first date in the Oracle's Elixir file)")
    ap.add_argument("--limit", type=int, help="crawl only the first N planned games (test run)")
    ap.add_argument("--replan", action="store_true", help="ignore the saved plan and read the schedule again")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-val", action="store_true",
                    help="crawl every game as a partial game (no full-game validation sample, no validation step at the end)")
    ap.add_argument("--probe", action="store_true", help="crawl 2 games per league (the newest) to check the feed, then stop")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    teams = {t.upper() for t in args.teams}
    unknown = teams - set(TEAM_RULES)
    if unknown or set(args.leagues) - set(LEAGUE_IDS):
        raise SystemExit(f"unknown teams {sorted(unknown)} or leagues {sorted(set(args.leagues) - set(LEAGUE_IDS))}")
    PROBE.mkdir(parents=True, exist_ok=True)
    plan, saved = None, None
    if PLAN.exists():
        saved = json.loads(PLAN.read_text())
        if not BACKUP.exists():
            BACKUP.write_text(PLAN.read_text())  # the 4-team LCK plan stays available
        if not args.replan and set(saved["teams"]) == teams and saved["minutes"] == args.minutes \
                and saved["share"] == args.share and saved["seed"] == args.seed \
                and saved.get("leagues") == sorted(args.leagues):
            plan = saved["games"]
            print(f"Using saved plan {PLAN.name}: {len(plan)} games")
    if plan is None:
        lo, hi = vb.oe_date_range()
        lo = args.since or lo
        print(f"Oracle's Elixir covers {lo} -> {hi}")
        old_modes = {g["game_id"]: g["mode"] for g in saved["games"]} if saved else {}
        plan, info = plan_games(teams, args.leagues, lo, hi, args.max_pages, args.share, args.seed, old_modes)
        PLAN.write_text(json.dumps({"teams": sorted(teams), "codes": info["codes"], "leagues": sorted(args.leagues),
                                    "minutes": args.minutes, "share": args.share, "seed": args.seed, "games": plan}, indent=1))
        (PROBE / "league_teams.json").write_text(json.dumps(info["teams_seen"], indent=1, ensure_ascii=False))
        silent = [t for t in sorted(teams) if not info["codes"][t]]
        if silent:
            print(f"\nNo match found for: {silent}. Check data/probe/league_teams.json for the codes and names the "
                  f"schedule uses and add them to TEAM_RULES.")
    if args.skip_val:  # runtime override only: the saved plan keeps its validation sample for later
        plan = [{**g, "mode": "partial"} for g in plan]
        print("--skip-val: every game is crawled as a partial game; no full-game validation")
    nfull = sum(g["mode"] == "full" for g in plan)
    by_team = {t: sum(t in g.get("mine", "").split("/") for g in plan) for t in sorted(teams)}
    print(f"\n{len(plan)} games: {nfull} in full (validation sample), {len(plan) - nfull} first {args.minutes:g} min")
    print(f"per team: {by_team}")
    by_league = {}
    for g in plan:
        by_league[g.get("league", "lck")] = by_league.get(g.get("league", "lck"), 0) + 1
    print(f"per league: {by_league}")
    print(f"first {plan[0]['start'][:10]} -> last {plan[-1]['start'][:10]}")
    left = [g for g in plan if not is_complete(g["game_id"], None if g["mode"] == "full" else args.minutes * 60)]
    nf = sum(g["mode"] == "full" for g in left)
    print(f"already crawled: {len(plan) - len(left)}; still to crawl: {len(left)} ({nf} full, {len(left) - nf} partial); "
          f"rough time with {args.workers} workers: {(nf * 28 + (len(left) - nf) * 13) / 60 * 3 / args.workers:.0f} min "
          f"(guess from the first run: about 13 s per partial and 28 s per full game at 3 workers)")
    if args.dry_run:
        for g in plan:
            print(f"  {g['start'][:10]} {g.get('league', 'lck'):<12} {g['teams']:<9} game {g['number']}  {g['mode']:<7} {g['game_id']}")
        return 0
    if args.validate_only:
        validate_full(plan)
        return 0
    if args.probe:
        for slug in sorted({g.get("league", "lck") for g in plan}):
            for g in [x for x in plan if x.get("league", "lck") == slug][-2:]:
                try:
                    info = crawl_one(g["game_id"], args.minutes * 60)
                    print(f"{slug:<13} {g['start'][:10]} {g['teams']:<9} OK  {info['reached']}, {info['kept_frames']} frames, {info['secs']:.0f}s")
                except Exception as e:
                    print(f"{slug:<13} {g['start'][:10]} {g['teams']:<9} FAILED {type(e).__name__}: {e}")
        return 0

    work = plan[:args.limit] if args.limit else plan
    todo = [g for g in work if not is_complete(g["game_id"], None if g["mode"] == "full" else args.minutes * 60)]
    print(f"{len(work) - len(todo)} already crawled, {len(todo)} to go, {args.workers} workers\n")
    failed, done, t_run = {}, 0, time.time()
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        futs = {ex.submit(crawl_one, g["game_id"], None if g["mode"] == "full" else args.minutes * 60): g for g in todo}
        for fut in as_completed(futs):
            g = futs[fut]
            done += 1
            try:
                info = fut.result()
                eta = (time.time() - t_run) / done * (len(todo) - done) / 60
                print(f"[{done}/{len(todo)}] {g['start'][:10]} {g['teams']:<9} g{g['number']} {info['mode']:<7} "
                      f"{info['reached']:<8} {info['pages']} pages, {info['kept_frames']}/{info['raw_frames']} frames, "
                      f"{info['secs']:.0f}s  (about {eta:.0f} min left)", flush=True)
            except Exception as e:
                failed[g["game_id"]] = f"{type(e).__name__}: {e}"
                print(f"[{done}/{len(todo)}] FAILED {g['game_id']}: {failed[g['game_id']]}", flush=True)
    except KeyboardInterrupt:
        print("\nStopped. Finished games are saved; run the same command again to continue.")
        ex.shutdown(wait=False, cancel_futures=True)
        return 130
    ex.shutdown()
    FAILED.write_text(json.dumps(failed, indent=1))
    print(f"\nCrawl done in {(time.time() - t_run) / 60:.0f} min; {len(failed)} failed"
          f"{' (see ' + FAILED.name + '; rerun to retry)' if failed else ''}")
    if not args.limit and not args.skip_val:
        validate_full(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
