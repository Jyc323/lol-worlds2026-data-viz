#!/usr/bin/env python3
"""Sample LCK games across the 2026 season, crawl their livestats frames (resumable),
reconstruct events and validate every game against Oracle's Elixir.

Run on your Mac (the cloud sandbox cannot reach lolesports):
    python3 scripts/validate_batch.py                    # 10 games from 10 different series, only inside the OE date range
    python3 scripts/validate_batch.py --n 10 --workers 3
    python3 scripts/validate_batch.py --games ID1 ID2    # explicit gameIds; cached ones need no network

Games already crawled (data/probe/crawl_<id>.json) are reused, so an interrupted run can be
restarted. Roughly 235 requests per game (one page per 10 s of game time).

Pass rule (fixed before the run, defined in reconstruct_events.verdict): a game passes only if
the crawl reached the 'finished' frame; an OE game with the same champions on that day exists;
final K/D/A of all 10 players equal OE; team kills/towers/dragons/barons equal OE; reconstructed
kills/deaths/assists at 10/15/20/25 min equal OE wherever OE has them; every kill increment is
matched to a death and every assist to a kill within 1 s. Deaths without a champion killer and
several deaths in one 1 s update are not failures; they are counted and reported.

Writes data/probe/validation_sample.json and data/probe/validation_summary.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import reconstruct_events as rec  # same folder

PROBE = rec.PROBE
FEED_BASE = os.environ.get("LOL_FEED_BASE", "https://feed.lolesports.com/livestats/v1")
API_KEY = os.environ.get("LOL_API_KEY", "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z")
HEADERS = {"x-api-key": API_KEY}
MAX_PAGES = 600       # ~100 min of game time at one page per 10 s
MAX_IDLE_PAGES = 120  # consecutive empty pages tolerated: a technical pause leaves a gap in the feed


# ---------------------------------------------------------------- crawling
def iso10(t: dt.datetime) -> str:
    t = t.replace(microsecond=0)
    t = t.replace(second=t.second - t.second % 10)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_window(gid: str, starting: str | None = None) -> dict:
    import requests
    for attempt in range(6):
        r = requests.get(f"{FEED_BASE}/window/{gid}", headers=HEADERS,
                         params={"startingTime": starting} if starting else None, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        raise RuntimeError(f"window/{gid} startingTime={starting}: HTTP {r.status_code}")
    raise RuntimeError(f"window/{gid} startingTime={starting}: gave up after retries")


def crawl_game(gid: str) -> tuple[int, float]:
    t_start = time.time()
    first = fetch_window(gid)
    meta = first["gameMetadata"]
    frames = {f["rfc460Timestamp"]: f for f in first["frames"]}
    cur = rec.parse(first["frames"][0]["rfc460Timestamp"])
    pages, idle = 1, 0
    while pages < MAX_PAGES:
        fr = fetch_window(gid, iso10(cur)).get("frames", [])
        pages += 1
        new = [f for f in fr if f["rfc460Timestamp"] not in frames]
        for f in fr:
            frames[f["rfc460Timestamp"]] = f
        if fr and fr[-1].get("gameState") == "finished":
            break
        if new:
            idle = 0
            nxt = rec.parse(iso10(rec.parse(fr[-1]["rfc460Timestamp"])))
            cur = nxt if nxt > cur else cur + dt.timedelta(seconds=10)
        else:
            idle += 1  # no frames: keep stepping forward through a pause instead of stopping
            if idle >= MAX_IDLE_PAGES:
                break
            cur = cur + dt.timedelta(seconds=10)
        time.sleep(0.1)
    ordered = sorted(frames.values(), key=lambda f: rec.parse(f["rfc460Timestamp"]))
    (PROBE / f"crawl_{gid}.json").write_text(json.dumps({"meta": meta, "frames": ordered}))
    return pages, time.time() - t_start


def crawl_complete(gid: str) -> bool:
    """A cached crawl counts only if it reached the finished frame (older runs stopped at pauses)."""
    path = PROBE / f"crawl_{gid}.json"
    if not path.exists():
        return False
    frames = json.loads(path.read_text())["frames"]
    return bool(frames) and frames[-1].get("gameState") == "finished"


# ---------------------------------------------------------------- sampling
def oe_date_range() -> tuple[str, str]:
    """First and last game date in the Oracle's Elixir file (YYYY-MM-DD)."""
    import csv
    lo = hi = None
    with rec.OE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            d = row["date"][:10]
            lo = d if lo is None or d < lo else lo
            hi = d if hi is None or d > hi else hi
    return lo, hi


def all_completed_matches(max_pages: int, since: str, until: str) -> list[dict]:
    """Completed LCK matches dated since..until (YYYY-MM-DD), newest first."""
    import find_lck_game_ids as fl
    found, token = {}, None
    for _ in range(max_pages):
        params = {"hl": "en-US", "leagueId": fl.LCK_LEAGUE_ID}
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
            break  # past the start of the Oracle's Elixir coverage
    return sorted(found.values(), key=lambda e: e["startTime"], reverse=True)


