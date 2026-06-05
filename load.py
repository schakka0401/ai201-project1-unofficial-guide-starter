"""
load.py  —  Project 1: AI Kelley Blue Book
The bridge between Stage 0 (collect.py) and Stage 2 chunking (ingest.py).

Flow:
    collect.py   ->  raw/ + manifest.jsonl   (raw bytes, already done)
    load.py      ->  reads manifest, loads each raw file from DISK (no network),
                     cleans by content type (html/json/pdf), then chunks it
                     with ingest.chunk_text, attaching manifest metadata
                     (source, model_year, collected_date) to every chunk.
    -> output: a single list of enriched chunk dicts ready for embedding (M4).

Why a separate module: collect (slow, network) and clean+chunk (fast, local)
are decoupled so you can re-clean endlessly without re-scraping. load.py only
ever touches the local raw/ directory.
"""

from __future__ import annotations
import json
import html as _html
import pathlib
import re

from bs4 import BeautifulSoup

# Reuse the chunker you already built and verified.
from ingest import chunk_text, count_tokens

RAW_DIR = pathlib.Path("raw")
MANIFEST = RAW_DIR / "manifest.jsonl"


# --------------------------------------------------------------------------- #
# Cleaning — one cleaner per content type. Each returns plain text.
# --------------------------------------------------------------------------- #
# Lines that are pure UI chrome and tend to survive content extraction.
# Matched against whole stripped lines (case-insensitive), so we only drop a
# line that IS one of these, not any line that contains the word.
_CHROME_LINES = {
    "read more", "read less", "show more", "show less", "see more",
    "share", "share this", "tweet", "save", "print", "copy link",
    "advertisement", "sponsored", "back to top", "skip to content",
    "sign in", "log in", "subscribe", "newsletter", "accept all cookies",
    "accept cookies", "manage cookies", "reply", "quote", "like", "report",
}
# "12 comments", "3 replies", "1.2k views", "Posted 3 days ago" — UI counters.
_CHROME_PATTERNS = [
    re.compile(r"^\d[\d,.]*\s*(comments?|replies?|views?|likes?|shares?)$", re.I),
    re.compile(r"^posted\s+.+ago$", re.I),
    re.compile(r"^\d+\s*(min|minute)s?\s+read$", re.I),
]


def _is_menu_item_line(stripped: str) -> bool:
    """Heuristic: is this line a navigation/dropdown list item rather than real
    content? Junk list items (state names, link titles, category lists) are
    short, lack sentence punctuation, and aren't full sentences. Real bullets
    (e.g. CarEdge's 'For fast-selling cars: Expect to pay at or near MSRP...')
    are long and sentence-like, so we keep those.

    Conservative: only flags a line as menu-junk if it's SHORT and has no
    sentence-ending punctuation and few words. This is applied only to runs
    (see _normalize_text) so a lone short line in real prose isn't removed."""
    s = stripped.lstrip("-•·* ").strip()
    if not s:
        return False
    word_count = len(s.split())
    # Long lines are almost always real content (sentences, full bullets).
    if word_count > 8:
        return False
    # A line ending in a period/!/colon is a real sentence/clause — keep it.
    # (Questions are NOT auto-kept: short "?" lines are often nav links like
    # "Who Owns Which Car Brands?", so those fall through to the length test.)
    if s.endswith((".", "!", ":")):
        return False
    # Short line (<=8 words), no terminal sentence punctuation → menu/list item
    # ("Alaska AK", "Owner Satisfaction Ratings", "Who Owns Which Car Brands?").
    return True


