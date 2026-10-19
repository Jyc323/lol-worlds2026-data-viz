#!/usr/bin/env python3
"""Download Oracle's Elixir match-data CSVs from their public Google Drive folder
using the official Google Drive API (v3).

Folder (linked from https://oracleselixir.com/tools/downloads, checked 2026-10-14):
    https://drive.google.com/drive/folders/1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH
Files are named  <year>_LoL_esports_match_data_from_OraclesElixir.csv

Setup (once, free, ~5 minutes)
  1. console.cloud.google.com -> create a project -> "APIs & Services" -> enable
     "Google Drive API".
  2. "Credentials" -> "Create credentials" -> "API key". Restrict it to the
     Google Drive API (and, if you like, to your IP).
  3. Put it in an environment variable or a git-ignored file named `.env`
     in the project root:
         GOOGLE_API_KEY=your-key-here
     Never commit it. In GitHub Actions store it as a repository secret.

Usage
    python3 scripts/fetch_oracles_elixir.py                 # current + previous year
    python3 scripts/fetch_oracles_elixir.py --years 2024 2025 2026
    python3 scripts/fetch_oracles_elixir.py --force         # ignore unchanged/once-a-day guards
    python3 scripts/fetch_oracles_elixir.py --web           # old anonymous web download (quota-limited)

Behavior
  * Lists the folder through the API (name, size, md5, modifiedTime).
  * Skips a file when its md5 matches the local copy: no download needed, which
    also keeps us inside any quota. Oracle's Elixir updates once per day, so a
    daily run is the most that is useful.
  * Streams to a temp file, verifies md5 and the CSV header, then renames.
  * manifest.json records Drive `modifiedTime` per file: use it as the site's
    "data last updated" stamp.
  * The API key goes in the `x-goog-api-key` header, not in URLs or logs.
  * Quota note: file-level download limits can still apply to very popular public
    files. If Google answers 403 with a quota reason the script says so and stops;
    it does not retry in a loop or try to evade the limit.

Attribution (keep in the README and on the site): data by Tim Sevenhuysen of
OraclesElixir.com; game statistics are property of Riot Games and must be used under
Riot's terms; Oracle's Elixir is not endorsed by Riot Games.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
FOLDER_ID = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
API = os.environ.get("DRIVE_API_BASE", "https://www.googleapis.com/drive/v3")
WEB_FOLDER_URL = os.environ.get("OE_FOLDER_URL", f"https://drive.google.com/drive/folders/{FOLDER_ID}")
WEB_DL_URL = os.environ.get("OE_DL_URL", "https://drive.usercontent.google.com/download")
NAME_RE = re.compile(r"^(\d{4})_LoL_esports_match_data_from_OraclesElixir\.csv$")
NAME_FMT = "{year}_LoL_esports_match_data_from_OraclesElixir.csv"
UA = {"User-Agent": "lol-myth-viz/0.1 (portfolio project; daily fetch of public CSVs)"}
MIN_AGE_HOURS = 20  # web mode only
REQUIRED_HEADER = {"gameid", "playername", "position", "teamname", "result"}

PINNED = {  # folder listing of 2026-10-14; web-mode fallback only
    2014: "12syQsRH2QnKrQZTQQ6G5zyVeTG2pAYvu", 2015: "1qyckLuw0-hJM8XqFhlV9l1xAbr3H78T_",
    2016: "1muyfpaIqk8_0BFkgLCWXDGNgWSXoPBwG", 2017: "11fx3nNjSYB0X8vKxLAbYOrS2Bu6avm9A",
    2018: "1GsNetJQOMx0QJ6_FN8M1kwGvU_GPPcPZ", 2019: "11eKtScnZcpfZcD3w3UrD7nnpfLHvj9_t",
    2020: "1dlSIczXShnv1vIfGNvBjgk-thMKA5j7d", 2021: "1fzwTTz77hcnYjOnO9ONeoPrkWCoOSecA",
    2022: "1EHmptHyzY8owv0BAcNKtkQpMwfkURwRy", 2023: "1XXk2LO0CsNADBB1LRGOV5rUpyZdEZ8s2",
    2024: "1IjIEhLc9n8eLKeY-yh_YigKVWbhgGBsN", 2025: "1v6LRphp2kYciU4SXp0PCjEMuev1bDejc",
    2026: "1hnpbrUpBMS1TZI7IovfpKeZfWJH1Aptm",
}

OUT_DIR = ROOT / "data" / "raw" / "oe"
MANIFEST = OUT_DIR / "manifest.json"


def load_dotenv() -> None:
    """Minimal .env reader (KEY=VALUE lines). Does not override real env vars."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class QuotaError(RuntimeError):
    pass