def sample(n: int, max_pages: int, since: str, until: str) -> tuple[list[dict], tuple]:
    import find_lck_game_ids as fl
    ms = all_completed_matches(max_pages, since, until)
    if not ms:
        raise SystemExit("No completed LCK matches found.")
    k = min(n, len(ms))
    idx = sorted({round(i * (len(ms) - 1) / max(k - 1, 1)) for i in range(k)})
    picked = []
    for j, i in enumerate(idx):
        games = fl.games_of(ms[i])
        if games:
            picked.append(games[j % len(games)])  # vary game number across series
    return picked, (ms[-1]["startTime"], ms[0]["startTime"], len(ms))


# ---------------------------------------------------------------- summary
def summary(results: list[dict]) -> str:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out = [f"# Validation summary", f"Run at {now}", "",
           "Pass rule: see the docstring of scripts/validate_batch.py (fixed before the run).", "",
           "| game | match-up | date (UTC) | verdict | deaths / kills / assists | no-killer deaths | "
           "multi-death 1 s updates | timeline @10/15/20/25 | notes |",
           "|---|---|---|---|---|---|---|---|---|"]
    for m in results:
        tl = f"{m.get('timeline_match', 0)}/{m.get('timeline_total', 0)}"
        why = "; ".join(m.get("fails", []) + m.get("notes", []))
        out.append(f"| {m['gid']} | {m.get('blue') or '?'} vs {m.get('red') or '?'} | {m.get('date') or '?'} | "
                   f"{m['status']} | {m.get('deaths', '?')} / {m.get('kills', '?')} / {m.get('assists', '?')} | "
                   f"{m.get('unmatched_deaths', '?')} | {m.get('multi_death_updates', '?')} | {tl} | {why} |")
    ok = [m for m in results if m["status"] == "PASS"]
    out += ["", f"**{len(ok)}/{len(results)} games pass.**"]
    from collections import Counter
    event_ok = [m for m in results if m.get("oe_gid") and not [f for f in m["fails"] if "team totals" not in f]]
    diffs = [d for m in results for d in m.get("team_diffs", [])]
    fields = Counter(d.split()[1].rstrip(":") for d in diffs)
    out.append(f"- Event checks alone (K/D/A, 10/15/20/25 timeline, kill/assist matching; team totals excluded): "
               f"{len(event_ok)}/{len(results)} games pass.")
    out.append(f"- Team-total differences vs OE: {len(diffs)} team sides in {sum(1 for m in results if m.get('team_diffs'))} games; "
               f"by field: {dict(fields) or 'none'}.")
    done = [m for m in results if "deaths" in m]
    d = sum(m["deaths"] for m in done)
    if d:
        multi = sum(m["deaths_in_multi_death_updates"] for m in done)
        nokill = sum(m["unmatched_deaths"] for m in done)
        out.append(f"- Attribution: {multi} of {d} deaths ({100 * multi / d:.1f}%) share a 1 s update with another death "
                   f"(only these can cross-match killers); {nokill} deaths have no champion killer.")
        meds = sorted(m["state_update_median_s"] for m in done)
        out.append(f"- Median gap between state updates per game: {meds[0]:.2f}s to {meds[-1]:.2f}s.")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-pages", type=int, default=12, help="schedule pages to page back through")
    ap.add_argument("--since", help="earliest game date YYYY-MM-DD (default: first date in the Oracle's Elixir file)")
    ap.add_argument("--games", nargs="*", help="explicit lolesports gameIds")
    args = ap.parse_args()

    if args.games:
        picked = [{"game_id": g} for g in args.games]
    else:
        lo, hi = oe_date_range()
        lo = args.since or lo
        print(f"Oracle's Elixir covers {lo} -> {hi}; sampling only inside that range")
        picked, span = sample(args.n, args.max_pages, lo, hi)
        print(f"Schedule: {span[2]} completed LCK matches, {span[0][:10]} -> {span[1][:10]}; "
              f"sampled {len(picked)} games from different series")
    for p in picked:
        print(f"  {p.get('start', '')[:10]} {p.get('teams', ''):<10} game {p.get('number', '?')}  gameId={p['game_id']}")
    PROBE.mkdir(parents=True, exist_ok=True)
    (PROBE / "validation_sample.json").write_text(json.dumps(picked, indent=2))

    todo = [p["game_id"] for p in picked if not crawl_complete(p["game_id"])]
    errors: dict[str, str] = {}
    if todo:
        print(f"\nCrawling {len(todo)} games, {args.workers} at a time (about 235 requests each)...")
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(crawl_game, g): g for g in todo}
            for fut in as_completed(futs):
                g = futs[fut]
                try:
                    pages, secs = fut.result()
                    print(f"  crawled {g}: {pages} pages in {secs:.0f}s")
                except Exception as e:  # keep going; the failure is reported in the summary
                    errors[g] = f"crawl failed: {type(e).__name__}: {e}"
                    print(f"  FAILED  {g}: {errors[g]}")
    else:
        print("\nAll games already crawled; skipping network.")

    results = []
    for p in picked:
        g = p["game_id"]
        if g in errors:
            results.append({"gid": g, "status": "FAIL", "fails": [errors[g]], "notes": []})
            continue
        try:
            results.append(rec.analyse(g, quiet=True, write_report=False))
        except Exception as e:
            results.append({"gid": g, "status": "FAIL", "fails": [f"analysis failed: {type(e).__name__}: {e}"], "notes": []})
    text = summary(results)
    (PROBE / "validation_summary.md").write_text(text)
    print("\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
