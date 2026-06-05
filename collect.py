"""
collect.py  —  Project 1: AI Kelley Blue Book
Stage 0: collect RAW documents and persist them BEFORE any cleaning.

Design principle: scraping is slow/flaky, cleaning is fast/iterative.
So this script does ONE job — pull each source once and save the raw payload
to disk — and nothing else. Cleaning + chunking happen later (ingest.py),
reading from these saved files so you never re-scrape just to tweak cleaning.

Output layout:
    raw/
      manifest.jsonl          one JSON line per source (metadata + filename)
      0001_kbb.html           raw bytes, extension by content type
      0002_edmunds.html
      0009_nhtsa_crv.json
      ...

The manifest is the source of truth. It records collected_date (needed by your
stale-recall risk mitigation), model_year, source_type, http status, and the
local filename. ingest.py later walks the manifest, not the URLs.
"""

from __future__ import annotations
import json
import time
import pathlib
import datetime as dt
from urllib.parse import urlparse

import requests

RAW_DIR = pathlib.Path("raw")
MANIFEST = RAW_DIR / "manifest.jsonl"
HEADERS = {"User-Agent": "Mozilla/5.0 (Project1-AI-KBB research; contact: you@school.edu)"}
POLITE_DELAY_SEC = 1.5  # be a good citizen between requests


# --------------------------------------------------------------------------- #
# Your sources. source_type drives chunking later: 'prose' | 'record' | 'forum'
# model_year is optional metadata; fill where a source is year-specific.
# NOTE the two special cases flagged in the writeup:
#   - Reddit: use the .json endpoint, plain HTML comes back nearly empty
#   - NHTSA:  use the JSON API, far cleaner than scraping the recall page
# --------------------------------------------------------------------------- #
SOURCES = [
    {"id": 1,  "name": "kbb_fpp",        "type": "prose",  "year": None,
     # was 404: https://www.kbb.com/car-advice/kbb-fair-purchase-price/
     # then FAQ page (thin — mostly abbreviations glossary). Swapped to the B2B
     # definitions page, which has the actual Fair Purchase Price / Fair Market
     # Range methodology in prose.
     "url": "https://b2b.kbb.com/kbb-vehicle-values/definitions-of-our-values/"},
    {"id": 2,  "name": "carmax_inventory", "type": "record",  "year": None,
     # REPLACED edmunds_tmv (was 403). Live used-car inventory.
     # WARNING: inventory is JS/API-rendered — plain requests likely gets an
     # empty shell. If it comes back empty/blocked, the fallback is CarMax's
     # static research pages (carmax.com/articles) or accepting the gap.
     "url": "https://www.carmax.com/cars"},
    {"id": 3,  "name": "r_whatcar",      "type": "forum",  "year": None,
     "url": "https://www.reddit.com/r/whatcarshouldibuy/.json"},   # .json!
    {"id": 4,  "name": "caredge_guides", "type": "prose",  "year": None,
     # was 404: https://caredge.com/guides/car-buying
     # /guides/ path is alive; this slug explicitly explains Market Day Supply.
     "url": "https://caredge.com/guides/fastest-selling-cars"},
    {"id": 5,  "name": "cr_reliability", "type": "prose",  "year": None,
     # was 404: https://www.consumerreports.org/cars/reliability/
     # this page explains the scoring methodology; NOTE: CR is partly paywalled,
     # so expect possibly only the intro to come through cleanly.
     "url": "https://www.consumerreports.org/cars/car-reliability-owner-satisfaction/who-makes-the-most-reliable-cars-a7824554938/"},
    {"id": 6,  "name": "r_mechanic",     "type": "forum",  "year": None,
     "url": "https://www.reddit.com/r/MechanicAdvice/.json"},      # .json!
    {"id": 7,  "name": "carcomplaints",  "type": "record", "year": None,
     "url": "https://www.carcomplaints.com/"},
    {"id": 8,  "name": "civicx",         "type": "forum",  "year": None,
     "url": "https://www.civicx.com/forum/"},
    {"id": 9,  "name": "nhtsa_crv_2018", "type": "record", "year": 2018,
     # JSON API is far cleaner than the /vehicle/2018/HONDA/CR-V page:
     "url": "https://api.nhtsa.gov/recalls/recallsByVehicle?make=honda&model=cr-v&modelYear=2018"},
    {"id": 10, "name": "carvana_inventory", "type": "record", "year": None,
     # REPLACED nhtsa_tsb (was 403). Live used-car inventory.
     # WARNING: same JS/API caveat as CarMax — expect a likely empty shell.
     "url": "https://www.carvana.com/cars"},
    {"id": 11, "name": "iihs_ratings",   "type": "record", "year": None,
     "url": "https://www.iihs.org/ratings"},
    {"id": 12, "name": "autotempest",   "type": "record", "year": None,
     # REPLACED r_pf_vehicles (was 403). Aggregated listings across sites.
     # WARNING: AutoTempest is a meta-search aggregator — even MORE JS-dependent
     # than CarMax/Carvana and likely to block. Lowest odds of the three.
     "url": "https://www.autotempest.com/results?make=honda&model=cr-v"},
    {"id": 13, "name": "lemonsquad",     "type": "prose",  "year": None,
     "url": "https://lemonsquad.com/blog/"},
]


