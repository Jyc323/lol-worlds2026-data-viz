"""Shared helpers for the Worlds 2026 fearless-depth charts.

Data: Oracle's Elixir match data (one CSV per year). Not stored in the repo; download it with
scripts/fetch_oracles_elixir.py or by hand and put it in data/raw/oe/ (or set OE_DIR).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import gammaln

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RAW = Path(os.environ.get("OE_DIR", REPO / "data" / "raw" / "oe"))  # folder with the Oracle's Elixir CSV(s)
OUT = HERE / "output"
OUT.mkdir(exist_ok=True)
SEED = 3
POS = ["top", "jng", "mid", "bot", "sup"]
ROLE_LABEL = {"top": "Top", "jng": "Jungle", "mid": "Mid", "bot": "Bot (ADC)", "sup": "Support"}

WORLDS_TEAMS = ["Gen.G", "Hanwha Life Esports", "T1", "Dplus Kia", "Anyone's Legend", "Bilibili Gaming",
                "Top Esports", "Invictus Gaming", "G2 Esports", "Movistar KOI",
                "Team Liquid", "LYON", "Team Secret Whales", "CTBC Flying Oyster", "LØS"]  # 15 direct-to-Swiss teams (Play-In: KC, C9, MVK, FURIA)
SHORT = {"Hanwha Life Esports": "Hanwha Life", "Anyone's Legend": "Anyone's Legend", "Team Secret Whales": "Secret Whales",
         "CTBC Flying Oyster": "CTBC Flying Oyster", "Movistar KOI": "Movistar KOI", "G2 Esports": "G2",
         "Karmine Corp": "Karmine Corp", "Team Liquid": "Team Liquid", "Dplus Kia": "Dplus KIA",
         "Bilibili Gaming": "Bilibili Gaming", "Invictus Gaming": "Invictus Gaming", "MVK Esports": "MVK"}
INTERNATIONAL = {"WLDs", "MSI", "FST", "EWC", "Worlds", "WCS"}


def load(years):
    return pd.concat([pd.read_csv(RAW / f"{y}_LoL_esports_match_data_from_OraclesElixir.csv",
                                  low_memory=False, dtype={"patch": "string"}) for y in years], ignore_index=True)


def rarefied_distinct(counts: np.ndarray, k: int) -> float:
    """Expected number of distinct champions in k games drawn without replacement from the season."""
    n = int(counts.sum())
    if n < k:
        return float("nan")
    lc = lambda a, b: gammaln(a + 1) - gammaln(b + 1) - gammaln(a - b + 1)
    miss = np.where(n - counts >= k, np.exp(lc(n - counts, k) - lc(n, k)), 0.0)
    return float((1 - miss).sum())