def _normalize_text(text: str) -> str:
    """Final cleanup applied to EVERY cleaner's output, regardless of source
    type. Decodes HTML entities (&amp; &nbsp; &#39; etc.), normalizes
    whitespace, and drops standalone UI-chrome lines (share/read-more/comment
    counts) that survive content extraction. This is the pass that catches the
    leftover-entity and stray-nav problems the cleaning step asks you to check
    for by eye."""
    # 1) Decode HTML entities, possibly double-encoded (&amp;nbsp; -> &nbsp; -> ' ')
    for _ in range(2):
        new = _html.unescape(text)
        if new == text:
            break
        text = new
    # 2) Replace non-breaking spaces and similar with normal spaces
    text = text.replace("\xa0", " ").replace("\u200b", "")
    # 3) Line-by-line: drop pure-chrome lines, keep substantive ones
    out_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        low = stripped.lower()
        if low in _CHROME_LINES:
            continue
        if any(p.match(stripped) for p in _CHROME_PATTERNS):
            continue
        out_lines.append(stripped)

    # 3b) Drop RUNS of menu/list-item lines (>=3 consecutive). A run that long
    # is a dropdown/link list (state names, "More on Cars" links); isolated
    # short lines inside prose are left alone.
    filtered = []
    i = 0
    n = len(out_lines)
    while i < n:
        if out_lines[i] and _is_menu_item_line(out_lines[i]):
            j = i
            while j < n and out_lines[j] and _is_menu_item_line(out_lines[j]):
                j += 1
            run_len = j - i
            if run_len >= 3:
                i = j            # skip the whole junk run
                continue
        filtered.append(out_lines[i])
        i += 1
    text = "\n".join(filtered)
    # 4) Collapse runs of blank lines and trailing spaces
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _clean_html_bs4(raw: bytes) -> str:
    """Fallback cleaner: strip known-boilerplate tags via BeautifulSoup.
    Crude — leaves menu/cookie/related-article text that isn't in nav/footer
    tags. Used only when trafilatura is unavailable or returns nothing."""
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript",
                     "form", "aside", "button"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _clean_html(raw: bytes) -> str:
    """Extract the MAIN CONTENT of a page, dropping navigation/menu/footer/
    cookie/boilerplate chrome.

    Modern sites (KBB, CarEdge, CR) bury the real article in menus that aren't
    in <nav> tags, so the old strip-known-tags approach left chunks full of
    'New Car / Used Car / Instant Cash Offer' menu text. trafilatura is built
    for exactly this — it finds the article body and discards the chrome.
    Falls back to the BeautifulSoup cleaner if trafilatura isn't installed or
    can't find content."""
    try:
        import trafilatura
    except ImportError:
        return _clean_html_bs4(raw)

    html = raw.decode("utf-8", errors="replace")
    extracted = trafilatura.extract(
        html,
        include_comments=False,   # drop comment sections
        include_tables=True,      # keep tables (IIHS-style grids, spec tables)
        favor_precision=True,     # prefer dropping junk over keeping everything
    )
    if extracted and extracted.strip():
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", extracted)
        return text.strip()
    # trafilatura found nothing usable — fall back.
    return _clean_html_bs4(raw)



def _clean_json(raw: bytes) -> str:
    """Flatten JSON into readable text.

    Handles the two JSON shapes in your corpus:
      - NHTSA recalls API: {'results': [ {recall}, {recall}, ... ]}
        -> each recall becomes one blank-line-separated block, which is exactly
           what the 'record' chunker wants (one entry per chunk).
      - Reddit .json: nested listing of posts/comments
        -> pull the text bodies (selftext / body / title) into blocks.
    Unknown shapes fall back to pretty-printed JSON so nothing is lost.
    """
    try:
        data = json.loads(raw)
    except Exception:
        return raw.decode("utf-8", errors="replace")

    # NHTSA recalls
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        blocks = []
        for r in data["results"]:
            if not isinstance(r, dict):
                continue
            parts = [f"{k}: {v}" for k, v in r.items()
                     if v not in (None, "", [], {})]
            if parts:
                blocks.append("\n".join(parts))
        if blocks:
            return "\n\n".join(blocks)   # blank line = record boundary

    # Reddit listing: recursively grab title/selftext/body fields
    texts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("title", "selftext", "body"):
                v = node.get(key)
                if isinstance(v, str) and v.strip() and v.strip() != "[deleted]":
                    texts.append(v.strip())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    if texts:
        # de-dup while preserving order (Reddit nests title in many places)
        seen, uniq = set(), []
        for t in texts:
            if t not in seen:
                seen.add(t); uniq.append(t)
        return "\n\n".join(uniq)        # blank line = post/comment boundary

    return json.dumps(data, indent=2)   # unknown shape, keep everything


