"""
generate.py — Project 1: AI Kelley Blue Book
Milestone 5: Generation + interface (RAG answer step).

Pipeline stage:  query --> retrieve() [M4] --> chunks --> [answer()] --> LLM --> grounded reply

LLM provider: Groq (OpenAI-compatible, free tier). NOTE: the Milestone 5 prompt
in planning.md said to call the Anthropic API with claude-sonnet-4. We use Groq
+ an open Llama model instead (free, fast). This is a documented substitution —
update your planning doc's AI Tool Plan to reflect Groq rather than Anthropic.

Setup:
    pip install groq python-dotenv
    Put your key in .env:   GROQ_API_KEY=gsk_...

Two planning-doc risks are addressed directly in the prompt template (see
build_prompt): (1) STALE RECALL DATA — chunks older than STALE_DAYS are flagged
so the model caveats them; (2) MODEL-YEAR BLEED — the model is told to attend to
the model_year on each chunk and not generalize a complaint across years.
"""

from __future__ import annotations
import os
import datetime as dt

from dotenv import load_dotenv
from groq import Groq

from retrieval import retrieve

load_dotenv()

# Current Groq production model (free tier). Swap if deprecated — check
# console.groq.com/docs/models. 70B versatile = best free general model.
_MODEL = "llama-3.3-70b-versatile"
_FALLBACK_MODEL = "llama-3.1-8b-instant"   # smaller/faster if 70B is busy
STALE_DAYS = 90                            # chunks older than this get caveated

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY not set. Put it in a .env file as "
                "GROQ_API_KEY=gsk_... or set it in your environment.")
        _client = Groq(api_key=key)
    return _client


def _days_old(collected_date: str) -> int | None:
    """How many days ago was this chunk collected? None if no/!bad date."""
    if not collected_date:
        return None
    try:
        d = dt.date.fromisoformat(collected_date)
        return (dt.date.today() - d).days
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
SYSTEM_INSTRUCTION = (
    "You are a used-car research assistant. Answer ONLY from the provided "
    "context chunks — do not use outside knowledge or invent facts. If the "
    "context does not contain the answer, say so plainly rather than guessing. "
    "Always cite which source each claim comes from using the [source] label "
    "shown on each chunk. "
    "Pay close attention to the model_year on each chunk: a complaint or recall "
    "for one model year does NOT necessarily apply to another — never generalize "
    "across years unless a chunk explicitly says so. "
    "If a chunk is marked [STALE], treat its time-sensitive facts (especially "
    "recall status) as possibly out of date and tell the user to verify against "
    "the official source before relying on it."
)


def build_prompt(query: str, chunks: list[dict]) -> str:
    """Build the user-content string: labeled chunks + the question.

    Each chunk is labeled with its source, source_type, model_year, and a
    [STALE] marker if collected_date is older than STALE_DAYS — which is how
    the two planning-doc risks (stale recall data, model-year bleed) are
    surfaced to the model.
    """
    if not chunks:
        return (f"CONTEXT: (no relevant chunks were retrieved)\n\n"
                f"QUESTION: {query}\n\n"
                f"There is no context, so explain that you don't have "
                f"information on this and cannot answer reliably.")

    blocks = []
    for i, c in enumerate(chunks, 1):
        age = _days_old(c.get("collected_date", ""))
        stale = " [STALE]" if (age is not None and age > STALE_DAYS) else ""
        year = c.get("model_year")
        year_label = f" model_year={year}" if year not in (None, "") else ""
        label = (f"[chunk {i} | source={c.get('source','?')} "
                 f"| type={c.get('source_type','?')}{year_label}"
                 f"{stale} | collected={c.get('collected_date','?')}]")
        blocks.append(f"{label}\n{c['text']}")

    context = "\n\n".join(blocks)
    return (f"CONTEXT:\n{context}\n\n"
            f"QUESTION: {query}\n\n"
            f"Answer using only the context above, citing sources by their "
            f"[source] label. Flag any [STALE] chunk's time-sensitive claims.")


# --------------------------------------------------------------------------- #
# answer
# --------------------------------------------------------------------------- #
def answer(query: str, persist_path: str = "chroma_db", k: int = 5) -> str:
    """Retrieve top-k chunks and generate a grounded, cited answer via Groq."""
    chunks = retrieve(query, persist_path, k=k)
    user_content = build_prompt(query, chunks)

    client = _get_client()
    try:
        resp = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,   # low — we want grounded, not creative
        )
    except Exception as e:
        # If the primary model is rate-limited/unavailable, try the smaller one.
        resp = client.chat.completions.create(
            model=_FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )
    return resp.choices[0].message.content


# --------------------------------------------------------------------------- #
# CLI loop
# --------------------------------------------------------------------------- #
def _cli():
    print("AI Used-Car Guide (Groq RAG). Type a question, or 'quit' to exit.\n")
    while True:
        try:
            query = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if query.lower() in {"quit", "exit", "q"}:
            print("bye")
            break
        if not query:
            continue
        # Simple top-k tiering per planning.md: broad question -> 8, else 5.
        k = 8 if len(query.split()) > 10 else 5
        try:
            print("\n" + answer(query, k=k) + "\n")
        except Exception as e:
            print(f"[error] {e}\n")


if __name__ == "__main__":
    _cli()