def _ext_for(resp: requests.Response, url: str) -> str:
    """Choose a file extension from content type / URL so raw bytes round-trip."""
    ctype = resp.headers.get("content-type", "").lower()
    if "json" in ctype or url.endswith(".json"):
        return "json"
    if "pdf" in ctype or url.endswith(".pdf"):
        return "pdf"
    return "html"


def _already_have(url: str) -> bool:
    """Idempotency: skip a URL already recorded in the manifest."""
    if not MANIFEST.exists():
        return False
    with MANIFEST.open() as f:
        return any(json.loads(line).get("url") == url for line in f if line.strip())


def collect_one(src: dict) -> dict:
    """Fetch a single source, save raw bytes, return a manifest record."""
    resp = requests.get(src["url"], headers=HEADERS, timeout=30)
    ext = _ext_for(resp, src["url"])
    fname = f"{src['id']:04d}_{src['name']}.{ext}"
    (RAW_DIR / fname).write_bytes(resp.content)   # raw bytes, no cleaning

    return {
        "id": src["id"],
        "name": src["name"],
        "url": src["url"],
        "source_type": src["type"],
        "model_year": src["year"],
        "http_status": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
        "bytes": len(resp.content),
        "filename": fname,
        "collected_date": dt.date.today().isoformat(),   # for stale-data caveats
    }


def main():
    RAW_DIR.mkdir(exist_ok=True)
    with MANIFEST.open("a") as mf:                 # append: safe across re-runs
        for src in SOURCES:
            if _already_have(src["url"]):
                print(f"[skip] {src['name']} (already collected)")
                continue
            try:
                rec = collect_one(src)
                mf.write(json.dumps(rec) + "\n")
                mf.flush()                          # persist immediately
                print(f"[ok]   {rec['filename']}  "
                      f"{rec['http_status']}  {rec['bytes']:,} bytes")
            except Exception as e:
                # Log the failure as a manifest line too, so you can see what
                # broke without it killing the rest of the run.
                err = {"id": src["id"], "name": src["name"], "url": src["url"],
                       "error": str(e),
                       "collected_date": dt.date.today().isoformat()}
                mf.write(json.dumps(err) + "\n"); mf.flush()
                print(f"[ERR]  {src['name']}: {e}")
            time.sleep(POLITE_DELAY_SEC)

    print(f"\nDone. Raw files in {RAW_DIR}/ , manifest at {MANIFEST}")


if __name__ == "__main__":
    main()