def explain_api_error(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
        reasons = [e.get("reason") for e in err.get("errors", [])]
        return f"HTTP {r.status_code} {err.get('message', '')[:200]} reasons={reasons}"
    except ValueError:
        return f"HTTP {r.status_code} {r.text[:200]!r}"


# --------------------------------------------------------------------- API mode
def api_list(s: requests.Session, key: str) -> list[dict]:
    files, token = [], None
    while True:
        params = {
            "q": f"'{FOLDER_ID}' in parents and trashed = false",
            "fields": "nextPageToken, files(id,name,size,md5Checksum,modifiedTime,mimeType)",
            "pageSize": 200,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            params["pageToken"] = token
        r = s.get(f"{API}/files", params=params, headers={"x-goog-api-key": key}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"files.list failed: {explain_api_error(r)}")
        j = r.json()
        files += j.get("files", [])
        token = j.get("nextPageToken")
        if not token:
            return files


def api_download(s: requests.Session, key: str, meta: dict, dest: Path) -> tuple[int, str]:
    r = s.get(f"{API}/files/{meta['id']}", params={"alt": "media", "supportsAllDrives": "true"},
              headers={"x-goog-api-key": key}, stream=True, timeout=120)
    if r.status_code != 200:
        msg = explain_api_error(r)
        if r.status_code == 403 and re.search(r"quota|rate|download", msg, re.I):
            raise QuotaError(msg)
        raise RuntimeError(msg)
    return write_stream(r, dest, expect_md5=meta.get("md5Checksum"))


def write_stream(r: requests.Response, dest: Path, expect_md5: str | None = None) -> tuple[int, str]:
    tmp = dest.with_suffix(".csv.part")
    sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    if expect_md5 and md5.hexdigest() != expect_md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"md5 mismatch (got {md5.hexdigest()}, Drive says {expect_md5})")
    with open(tmp, "r", encoding="utf-8-sig", errors="replace") as f:
        header = f.readline().strip().lower().split(",")
    missing = REQUIRED_HEADER - set(header)
    if missing:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"not an Oracle's Elixir CSV (missing columns {sorted(missing)})")
    tmp.replace(dest)
    return size, sha.hexdigest()


def local_md5(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_api(years: list[int], force: bool, key: str, manifest: dict) -> int:
    s = requests.Session()
    s.headers.update(UA)
    try:
        listing = api_list(s, key)
    except RuntimeError as e:
        print(f"! {e}")
        print("  Check: Drive API enabled for the key's project? key restricted to the right API?")
        return 1
    by_year = {}
    for f in listing:
        m = NAME_RE.match(f["name"])
        if m:
            by_year[int(m.group(1))] = f
    print(f"listing (API): {len(by_year)} yearly files; "
          f"newest modifiedTime {max((f['modifiedTime'] for f in by_year.values()), default='?')}")
    rc = 0
    for y in years:
        name = NAME_FMT.format(year=y)
        meta = by_year.get(y)
        if not meta:
            print(f"- {name}: not in the folder listing")
            rc = 1
            continue
        dest = OUT_DIR / name
        if not force and meta.get("md5Checksum") and local_md5(dest) == meta["md5Checksum"]:
            manifest.setdefault(name, {}).update(drive_modified_time=meta["modifiedTime"],
                                                 checked_at=now())
            print(f"- {name}: unchanged (md5 match), Drive modified {meta['modifiedTime']}")
            continue
        t0 = time.time()
        try:
            size, sha = api_download(s, key, meta, dest)
        except QuotaError as e:
            print(f"! {name}: quota: {e}\n  Stopping; try again later. Not retrying in a loop.")
            return 2
        except (RuntimeError, requests.RequestException) as e:
            print(f"! {name}: {e}")
            rc = 1
            continue
        manifest[name] = {"file_id": meta["id"], "bytes": size, "sha256": sha,
                          "md5": meta.get("md5Checksum"), "drive_modified_time": meta["modifiedTime"],
                          "fetched_at": now(), "checked_at": now(), "source": "drive-api"}
        save_manifest(manifest)
        print(f"- {name}: {size / 1e6:.1f} MB in {time.time() - t0:.0f}s, md5 verified, "
              f"Drive modified {meta['modifiedTime']}")
        time.sleep(1)
    save_manifest(manifest)
    return rc


# --------------------------------------------------------------------- web mode
def run_web(years: list[int], force: bool, manifest: dict) -> int:
    """Anonymous download through the public web endpoint (often quota-limited)."""
    s = requests.Session()
    s.headers.update(UA)
    ids = dict(PINNED)
    rc = 0
    for y in years:
        name = NAME_FMT.format(year=y)
        if y not in ids:
            print(f"- {name}: unknown file id")
            rc = 1
            continue
        ent = manifest.get(name)
        if not force and ent and (OUT_DIR / name).exists() and "fetched_at" in ent:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ent["fetched_at"])
            if age < dt.timedelta(hours=MIN_AGE_HOURS):
                print(f"- {name}: fetched < {MIN_AGE_HOURS} h ago, skipping")
                continue
        try:
            r = s.get(WEB_DL_URL, params={"id": ids[y], "export": "download", "confirm": "t"},
                      stream=True, timeout=60)
            if "text/html" in r.headers.get("Content-Type", ""):
                msg = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(r.text)))[:120]
                raise QuotaError(f"HTML page instead of file: {msg!r}")
            size, sha = write_stream(r, OUT_DIR / name)
        except (QuotaError, RuntimeError, requests.RequestException) as e:
            print(f"! {name}: {e}")
            rc = 1
            continue
        manifest[name] = {"file_id": ids[y], "bytes": size, "sha256": sha, "fetched_at": now(),
                          "source": "drive-web"}
        save_manifest(manifest)
        print(f"- {name}: {size / 1e6:.1f} MB")
        time.sleep(2)
    return rc


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def save_manifest(m: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2))


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    this = dt.date.today().year
    ap.add_argument("--years", type=int, nargs="+", default=[this - 1, this])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--web", action="store_true", help="anonymous web download instead of the API")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    key = os.environ.get("GOOGLE_API_KEY", "")
    if args.web:
        rc = run_web(args.years, args.force, manifest)
    elif not key:
        print("! GOOGLE_API_KEY is not set. See the setup steps at the top of this script, "
              "or run with --web (quota-limited).")
        return 1
    else:
        rc = run_api(args.years, args.force, key, manifest)
    print(f"manifest: {MANIFEST}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