def _clean_pdf(raw: bytes, path: pathlib.Path) -> str:
    """Extract text from a PDF. Requires pdfplumber (per your architecture)."""
    try:
        import pdfplumber
    except ImportError:
        return f"[pdf not extracted: pdfplumber not installed] {path.name}"
    import io
    out = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n\n".join(out).strip()


_CLEANERS = {"html": _clean_html, "json": _clean_json}


def load_document(record: dict) -> str:
    """Load ONE raw file from disk (per a manifest record) and return clean text.

    No network access — reads only from raw/. The manifest record tells us the
    filename and how to clean it.
    """
    if record.get("error"):
        return ""  # this source failed at collection time; skip it
    path = RAW_DIR / record["filename"]
    raw = path.read_bytes()
    ext = path.suffix.lstrip(".").lower()
    if ext == "pdf":
        cleaned = _clean_pdf(raw, path)
    else:
        cleaner = _CLEANERS.get(ext, _clean_html)  # default to html cleaner
        cleaned = cleaner(raw)
    # Single normalization pass for ALL source types: decode entities, drop
    # UI-chrome lines, collapse whitespace. This is what guarantees no &amp;/
    # &nbsp; or stray "Read more" survives, whichever cleaner ran.
    return _normalize_text(cleaned)


# --------------------------------------------------------------------------- #
# Junk detection — catch block pages, error stubs, and repeated boilerplate
# --------------------------------------------------------------------------- #
# Phrases that strongly indicate a bot-block / login wall / error page rather
# than real content. Matched case-insensitively against the cleaned text.
_BLOCK_PHRASES = (
    "are you a human", "verify you are human", "enable javascript",
    "access denied", "request blocked", "unusual traffic",
    "log in to reddit", "you've been blocked", "captcha",
    "blocked by network security", "rate limited", "too many requests",
    "please enable cookies", "checking your browser",
)


def _looks_like_block_page(text: str) -> str | None:
    """Return a reason string if the WHOLE document looks like a block/error
    page, else None. Conservative: only fires on short-ish docs dominated by
    block language, so we don't nuke a real article that happens to mention
    'captcha' once."""
    low = text.lower()
    hits = [p for p in _BLOCK_PHRASES if p in low]
    # A real long article may mention one of these in passing; a block page is
    # short and is basically nothing but these phrases. Require either multiple
    # distinct hits, or a single hit in a suspiciously short document.
    if len(hits) >= 2:
        return f"block-page language ({', '.join(hits[:3])})"
    if hits and len(text) < 1500:
        return f"short page dominated by block language ('{hits[0]}')"
    return None


def _dedupe_chunks(chunks: list[dict]) -> tuple[list[dict], int]:
    """Drop near-duplicate chunks WITHIN one source by exact normalized text.
    The Reddit block pages chunked into hundreds of identical fragments; this
    collapses them. Returns (kept_chunks, num_dropped)."""
    seen: set[str] = set()
    kept = []
    for c in chunks:
        # normalize whitespace so trivially-different copies still collide
        key = " ".join(c["text"].split())
        if key in seen:
            continue
        seen.add(key)
        kept.append(c)
    return kept, len(chunks) - len(kept)


def _repetition_ratio(chunks: list[dict]) -> float:
    """Fraction of chunks that are exact-text duplicates of another chunk in
    the same source. A high ratio (e.g. >0.5) is a strong signal the whole
    source is boilerplate/block junk, not real varied content."""
    if not chunks:
        return 0.0
    keys = [" ".join(c["text"].split()) for c in chunks]
    unique = len(set(keys))
    return 1.0 - (unique / len(keys))



