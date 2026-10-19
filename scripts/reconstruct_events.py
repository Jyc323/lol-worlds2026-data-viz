#!/usr/bin/env python3
"""Reconstruct champion-kill events from livestats frames and validate them
against Oracle's Elixir.

    python3 scripts/reconstruct_events.py GAME_ID [GAME_ID ...]

Needs data/probe/crawl_<GAME_ID>.json (from crawl_game.py or validate_batch.py) and the OE CSV.
Writes data/processed/events_<GAME_ID>.csv, data/processed/validation_<GAME_ID>.json and
data/probe/reconstruct_report.md (last game only).

Frames are sorted by PARSED time. crawl_game.py sorts by the raw timestamp string, which
misorders timestamps with and without fractional seconds.

Pass rule (fixed before the 10-game run; see verdict()): a game passes only if the crawl
reached the 'finished' frame, an OE game with the same champions on the same day is found,
final K/D/A of all 10 players equal OE, team kills/towers/dragons/barons equal OE, the
reconstructed kills/deaths/assists at 10/15/20/25 min equal OE wherever OE has them, and
every kill increment is matched to a death and every assist to a kill within 1 s.
Deaths without a champion killer and several deaths in one 1 s update are NOT failures:
they are counted and reported.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "data" / "probe"
PROC = ROOT / "data" / "processed"
OE = ROOT / "data" / "raw" / "oe" / "2026_LoL_esports_match_data_from_OraclesElixir.csv"
WINDOW_S = 5.0      # a kill/assist counter change this close to a death is the same event
MAX_LAG_OK_S = 1.0  # pass rule: matched pairs must be within this many seconds
ALIAS = {"monkeyking": "wukong", "renata": "renataglasc", "nunu": "nunuwillump"}


def norm(name: str) -> str:
    """Champion key that survives lolesports-id vs OE spelling (Kai'Sa/Kaisa, MonkeyKing/Wukong)."""
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    return ALIAS.get(k, k)


def parse(ts: str) -> dt.datetime:
    base, _, frac = ts.rstrip("Z").partition(".")
    t = dt.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    return t + dt.timedelta(microseconds=int((frac + "000000")[:6]))


def players(f: dict) -> dict[int, dict]:
    return {p["participantId"]: p for side in ("blueTeam", "redTeam") for p in f[side]["participants"]}


def roster(meta: dict) -> dict[int, dict]:
    r = {}
    for side in ("blueTeamMetadata", "redTeamMetadata"):
        for p in meta[side]["participantMetadata"]:
            r[p["participantId"]] = {"team": "blue" if side.startswith("blue") else "red",
                                     "role": p["role"], "name": p["summonerName"], "champ": p["championId"]}
    return r


def num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def pct(vals: list[float], q: float) -> float:
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


def stat_sig(f: dict):
    return tuple((p["totalGold"], p["creepScore"], p["kills"], p["deaths"], p["assists"], p["level"])
                 for p in players(f).values())


def hp_sig(f: dict):
    return tuple(p["currentHealth"] for p in players(f).values())


def update_times(frames, ts, sig):
    out, prev = [], None
    for f, t in zip(frames, ts):
        s = sig(f)
        if s != prev:
            out.append(t)
        prev = s
    return out


def gap_stats(times):
    g = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return st.median(g), pct(g, .9), max(g)


# ---------------------------------------------------------------- events
def increments(frames, ts):
    ev = {"kills": [], "deaths": [], "assists": []}
    prev = players(frames[0])
    for f, t in zip(frames[1:], ts[1:]):
        cur = players(f)
        for pid, p in cur.items():
            for k in ev:
                d = p[k] - prev[pid][k]
                if d > 0:
                    ev[k] += [(t, pid)] * d
        prev = cur
    for k in ev:
        ev[k].sort()
    return ev


def match(ev, ros):
    deaths, kills, assists = ev["deaths"], ev["kills"], ev["assists"]
    pairs = []
    for di, (td, victim) in enumerate(deaths):
        for ki, (tk, killer) in enumerate(kills):
            if ros[killer]["team"] != ros[victim]["team"]:
                lag = (tk - td).total_seconds()
                if abs(lag) <= WINDOW_S:
                    pairs.append((abs(lag), di, ki, lag))
    pairs.sort()
    used_d, used_k, assign = set(), set(), {}
    for _, di, ki, lag in pairs:
        if di not in used_d and ki not in used_k:
            used_d.add(di)
            used_k.add(ki)
            assign[di] = (ki, lag)
    assist_for, orphans = defaultdict(list), []
    for ta, pid in assists:
        best = None
        for di, (ki, _) in assign.items():
            killer = kills[ki][1]
            if ros[killer]["team"] != ros[pid]["team"] or killer == pid:
                continue
            lag = (ta - deaths[di][0]).total_seconds()
            if abs(lag) <= WINDOW_S and (best is None or abs(lag) < best[0]):
                best = (abs(lag), di, lag)
        if best:
            assist_for[best[1]].append((pid, best[2]))
        else:
            orphans.append((ta, pid))
    n_cand, n_near = {}, {}
    for di, (td, victim) in enumerate(deaths):
        n_cand[di] = sum(1 for (tk, killer) in kills
                         if ros[killer]["team"] != ros[victim]["team"] and abs((tk - td).total_seconds()) <= WINDOW_S)
        n_near[di] = sum(1 for dj, (tj, _) in enumerate(deaths) if dj != di and abs((tj - td).total_seconds()) <= WINDOW_S)
    return assign, assist_for, orphans, used_k, n_cand, n_near


# ---------------------------------------------------------------- OE
def load_oe(first_ts):
    days = {(first_ts + dt.timedelta(days=k)).strftime("%Y-%m-%d") for k in (-1, 0, 1)}
    games = defaultdict(list)
    with OE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["date"][:10] in days:
                games[row["gameid"]].append(row)
    return games


def find_oe(games, ros, first_ts):
    want = sorted(norm(p["champ"]) for p in ros.values())
    best = None
    for gid, rows in games.items():
        if sorted(norm(r["champion"]) for r in rows if r["position"] != "team") != want:
            continue
        d = dt.datetime.strptime(rows[0]["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        diff = abs((d - first_ts).total_seconds())
        if best is None or diff < best[0]:
            best = (diff, gid, rows)
    return best


def make_clock(frames, ts, gamelength):
    """Pause-aware game clock. Returns (clock, info): clock(t) = game seconds at wall time t.

    Anchored at the last frame when the OE game length is known (so clock(last frame) = gamelength),
    otherwise at the first non-zero-gold frame. Time spent in a 'paused' state is not game time.
    """
    t_end = ts[-1]
    t0 = next((t for f, t in zip(frames, ts) if any(p["totalGold"] > 0 for p in players(f).values())), ts[0])
    pauses = [(ts[i], ts[i + 1]) for i in range(len(frames) - 1) if frames[i].get("gameState") == "paused"]

    def active(a, b):
        total = (b - a).total_seconds()
        for pa, pb in pauses:
            total -= max(0.0, (min(pb, b) - max(pa, a)).total_seconds())
        return total

    def clock(t):
        return gamelength - active(t, t_end) if gamelength else active(t0, t)

    return clock, {"t0": t0, "t_end": t_end, "pauses": pauses, "active": active}


def timeline_check(by_champ, ros, deaths, kills, assign, assist_for, clock, say):
    mism = total = 0
    for mark in (10, 15, 20, 25):
        lim = mark * 60
        got = {pid: {"kills": 0, "deaths": 0, "assists": 0} for pid in ros}
        for di, (td, victim) in enumerate(deaths):
            if clock(td) <= lim:
                got[victim]["deaths"] += 1
                if di in assign:
                    got[kills[assign[di][0]][1]]["kills"] += 1
                for apid, _ in assist_for.get(di, []):
                    got[apid]["assists"] += 1
        for pid, r in ros.items():
            o = by_champ[norm(r["champ"])]
            for k in ("kills", "deaths", "assists"):
                exp = num(o.get(f"{k}at{mark}"))
                if exp is None:
                    continue
                total += 1
                if got[pid][k] != exp:
                    mism += 1
                    say(f"  - @{mark}min {r['name']} {k}: reconstructed {got[pid][k]} vs OE {exp}")
    return total - mism, total


def verdict(m: dict) -> list[str]:
    fails = []
    if not m["finished"]:
        fails.append("crawl never reached the finished frame")
    if not m.get("oe_gid"):
        fails.append("no OE game with the same champions on that day")
    else:
        if m["kda_match"] < 10:
            fails.append(f"final K/D/A differs from OE for {10 - m['kda_match']} players")
        if m["team_mismatches"]:
            fails.append(f"{m['team_mismatches']} team totals differ from OE ({'; '.join(m.get('team_diffs', []))})")
        if m["timeline_match"] < m["timeline_total"]:
            fails.append(f"{m['timeline_total'] - m['timeline_match']} of {m['timeline_total']} @10/15/20/25 counts differ from OE")
    if m["unmatched_kills"]:
        fails.append(f"{m['unmatched_kills']} kill increments have no matching death")
    if m["orphan_assists"]:
        fails.append(f"{m['orphan_assists']} assist increments have no matching kill")
    for k in ("max_killer_lag_s", "max_assist_lag_s"):
        if m[k] is not None and m[k] > MAX_LAG_OK_S:
            fails.append(f"{k} = {m[k]:.1f}s > {MAX_LAG_OK_S:.0f}s")
    return fails


def analyse(gid: str, quiet: bool = False, write_report: bool = True) -> dict:
    lines: list[str] = []

    def say(s: str = "") -> None:
        if not quiet:
            print(s)
        lines.append(s)

    d = json.loads((PROBE / f"crawl_{gid}.json").read_text())
    meta = d["meta"]
    by_string = sorted(d["frames"], key=lambda f: f["rfc460Timestamp"])
    frames = sorted(d["frames"], key=lambda f: parse(f["rfc460Timestamp"]))
    ts = [parse(f["rfc460Timestamp"]) for f in frames]
    str_ts = [parse(f["rfc460Timestamp"]) for f in by_string]
    ros = roster(meta)
    m = {"gid": gid, "patch": meta.get("patchVersion"), "frames": len(frames),
         "finished": frames[-1].get("gameState") == "finished",
         "inversions": sum(b < a for a, b in zip(str_ts, str_ts[1:]))}
    say(f"# Event reconstruction for game {gid}")
    say(f"- string-sort order inversions (the old bug): {m['inversions']}")

    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    say(f"- frames: {len(frames)}, sorted by parsed time; negative gaps after sort: {sum(g < 0 for g in gaps)}; "
        f"median gap {st.median(gaps):.2f}s, max {max(gaps):.2f}s")
    stat_times = update_times(frames, ts, stat_sig)
    hp_times = update_times(frames, ts, hp_sig)
    for label, times in (("gold/CS/KDA/level", stat_times), ("current health", hp_times)):
        med, p90, mx = gap_stats(times)
        say(f"- distinct {label} updates: {len(times)}; gap between updates median {med:.2f}s, p90 {p90:.2f}s, max {mx:.2f}s")
    m["state_update_median_s"] = round(gap_stats(stat_times)[0], 2)

    ev = increments(frames, ts)
    deaths, kills, assists = ev["deaths"], ev["kills"], ev["assists"]
    say(f"- counter increments: deaths {len(deaths)}, kills {len(kills)}, assists {len(assists)}")
    assign, assist_for, orphans, used_k, n_cand, n_near = match(ev, ros)
    klags = [abs(l) for _, l in assign.values()]
    alags = [abs(l) for v in assist_for.values() for _, l in v]
    multi = {t: c for t, c in Counter(td for td, _ in deaths).items() if c > 1}
    m.update(deaths=len(deaths), kills=len(kills), assists=len(assists), matched=len(assign),
             unmatched_deaths=len(deaths) - len(assign), unmatched_kills=len(kills) - len(used_k),
             orphan_assists=len(orphans), max_killer_lag_s=max(klags) if klags else None,
             max_assist_lag_s=max(alags) if alags else None, multi_death_updates=len(multi),
             deaths_in_multi_death_updates=sum(multi.values()))
    say(f"- deaths matched to a killer: {len(assign)}/{len(deaths)}; unmatched kill increments: {m['unmatched_kills']}")
    if klags:
        say(f"- |killer lag| (kill counter vs death counter): median {st.median(klags):.2f}s, p90 {pct(klags, .9):.2f}s, max {max(klags):.2f}s")
    if alags:
        say(f"- |assist lag|: median {st.median(alags):.2f}s, p90 {pct(alags, .9):.2f}s, max {max(alags):.2f}s")
    say(f"- assist increments not attached to any kill: {len(orphans)}")
    say(f"- ambiguous deaths (>1 opposing kill within {WINDOW_S:.0f}s): {sum(v > 1 for v in n_cand.values())}; "
        f"deaths with another death within {WINDOW_S:.0f}s: {sum(v > 0 for v in n_near.values())}")
    say(f"- 1 s updates containing 2+ deaths: {len(multi)} ({m['deaths_in_multi_death_updates']} deaths); "
        f"only these can cross-match killers")

    # --- OE validation
    m.update(oe_gid=None, date=None, blue=None, red=None, kda_match=0, team_mismatches=0, team_total=0,
             timeline_match=0, timeline_total=0, length_diff_s=None, gamelength_s=None)
    found = find_oe(load_oe(ts[0]), ros, ts[0])
    gamelength, by_champ = None, {}
    if not found:
        say("- OE match: NOT FOUND (champion set + date); skipping validation")
    else:
        _, oegid, rows = found
        m["oe_gid"], m["date"] = oegid, rows[0]["date"]
        say(f"- OE match: {oegid}")
        by_champ = {norm(r["champion"]): r for r in rows if r["position"] != "team"}
        fin = players(frames[-1])
        bad = 0
        for pid, r in ros.items():
            o = by_champ[norm(r["champ"])]
            got = (fin[pid]["kills"], fin[pid]["deaths"], fin[pid]["assists"])
            exp = (num(o["kills"]), num(o["deaths"]), num(o["assists"]))
            if got != exp:
                bad += 1
                say(f"  - MISMATCH {r['name']} {r['champ']}: frames {got} vs OE {exp}")
        m["kda_match"] = 10 - bad
        say(f"- per-player final K/D/A vs OE: {10 - bad}/10 match")
        team_of = {pid: by_champ[norm(r["champ"])]["teamname"] for pid, r in ros.items()}
        for side, key in (("blue", "blueTeam"), ("red", "redTeam")):
            tname = next(team_of[p] for p in ros if ros[p]["team"] == side)
            m[side] = tname
            trow = next((r for r in rows if r["position"] == "team" and r["teamname"] == tname), None)
            if trow is None:
                continue
            ft = frames[-1][key]
            dr = ft["dragons"]
            checks = {"kills": (ft["totalKills"], num(trow.get("kills"))),
                      "towers": (ft["towers"], num(trow.get("towers"))),
                      "dragons": (len(dr) if isinstance(dr, list) else dr, num(trow.get("dragons"))),
                      "barons": (ft["barons"], num(trow.get("barons")))}
            for k, (a, b) in checks.items():
                if b is not None:
                    m["team_total"] += 1
                    if a != b:
                        m["team_mismatches"] += 1
                        m.setdefault("team_diffs", []).append(f"{side} {k}: frames {a} vs OE {b}")
            say(f"- team {side} ({tname}) frames vs OE: " + ", ".join(
                f"{k} {a}/{b}{'' if a == b else ' <-- differs'}" for k, (a, b) in checks.items()))
        gamelength = num(next(r for r in rows if r["position"] == "team")["gamelength"])
        m["gamelength_s"] = gamelength

    # --- game clock (pause-aware: time spent in a 'paused' state is not game time)
    clock, ci = make_clock(frames, ts, gamelength)
    pauses, active, t0, t_end = ci["pauses"], ci["active"], ci["t0"], ci["t_end"]
    m["pause_s"] = round(sum((b - a).total_seconds() for a, b in pauses), 1)
    span = active(t0, t_end)
    if gamelength:
        m["length_diff_s"] = round(span - gamelength, 1)
    say(f"- first non-zero-gold frame -> last frame: {span:.1f}s of play"
        + (f" after removing {m['pause_s']:.0f}s of pauses" if pauses else "")
        + (f"; OE gamelength {gamelength}s (diff {span - gamelength:+.1f}s)" if gamelength else ""))

    big = sorted(((b - a).total_seconds(), a) for a, b in zip(stat_times, stat_times[1:]))[-3:]
    say("- largest gaps between state updates: " + ", ".join(
        f"{g:.1f}s starting at game clock {clock(a) / 60:.1f} min" for g, a in big))
    if found:
        m["timeline_match"], m["timeline_total"] = timeline_check(by_champ, ros, deaths, kills, assign, assist_for, clock, say)
        say(f"- timeline check vs OE kills/deaths/assists @10/15/20/25 min: {m['timeline_match']}/{m['timeline_total']} comparisons match")

    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / f"events_{gid}.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["n", "clock_s", "minute", "victim_pid", "victim_role", "victim_champ", "victim_team",
                    "killer_pid", "killer_role", "killer_champ", "killer_lag_s", "assist_pids", "assist_lags_s",
                    "n_candidate_kills", "n_nearby_deaths"])
        for di, (td, victim) in enumerate(deaths):
            if di in assign:
                ki, kl = assign[di]
                killer = kills[ki][1]
                kcols = [killer, ros[killer]["role"], ros[killer]["champ"], f"{kl:.2f}"]
            else:
                kcols = ["", "", "", ""]
            asst = assist_for.get(di, [])
            c = clock(td)
            w.writerow([di + 1, f"{c:.1f}", f"{c / 60:.2f}", victim, ros[victim]["role"], ros[victim]["champ"],
                        ros[victim]["team"], *kcols, " ".join(str(p) for p, _ in asst),
                        " ".join(f"{l:.2f}" for _, l in asst), n_cand[di], n_near[di]])
    say(f"- wrote {out}")

    fails = verdict(m)
    notes = []
    if m["unmatched_deaths"]:
        notes.append(f"{m['unmatched_deaths']} deaths without a champion killer")
    if m["multi_death_updates"]:
        notes.append(f"{m['deaths_in_multi_death_updates']} deaths share a 1 s update with another death")
    if m["pause_s"]:
        notes.append(f"{m['pause_s']:.0f}s of pauses removed from the game clock")
    if m["oe_gid"] and m["timeline_total"] == 0:
        notes.append("OE has no @10/15/20/25 columns for this game")
    m["fails"], m["notes"], m["status"] = fails, notes, ("PASS" if not fails else "FAIL")
    say(f"- verdict: {m['status']}" + (": " + "; ".join(fails) if fails else ""))
    if notes:
        say("- notes: " + "; ".join(notes))
    (PROC / f"validation_{gid}.json").write_text(json.dumps(m, indent=2, default=str))
    if write_report:
        (PROBE / "reconstruct_report.md").write_text("\n".join(lines) + "\n")
    return m


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for gid in sys.argv[1:]:
        analyse(gid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
