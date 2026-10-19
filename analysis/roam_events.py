#!/usr/bin/env python3
"""Roam ledger prototype: find mid-laner roams in livestats frames and put a price on them.

    python3 analysis/roam_events.py [GAME_ID ...]     # default: every game of data/probe/team_games.json that is crawled

Works on complete games and on partial crawls (first ~19 minutes, scripts/crawl_teams.py). The game clock is
anchored at the first frame with gold (pauses removed) for every game; against the Oracle's Elixir game length this
differs by 0.3 s median. Only the mid laners of the teams in team_games.json are kept (the opposing mid still supplies
the cost). A game is used only if every kill increment is matched to a death and its 10 and 15 minute K/D/A counts equal
Oracle's Elixir; the others are listed in data/processed/roam_games.csv with the reason.

A candidate roam is a kill in which the mid laner took part (kill or assist) and the victim is NOT
the opposing mid. Kills of one mid laner within GROUP_GAP_S seconds form one candidate. A candidate
counts as a roam when the mid laner had not last-hit for STALL_S seconds before the first kill,
did not die and did not visit base (health jump) in between. Positions are not in the data: this is
an inference from CS stalls plus kill participation, not a measurement of where the player stood.

Price of a roam (all in gold):
  cost    = minions the opposing mid farmed while the mid laner was away, x GOLD_PER_CS
  return  = change in team gold lead over RWIN_S seconds from the moment the mid laner stopped
            farming, minus the average change over the same team's windows in the same game, within
            +-BASE_NEIGHBOURHOOD_S seconds, that contain no roam (the baseline)
            split into mid lane (mid gold minus opposing mid gold) and the rest of the team.
Associations only: roams happen when the team already has an opening.

Writes data/processed/roam_events.csv, data/processed/roam_params.json, data/probe/roam_report.md.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import reconstruct_events as rec  # noqa: E402

MIN_END_S = 15 * 60  # a crawl shorter than this (game clock) is not used
PLAN = rec.PROBE / "team_games.json"
GAME_COLUMNS = ["game_id", "date", "teams", "mode", "end_s", "finished", "unmatched_kills", "oe_found",
                "tl_match", "tl_total", "used", "reason"]

PARAMS = {
    "STALL_S": 30,               # no last hit for this long before the first kill = away from the wave
    "GROUP_GAP_S": 30,           # kills this close together belong to one roam
    "RWIN_S": 120,               # look at the team gold lead this long after the mid laner left
    "BASE_NEIGHBOURHOOD_S": 180, # baseline windows start within this many seconds of the roam
    "BASE_STEP_S": 10,
    "MIN_BASE_WINDOWS": 3,
    "HP_JUMP": 0.35,             # health share regained within HP_JUMP_S seconds = visited base
    "HP_JUMP_S": 3,
    "MIN_CLOCK_S": 120,          # ignore anything before 2:00
    "GOLD_PER_CS": 20,           # rough average gold per minion (cannon minions are worth more)
}
COLUMNS = ["game_id", "date", "team", "mid", "mid_champ", "opp_champ", "minute", "leave_s", "first_kill_s",
           "last_kill_s", "return_s", "stall_s", "away_s", "n_kills", "mid_kills", "mid_assists", "victim_roles",
           "died_during", "base_visit", "is_roam", "cs_lost", "cost_gold", "dlevel", "d_net", "d_lane", "d_rest",
           "base_net", "base_lane", "base_rest", "n_base", "ex_net", "ex_lane", "ex_rest", "kills_us", "kills_them", "win_full"]


_OE_DAYS = {}


def load_oe_cached(first_ts):
    """rec.load_oe without re-reading the CSV for every game."""
    if not _OE_DAYS:
        with rec.OE.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                _OE_DAYS.setdefault(row["date"][:10], {}).setdefault(row["gameid"], []).append(row)
    out = {}
    for k in (-1, 0, 1):
        out.update(_OE_DAYS.get((first_ts + dt.timedelta(days=k)).strftime("%Y-%m-%d"), {}))
    return out


def oe_check(frames, ts, ros, ev, assign, assist_for, clock):
    """(oe_found, matches, total) for the K/D/A counts at 10 and 15 game minutes."""
    found = rec.find_oe(load_oe_cached(ts[0]), ros, ts[0])
    if not found:
        return False, 0, 0
    by_champ = {}
    for r in found[2]:
        if r["position"] != "team":
            by_champ[rec.norm(r["champion"])] = {k: v for k, v in r.items() if not k.endswith(("at20", "at25"))}
    ok, total = rec.timeline_check(by_champ, ros, ev["deaths"], ev["kills"], assign, assist_for, clock, lambda *_: None)
    return True, ok, total


def per_second(frames, ts, clock, T):
    clk = [clock(t) for t in ts]
    pl = [rec.players(f) for f in frames]
    series = {k: {pid: [0.0] * (T + 1) for pid in range(1, 11)} for k in ("cs", "gold", "lvl", "hp")}
    j = 0
    for s in range(T + 1):
        while j + 1 < len(frames) and clk[j + 1] <= s:
            j += 1
        for pid, p in pl[j].items():
            series["cs"][pid][s] = p["creepScore"]
            series["gold"][pid][s] = p["totalGold"]
            series["lvl"][pid][s] = p["level"]
            series["hp"][pid][s] = p["currentHealth"] / p["maxHealth"] if p["maxHealth"] else 0.0
    return series


def last_tick(cs, x):
    """Second of the most recent last-hit at or before x (0 if none)."""
    s = min(int(x), len(cs) - 1)
    while s > 0 and cs[s] <= cs[s - 1]:
        s -= 1
    return s


def first_tick(cs, x):
    """Second of the first last-hit at or after x (end of game if none)."""
    s = max(int(x), 1)
    while s < len(cs) and cs[s] <= cs[s - 1]:
        s += 1
    return min(s, len(cs) - 1)


def fix_names(ros, teams):
    """Some summoner names lack the space after the team code ("TESCreme"): insert it so the code splits off."""
    for r in ros.values():
        n = r["name"]
        if n.split()[0] in (teams or []):
            continue
        for c in sorted(teams or [], key=len, reverse=True):
            if n.startswith(c) and len(n) > len(c) and (n[len(c)].isupper() or n[len(c)].isdigit()):
                r["name"] = c + " " + n[len(c):]
                break


def game_events(gid, teams=None):
    """-> (rows, stall_samples, quality). Rows only for mid laners whose team code is in `teams` (all if None)."""
    d = json.loads((rec.PROBE / f"crawl_{gid}.json").read_text())
    frames = sorted(d["frames"], key=lambda f: rec.parse(f["rfc460Timestamp"]))
    ts = [rec.parse(f["rfc460Timestamp"]) for f in frames]
    ros = rec.roster(d["meta"])
    fix_names(ros, teams)
    clock, _ = rec.make_clock(frames, ts, None)
    T = int(clock(ts[-1]))
    q = {"game_id": gid, "date": ts[0].strftime("%Y-%m-%d"), "end_s": T,
         "finished": int(frames[-1].get("gameState") == "finished"), "used": 0, "reason": ""}
    ev = rec.increments(frames, ts)
    assign, assist_for, orphans, used_k, *_ = rec.match(ev, ros)
    q["unmatched_kills"] = len(ev["kills"]) - len(used_k)
    q["oe_found"], q["tl_match"], q["tl_total"] = oe_check(frames, ts, ros, ev, assign, assist_for, clock)
    if T < MIN_END_S:
        q["reason"] = f"crawl ends at {T} s"
    elif q["unmatched_kills"] or orphans:
        q["reason"] = f"{q['unmatched_kills']} unmatched kills, {len(orphans)} orphan assists"
    elif not q["oe_found"]:
        q["reason"] = "no Oracle's Elixir game found"
    elif q["tl_match"] < q["tl_total"]:
        q["reason"] = f"10/15 min counts differ from OE ({q['tl_total'] - q['tl_match']} of {q['tl_total']})"
    if q["reason"]:
        return [], [], q
    q["used"] = 1
    S = per_second(frames, ts, clock, T)
    kills = ev["kills"]
    deaths = [{"t": clock(td), "victim": victim, "killer": kills[assign[di][0]][1],
               "assisters": [p for p, _ in assist_for.get(di, [])]}
              for di, (td, victim) in enumerate(ev["deaths"]) if di in assign]

    mids = {r["team"]: pid for pid, r in ros.items() if r["role"] == "mid"}
    PR = PARAMS
    rows, stall_samples = [], []
    for team in ("blue", "red"):
        other = "red" if team == "blue" else "blue"
        M, O = mids[team], mids[other]
        if teams and ros[M]["name"].split()[0] not in teams:
            continue
        us = [p for p, r in ros.items() if r["team"] == team]
        them = [p for p, r in ros.items() if r["team"] == other]
        D = [sum(S["gold"][p][s] for p in us) - sum(S["gold"][p][s] for p in them) for s in range(T + 1)]
        lane = [S["gold"][M][s] - S["gold"][O][s] for s in range(T + 1)]
        csM, csO = S["cs"][M], S["cs"][O]

        for s in range(180, min(T - 60, 14 * 60), 10):  # how long is a mid laner normally idle in lane? (roams included)
            stall_samples.append(s - last_tick(csM, s))

        cands = sorted((r for r in deaths if ros[r["victim"]]["team"] != team and ros[r["victim"]]["role"] != "mid"
                        and (r["killer"] == M or M in r["assisters"])), key=lambda r: r["t"])
        groups = []
        for r in cands:
            if groups and r["t"] - groups[-1][-1]["t"] <= PR["GROUP_GAP_S"]:
                groups[-1].append(r)
            else:
                groups.append([r])

        info = []
        for g in groups:
            tf, tl = int(round(g[0]["t"])), int(round(g[-1]["t"]))
            if tf < PR["MIN_CLOCK_S"] or tf >= T - 1:
                continue
            leave = last_tick(csM, tf - 1)
            if leave <= 0:
                continue
            ret = max(first_tick(csM, tl), leave + 1)
            died = any(leave < r["t"] < tf for r in deaths if r["victim"] == M)
            hp = S["hp"][M]
            base_visit = any(hp[s] - hp[s - PR["HP_JUMP_S"]] >= PR["HP_JUMP"]
                             for s in range(leave + PR["HP_JUMP_S"], tf + 1))
            is_roam = (tf - leave) >= PR["STALL_S"] and not died and not base_visit
            info.append({"g": g, "tf": tf, "tl": tl, "leave": leave, "ret": ret, "died": died,
                         "base_visit": base_visit, "is_roam": is_roam})
        roam_iv = [(i["leave"], i["ret"] + 30) for i in info if i["is_roam"]]

        for i in info:
            g, leave, ret, tf, tl = i["g"], i["leave"], i["ret"], i["tf"], i["tl"]
            s1, s2 = leave, min(T, leave + PR["RWIN_S"])
            d_net, d_lane = D[s2] - D[s1], lane[s2] - lane[s1]
            bases = []
            for s0 in range(max(PR["MIN_CLOCK_S"], leave - PR["BASE_NEIGHBOURHOOD_S"]),
                            min(T - PR["RWIN_S"], leave + PR["BASE_NEIGHBOURHOOD_S"]) + 1, PR["BASE_STEP_S"]):
                e0 = s0 + PR["RWIN_S"]
                if any(s0 < b and e0 > a for a, b in roam_iv):
                    continue
                bases.append((D[e0] - D[s0], lane[e0] - lane[s0]))
            if len(bases) >= PR["MIN_BASE_WINDOWS"]:
                b_net = st.mean(b[0] for b in bases)
                b_lane = st.mean(b[1] for b in bases)
            else:
                b_net = b_lane = None
            cs_lost = csO[max(leave, ret - 1)] - csO[leave]
            lv = S["lvl"]
            rows.append({
                "game_id": gid, "date": q["date"], "team": team, "mid": ros[M]["name"], "mid_champ": ros[M]["champ"],
                "opp_champ": ros[O]["champ"], "minute": round(tf / 60, 2), "leave_s": leave, "first_kill_s": tf,
                "last_kill_s": tl, "return_s": ret, "stall_s": tf - leave, "away_s": ret - leave, "n_kills": len(g),
                "mid_kills": sum(r["killer"] == M for r in g), "mid_assists": sum(M in r["assisters"] for r in g),
                "victim_roles": "/".join(ros[r["victim"]]["role"] for r in g), "died_during": int(i["died"]),
                "base_visit": int(i["base_visit"]), "is_roam": int(i["is_roam"]), "cs_lost": cs_lost,
                "cost_gold": cs_lost * PR["GOLD_PER_CS"],
                "dlevel": (lv[M][min(ret, T)] - lv[O][min(ret, T)]) - (lv[M][leave] - lv[O][leave]),
                "d_net": round(d_net), "d_lane": round(d_lane), "d_rest": round(d_net - d_lane),
                "base_net": None if b_net is None else round(b_net), "base_lane": None if b_lane is None else round(b_lane),
                "base_rest": None if b_net is None else round(b_net - b_lane), "n_base": len(bases),
                "ex_net": None if b_net is None else round(d_net - b_net),
                "ex_lane": None if b_net is None else round(d_lane - b_lane),
                "ex_rest": None if b_net is None else round((d_net - d_lane) - (b_net - b_lane)),
                "kills_us": sum(1 for r in deaths if s1 <= r["t"] <= s2 and ros[r["victim"]]["team"] != team),
                "kills_them": sum(1 for r in deaths if s1 <= r["t"] <= s2 and ros[r["victim"]]["team"] == team),
                "win_full": int(leave + PR["RWIN_S"] <= T),
            })
    return rows, stall_samples, q


def pctl(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


def main() -> int:
    gids = sys.argv[1:]
    teams = None
    modes = {}
    if PLAN.exists():
        plan = json.loads(PLAN.read_text())
        teams = set(plan["teams"]) | {c for v in plan.get("codes", {}).values() for c in v}
        modes = {g["game_id"]: (g["mode"], g["teams"]) for g in plan["games"]}
    if not gids:
        gids = [g for g in modes if (rec.PROBE / f"crawl_{g}.json").exists()]
    rows, stalls, lines, quality = [], [], [], []
    say = lambda s="": (print(s), lines.append(s))
    for i, g in enumerate(gids, 1):
        r, s, q = game_events(g, teams)
        q["mode"], q["teams"] = modes.get(g, ("", ""))
        rows += r
        stalls += s
        quality.append(q)
        if i % 50 == 0:
            print(f"  {i}/{len(gids)} games", flush=True)
    rec.PROC.mkdir(parents=True, exist_ok=True)
    with (rec.PROC / "roam_events.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with (rec.PROC / "roam_games.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=GAME_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(quality)
    used = [q["game_id"] for q in quality if q["used"]]
    (rec.PROC / "roam_params.json").write_text(json.dumps({"params": PARAMS, "teams": sorted(teams or []), "games": used}, indent=2))

    skipped = Counter(q["reason"].split(" (")[0].split(",")[0] for q in quality if not q["used"])
    say(f"# Roam events: {len(used)} of {len(gids)} games used ({dict(skipped) or 'none skipped'}); "
        f"{len(rows)} candidate groups (the mid laner of a tracked team took part in a non-mid kill)")
    say("- how long is a mid laner idle at a random moment in lane (3:00 to 14:00, every 10 s; roams included)? "
        f"median {pctl(stalls, .5)}s, p75 {pctl(stalls, .75)}s, p90 {pctl(stalls, .9)}s, p95 {pctl(stalls, .95)}s, "
        f"share >= 30 s: {100 * sum(s >= 30 for s in stalls) / len(stalls):.1f}%")
    st_all = [r["stall_s"] for r in rows]
    say(f"- stall before the first kill of a candidate: median {st.median(st_all):.0f}s, p25 {pctl(st_all, .25)}s, p75 {pctl(st_all, .75)}s")
    for thr in (10, 15, 20, 30, 45, 60):
        n = sum(r["stall_s"] >= thr and not r["died_during"] and not r["base_visit"] for r in rows)
        say(f"  - stall >= {thr:>2}s (and no death / base visit): {n} candidates")
    say(f"- flags among all candidates: died between leaving and the kill {sum(r['died_during'] for r in rows)}, "
        f"base visit {sum(r['base_visit'] for r in rows)}")
    roams = [r for r in rows if r["is_roam"]]
    say(f"- roams under the default rule (stall >= {PARAMS['STALL_S']}s): {len(roams)} "
        f"({len({r['game_id'] for r in roams})} games, {len({(r['game_id'], r['team']) for r in roams})} teams)")
    pr = Counter(r["victim_roles"].split("/")[0] for r in roams)
    say(f"- first victim role in roams: {dict(pr)}")
    priced = [r for r in roams if r["ex_net"] is not None]
    say(f"- priced against a baseline: {len(priced)} of {len(roams)}")
    if priced:
        for label, key in (("cost (gold the opposing mid farmed)", "cost_gold"), ("team lead change in 120 s", "d_net"),
                           ("... minus baseline (excess)", "ex_net"), ("excess, mid lane part", "ex_lane"),
                           ("excess, rest of team part", "ex_rest")):
            vals = [r[key] for r in priced]
            say(f"  - {label}: median {st.median(vals):+.0f}, mean {st.mean(vals):+.0f}, "
                f"share > 0 {100 * sum(v > 0 for v in vals) / len(vals):.0f}%")
        for lo, hi in ((2, 6), (6, 10), (10, 15), (15, 40)):
            b = [r for r in priced if lo <= r["minute"] < hi]
            if b:
                say(f"  - minutes {lo}-{hi}: n={len(b)}, median excess net {st.median(r['ex_net'] for r in b):+.0f}, "
                    f"median cost {st.median(r['cost_gold'] for r in b):.0f}, median kills {st.median(r['n_kills'] for r in b):.0f}")
    say("\n- a few events to eyeball (default-rule roams, earliest first):")
    for r in sorted(roams, key=lambda r: (r["game_id"], r["minute"]))[:12]:
        say(f"  {r['game_id'][-6:]} {r['date']} {r['mid_champ']:<10} min {r['minute']:>5.1f} | stall {r['stall_s']:>3}s away {r['away_s']:>3}s | "
            f"kills {r['n_kills']} ({r['victim_roles']}) | cost {r['cost_gold']:>4.0f} | excess net {r['ex_net']} (lane {r['ex_lane']}, rest {r['ex_rest']})")
    (rec.PROBE / "roam_report.md").write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