def read_manifest(dedupe: bool = True) -> list[dict]:
    """Read manifest.jsonl. If dedupe=True (default), keep only the LAST entry
    per source name — so when collect.py was re-run with corrected URLs and
    appended new lines, the corrected entry wins and the stale 404 line is
    dropped. This fixes the duplicate-chunk problem (kbb/caredge/cr appeared
    twice)."""
    if not MANIFEST.exists():
        raise FileNotFoundError(
            f"{MANIFEST} not found — run collect.py first.")
    records = []
    with MANIFEST.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not dedupe:
        return records

    # Keep last occurrence per name, preserving original order of first sight.
    by_name: dict[str, dict] = {}
    for rec in records:
        key = rec.get("name", rec.get("url"))
        by_name[key] = rec          # later lines overwrite earlier ones
    deduped = list(by_name.values())
    dropped = len(records) - len(deduped)
    if dropped:
        print(f"[manifest] de-duped {dropped} stale entr"
              f"{'y' if dropped == 1 else 'ies'} "
              f"({len(records)} lines -> {len(deduped)} sources)")
    return deduped


def load_all_chunks() -> list[dict]:
    """Walk the manifest, load+clean+chunk every source, attach metadata.

    Returns a flat list of chunk dicts. Each chunk carries, in addition to the
    keys ingest.chunk_text produces ('text', 'source_type', 'char_count',
    'token_count'):
        'source'         human-readable source name (e.g. 'nhtsa_crv_2018')
        'url'            origin URL, for citation in the final answer
        'model_year'     for the model-year-bleed mitigation
        'collected_date' for the stale-recall caveat in generation (M5)
    """
    all_chunks: list[dict] = []
    skipped_sources: list[str] = []
    for rec in read_manifest():
        if rec.get("error"):
            print(f"[skip] {rec.get('name')} — collection error: {rec['error']}")
            skipped_sources.append(rec.get("name", "?"))
            continue

        text = load_document(rec)
        if not text.strip():
            print(f"[skip] {rec['name']} — empty after cleaning "
                  f"(JS-rendered or error page)")
            skipped_sources.append(rec["name"])
            continue

        # Reject whole-document block / login / error pages before chunking.
        block_reason = _looks_like_block_page(text)
        if block_reason:
            print(f"[skip] {rec['name']} — {block_reason}; not real content")
            skipped_sources.append(rec["name"])
            continue

        raw_chunks = chunk_text(text, rec["source_type"])

        # If the source is mostly repetition, treat the whole thing as junk
        # rather than trusting the few unique survivors.
        rep = _repetition_ratio(raw_chunks)
        if rep > 0.5:
            print(f"[skip] {rec['name']} — {rep:.0%} duplicate chunks "
                  f"(boilerplate/block junk), dropping source")
            skipped_sources.append(rec["name"])
            continue

        # Collapse any remaining near-identical fragments within this source.
        chunks, dropped = _dedupe_chunks(raw_chunks)

        if not chunks:
            print(f"[skip] {rec['name']} — produced 0 chunks after cleaning "
                  f"(likely an error/empty page)")
            skipped_sources.append(rec["name"])
            continue

        for c in chunks:
            c["source"] = rec["name"]
            c["url"] = rec["url"]
            c["model_year"] = rec.get("model_year")
            c["collected_date"] = rec.get("collected_date")
        all_chunks.extend(chunks)
        note = f" ({dropped} dup chunks removed)" if dropped else ""
        print(f"[ok]   {rec['name']:<16} {rec['source_type']:<7} "
              f"-> {len(chunks)} chunks{note}")

    print(f"\nTotal: {len(all_chunks)} usable chunks "
          f"from {len(read_manifest()) - len(skipped_sources)} good sources")
    if skipped_sources:
        print(f"Skipped {len(skipped_sources)} source(s) as unusable: "
              f"{', '.join(skipped_sources)}")
    return all_chunks


if __name__ == "__main__":
    chunks = load_all_chunks()
    # Show one sample chunk so you can eyeball the metadata wiring.
    if chunks:
        import pprint
        print("\n--- sample chunk ---")
        pprint.pprint({k: (v[:120] + "..." if k == "text" and len(v) > 120 else v)
                       for k, v in chunks[0].items()})