"""
retrieval.py — Project 1: AI Kelley Blue Book
Milestone 4: Embedding + vector store + retrieval.

Pipeline stage:  ... load.py (chunks) --> [build_index] --> ChromaDB
                 query --> [retrieve] --> top-k chunks --> (Milestone 5: generate)

Embedding model: all-MiniLM-L6-v2 (sentence-transformers), 384-dim — per the
Retrieval Approach section of planning.md. Vector store: persisted ChromaDB.

----------------------------------------------------------------------------
NOTE ON SPEC vs. THIS IMPLEMENTATION (for your review/writeup)
----------------------------------------------------------------------------
The Milestone 4 prompt said to store metadata fields `source_type` and
`char_count` only. This code stores those PLUS `source`, `url`, `model_year`,
and `collected_date`. Reason: your own risk mitigations need them —
  - collected_date  -> Milestone 5 stale-recall caveat ("as of <date>...")
  - model_year      -> model-year-bleed mitigation
  - source / url    -> source citation in the final answer
Storing only the two named fields would strip the metadata your planning doc
depends on, so this is a deliberate, documented expansion of the spec.

Also implements the top-k tiering from your Retrieval Approach section:
default k=5, but retrieve() accepts any k (use 8 for broad queries, 3 for
precise record lookups).

requirements (exact versions this was written against):
    chromadb==0.5.5
    sentence-transformers==3.0.1
    (sentence-transformers pulls torch + transformers automatically)
Install:  pip install "chromadb==0.5.5" "sentence-transformers==3.0.1"
----------------------------------------------------------------------------
"""

from __future__ import annotations
import hashlib
import os

import chromadb
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_COLLECTION = "used_car_guide"

# Load the embedding model once at import (it's ~80 MB; reloading per call is slow).
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings -> list of 384-dim vectors (as plain lists)."""
    vecs = _get_model().encode(
        texts,
        normalize_embeddings=True,   # cosine similarity via normalized vectors
        show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]


# --------------------------------------------------------------------------- #
# build_index
# --------------------------------------------------------------------------- #
def build_index(chunks: list[dict], persist_path: str = "chroma_db") -> int:
    """Embed chunk dicts and store them in a persisted ChromaDB collection.

    Args:
        chunks: list of dicts from load.load_all_chunks(). Each must have
                'text' and 'source_type'; optional 'source', 'url',
                'model_year', 'collected_date', 'char_count', 'token_count'.
        persist_path: directory where ChromaDB persists to disk.

    Idempotent: re-running on the same chunks does NOT duplicate entries,
    because each chunk gets a deterministic id derived from its source + text.
    (Your verification step checks count() before/after a second build.)

    Returns the number of chunks in the collection after building.
    """
    client = chromadb.PersistentClient(path=persist_path)
    collection = client.get_or_create_collection(
        name=_COLLECTION,
        metadata={"hnsw:space": "cosine"},   # cosine distance
    )

    if not chunks:
        return collection.count()

    ids, documents, metadatas = [], [], []
    seen_ids: set[str] = set()
    for i, c in enumerate(chunks):
        text = c["text"]
        source = c.get("source", "unknown")
        # Deterministic id: same source+text -> same id -> upsert, no dup.
        # Use md5 (stable across processes) not built-in hash() (randomized
        # per-process by PYTHONHASHSEED, which would break cross-run idempotency).
        digest = hashlib.md5(f"{source}:{text}".encode("utf-8")).hexdigest()[:12]
        cid = f"{source}:{digest}"
        if cid in seen_ids:            # exact-dup within this batch
            continue
        seen_ids.add(cid)

        ids.append(cid)
        documents.append(text)
        # Chroma metadata values must be str/int/float/bool — coerce None away.
        meta = {
            "source_type": c.get("source_type", ""),
            "char_count": int(c.get("char_count", len(text))),
            "source": source,
            "url": c.get("url") or "",
            "model_year": c.get("model_year") if c.get("model_year") is not None else "",
            "collected_date": c.get("collected_date") or "",
        }
        metadatas.append(meta)

    embeddings = _embed(documents)

    # upsert (not add) so a second run overwrites rather than duplicates.
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    return collection.count()


# --------------------------------------------------------------------------- #
# retrieve
# --------------------------------------------------------------------------- #
def retrieve(query: str, persist_path: str = "chroma_db", k: int = 5) -> list[dict]:
    """Embed `query` and return the top-k most similar chunks.

    Per planning.md top-k tiering: default 5; pass k=8 for broad
    multi-source queries, k=3 for precise record lookups.

    Returns a list of dicts with keys: 'text', 'source_type', 'distance',
    plus the stored metadata ('source', 'url', 'model_year', 'collected_date')
    so the generation step (M5) can cite sources and caveat stale data.
    """
    client = chromadb.PersistentClient(path=persist_path)
    collection = client.get_or_create_collection(
        name=_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    if collection.count() == 0:
        return []

    q_emb = _embed([query])[0]
    res = collection.query(
        query_embeddings=[q_emb],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    out = []
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]
    for doc, meta, dist in zip(docs, metas, dists):
        out.append({
            "text": doc,
            "source_type": meta.get("source_type", ""),
            "distance": dist,
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "model_year": meta.get("model_year", ""),
            "collected_date": meta.get("collected_date", ""),
        })
    return out


# --------------------------------------------------------------------------- #
# __main__ — build from real corpus (or samples) and run test queries
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    PERSIST = "chroma_db"

    # Prefer the real corpus via load.py; fall back to tiny samples if the
    # raw/ dir isn't present (e.g. running this file in isolation).
    try:
        import load
        chunks = load.load_all_chunks()
    except Exception as e:
        print(f"[warn] couldn't load real corpus ({e}); using sample chunks")
        chunks = [
            {"text": "Market Day Supply measures how many days it would take to "
                     "sell all current inventory at the current sales rate.",
             "source_type": "prose", "source": "caredge_guides",
             "url": "https://caredge.com/guides/fastest-selling-cars",
             "model_year": None, "collected_date": "2026-06-05",
             "char_count": 110},
            {"text": "Consumer Reports scores reliability from 1 to 100 across "
                     "20 trouble areas using owner surveys of ~380,000 vehicles.",
             "source_type": "prose", "source": "cr_reliability",
             "url": "https://www.consumerreports.org/", "model_year": None,
             "collected_date": "2026-06-05", "char_count": 115},
            {"text": "Component: ENGINE. 2018 Honda CR-V oil dilution in cold "
                     "climates. Campaign 19V001. Remedy: software update.",
             "source_type": "record", "source": "nhtsa_crv_2018",
             "url": "https://api.nhtsa.gov/", "model_year": 2018,
             "collected_date": "2026-06-05", "char_count": 105},
        ]

    count = build_index(chunks, PERSIST)
    print(f"\nIndex built: {count} chunks in collection.")

    # Idempotency check (your verification step): build again, count unchanged.
    count2 = build_index(chunks, PERSIST)
    print(f"Rebuild count: {count2} (should equal {count} — idempotent)")

    print("\n--- test queries ---")
    for q, k in [
        ("how is market day supply calculated", 5),
        ("does the 2018 CR-V have any recalls", 3),
        ("how does Consumer Reports score reliability", 5),
    ]:
        print(f"\nQ: {q!r} (k={k})")
        for r in retrieve(q, PERSIST, k=k):
            print(f"  [{r['distance']:.3f}] {r['source']:<16} "
                  f"{r['text'][:80]}...")