"""
ingest.py  —  Project 1: AI Kelley Blue Book
Document ingestion + chunking pipeline (Milestone 3).

Implements the first two stages of the architecture diagram in planning.md:

    Document ingestion ──> Chunking
    (requests/BeautifulSoup)  (token- and structure-aware splitting)

-------------------------------------------------------------------------------
NOTE ON SPEC vs. THIS IMPLEMENTATION  (read this during your review step)
-------------------------------------------------------------------------------
Your Chunking Strategy section is written in TOKENS:
    prose   400-500 tok, 50 tok overlap
    records 150-200 tok, 0 overlap, ONE record per chunk
    forum   <=500 tok,   0 overlap, ONE thread per chunk

Your Milestone 3 prompt, however, asked for a plain
RecursiveCharacterTextSplitter with character sizes (1800/200, 700/0, 1800/0).
A plain character splitter CANNOT honour "one record per chunk" or "one thread
per chunk" — it cuts on length, not on record/thread boundaries. So this code
departs from the literal prompt in two deliberate ways:

  1. It counts length in TOKENS (via tiktoken if available, else a ~4 char/token
     fallback) so the splitter matches the units your spec is written in.
  2. 'record' and 'forum' are split STRUCTURALLY first (by record/thread
     boundary), and only then length-capped. This is what actually satisfies
     your verification criteria ("record chunks contain exactly one entry").

Both departures are flagged inline with #SPEC: comments.
-------------------------------------------------------------------------------
"""

from __future__ import annotations
import re
from typing import Callable

import requests
from bs4 import BeautifulSoup
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

# --------------------------------------------------------------------------- #
# Token counting
# --------------------------------------------------------------------------- #
# Your spec is in tokens. RecursiveCharacterTextSplitter measures characters by
# default; we pass it a length_function so the 400/200/500 numbers below mean
# tokens, not characters. If tiktoken isn't installed we fall back to the common
# ~4-characters-per-token heuristic so the script still runs.
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
except Exception:  # tiktoken missing or offline
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)  # rough fallback


# --------------------------------------------------------------------------- #
# Stage 1 — Document ingestion
# --------------------------------------------------------------------------- #
def fetch_document(url: str, timeout: int = 20) -> str:
    """Fetch a URL and return cleaned plain text.

    Uses requests + BeautifulSoup as specified in the architecture diagram.
    Strips script/style/nav/footer boilerplate and collapses whitespace.
    (PDF/JSON sources from your table would route to pdfplumber / json instead;
    this covers the HTML sources, which are the majority.)
    """
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (Project1-AI-KBB research bot)"},
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines to a single blank line (paragraph boundary)
    # and strip trailing spaces, so chunkers see clean structure.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Stage 2 — Chunking
# --------------------------------------------------------------------------- #
# Per-source-type parameters, in TOKENS, taken straight from planning.md.
# Midpoints of your stated ranges are used as the targets.
_PARAMS = {
    "prose":  {"chunk_size": 450, "chunk_overlap": 50},  # 400-500 tok, 50 overlap
    "record": {"chunk_size": 175, "chunk_overlap": 0},   # 150-200 tok, 0 overlap
    "forum":  {"chunk_size": 500, "chunk_overlap": 0},   # <=500 tok,   0 overlap
}

# Drop junk fragments — but ONLY for prose. NHTSA/IIHS/complaint records are
# legitimately short (often 15-40 tokens), so applying this floor to 'record'
# would silently delete valid entries. (Found this in verification: a 100-char
# floor wiped out every short recall record.)
_MIN_TOKENS = 25  # ~100 chars; mirrors your "no chunk shorter than 100 chars"


def _prose_chunks(text: str, length_fn: Callable[[str], int]) -> list[str]:
    """Length-based recursive splitting for mid-length explanatory prose.

    #SPEC: This is the only type your original prompt maps onto cleanly —
    a recursive splitter with overlap, just measured in tokens.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_PARAMS["prose"]["chunk_size"],
        chunk_overlap=_PARAMS["prose"]["chunk_overlap"],
        length_function=length_fn,
        separators=["\n\n", "\n", ". ", " ", ""],  # prefer paragraph > sentence
    )
    return splitter.split_text(text)


def _record_chunks(text: str, length_fn: Callable[[str], int]) -> list[str]:
    """One structured record (recall / TSB / IIHS row / complaint) per chunk.

    #SPEC: A plain character splitter would merge unrelated model years into one
    blob, which your Anticipated Challenges section explicitly warns against.
    So we split on record boundaries first. Heuristic: records in these sources
    are separated by blank lines. Any single record that still exceeds the token
    cap is hard-split as a safety valve (rare for short NHTSA/IIHS entries).
    """
    raw_records = [r.strip() for r in re.split(r"\n\s*\n", text) if r.strip()]
    cap = _PARAMS["record"]["chunk_size"]
    out: list[str] = []
    for rec in raw_records:
        if length_fn(rec) <= cap:
            out.append(rec)
        else:
            # oversized single record — fall back to length split, no overlap
            sub = RecursiveCharacterTextSplitter(
                chunk_size=cap, chunk_overlap=0, length_function=length_fn,
            )
            out.extend(sub.split_text(rec))
    return out


def _forum_chunks(text: str, length_fn: Callable[[str], int]) -> list[str]:
    """One thread per chunk: question post + top replies kept together.

    #SPEC: Your strategy treats a thread as one atomic unit and only splits a
    too-long thread AFTER a complete reply, never mid-reply. We treat blank
    lines as reply boundaries: greedily pack whole replies into a chunk until
    the next reply would exceed the cap, then start a new chunk on a reply
    boundary. This directly mitigates the "model-year bleed" risk you named.
    """
    replies = [r.strip() for r in re.split(r"\n\s*\n", text) if r.strip()]
    cap = _PARAMS["forum"]["chunk_size"]
    out: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            out.append("\n\n".join(buf))
            buf.clear()

    for reply in replies:
        candidate = ("\n\n".join(buf + [reply])) if buf else reply
        if buf and length_fn(candidate) > cap:
            flush()                 # close current chunk at a reply boundary
            buf.append(reply)       # start new chunk with this reply
        elif not buf and length_fn(reply) > cap:
            # a single reply alone is over cap — split it, no overlap
            sub = RecursiveCharacterTextSplitter(
                chunk_size=cap, chunk_overlap=0, length_function=length_fn,
            )
            out.extend(sub.split_text(reply))
        else:
            buf.append(reply)
    flush()
    return out


def chunk_text(text: str, source_type: str,
               length_fn: Callable[[str], int] = count_tokens) -> list[dict]:
    """Split `text` into chunk dicts according to `source_type`.

    Args:
        text:        cleaned plain text from fetch_document()
        source_type: one of 'prose', 'record', 'forum'
        length_fn:   token counter (default tiktoken/heuristic)

    Returns a list of dicts, each with keys:
        'text', 'source_type', 'char_count', 'token_count'
    """
    if source_type not in _PARAMS:
        raise ValueError(
            f"source_type must be one of {list(_PARAMS)}, got {source_type!r}"
        )

    if source_type == "prose":
        pieces = _prose_chunks(text, length_fn)
    elif source_type == "record":
        pieces = _record_chunks(text, length_fn)
    else:  # forum
        pieces = _forum_chunks(text, length_fn)

    chunks = []
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        # Min-length floor applies only to prose; records/forums may be short
        # by design (see note above).
        if source_type == "prose" and length_fn(p) < _MIN_TOKENS:
            continue
        chunks.append({
            "text": p,
            "source_type": source_type,
            "char_count": len(p),
            "token_count": length_fn(p),
        })
    return chunks


# --------------------------------------------------------------------------- #
# __main__ — one test URL per source type, prints chunk counts
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # One representative source of each type from your Documents table.
    TEST_SOURCES = [
        ("https://www.kbb.com/car-advice/kbb-fair-purchase-price/", "prose"),
        ("https://www.nhtsa.gov/vehicle/2018/HONDA/CR-V/SUV/AWD#recalls", "record"),
        ("https://www.reddit.com/r/whatcarshouldibuy/", "forum"),
    ]

    for url, stype in TEST_SOURCES:
        print(f"\n=== {stype.upper()} :: {url}")
        try:
            raw = fetch_document(url)
            chunks = chunk_text(raw, stype)
            print(f"    fetched {len(raw):,} chars -> {len(chunks)} chunks")
            if chunks:
                tok = [c["token_count"] for c in chunks]
                print(f"    token range: {min(tok)}-{max(tok)} "
                      f"(target {_PARAMS[stype]['chunk_size']})")
        except Exception as e:  # network/parse failures shouldn't kill the loop
            print(f"    ERROR: {e}")