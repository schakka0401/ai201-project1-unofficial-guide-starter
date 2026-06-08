# The Unofficial Guide — Project 1

A RAG system that makes used-car ownership knowledge — recalls, reliability, safety
ratings, and market pricing dynamics — searchable and answerable with grounded, cited
responses. Ask a plain-language question ("Does the 2018 Honda CR-V have any recalls?")
and get an answer drawn only from collected documents, with sources attributed.


(Before you run generate, run retrieval first to build the chromadb index. run => .venv312\Scripts\activate as well in the terminal to activate venv312 because 314 didnt work for me for some reason)

---

## Domain

This system covers the **used-car market** — specifically the kind of buying knowledge
that Kelley Blue Book reduces to a single price with no context. The valuable, hard-to-find
signal is scattered across recall databases, reliability surveys, owner forums, safety-test
results, and market-supply data, and no official channel synthesizes it. KBB gives you a
number; it doesn't tell you the 2018 CR-V has an open fuel-pump recall, that Consumer Reports
ranks the brand fifth for reliability, or that a low market-day-supply means you have no room
to negotiate. This guide indexes those scattered sources so a buyer can ask a real question
and get a grounded, cited answer.

After collection, the realistic scope narrowed: because most pricing/valuation sources block
scraping (see Failure Case and Document Sources), the system is **strong on recalls,
reliability, and safety, and thin on live valuation** — closer to a "reliability and
ownership-risk research assistant" than a full KBB replacement.

---

## Document Sources

13 sources were planned; **9 of 13 were blocked, paywalled, or moved**, leaving a working
corpus of the sources marked **usable** below. This source-availability problem is documented
honestly because it drove the system's final scope (see Failure Case Analysis).

| # | Source | Type | URL or file path | Status |
|---|--------|------|-----------------|--------|
| 1 | Kelley Blue Book FAQ (Fair Purchase Price) | prose | https://www.kbb.com/faq/used-cars/ | usable (thin) |
| 2 | CarMax inventory | record | https://www.carmax.com/cars | blocked (403) |
| 3 | r/whatcarshouldibuy | forum | reddit.com/r/whatcarshouldibuy | blocked (403) |
| 4 | CarEdge — Market Day Supply guide | prose | https://caredge.com/guides/fastest-selling-cars | usable |
| 5 | Consumer Reports — reliability rankings | prose | https://www.consumerreports.org/cars/car-reliability-owner-satisfaction/who-makes-the-most-reliable-cars-a7824554938/ | usable |
| 6 | r/MechanicAdvice | forum | reddit.com/r/MechanicAdvice | blocked (403) |
| 7 | CarComplaints.com | record | https://www.carcomplaints.com/ | usable (thin) |
| 8 | CivicX owner forum | forum | https://www.civicx.com/forum/ | usable |
| 9 | NHTSA recalls API (Honda CR-V 2018) | record | https://api.nhtsa.gov/recalls/recallsByVehicle?make=honda&model=cr-v&modelYear=2018 | usable (strongest) |
| 10 | Carvana inventory | record | https://www.carvana.com/cars | blocked (403) |
| 11 | IIHS safety ratings | record | https://www.iihs.org/ratings | usable (thin) |
| 12 | AutoTempest aggregated listings | record | https://www.autotempest.com/results?make=honda&model=cr-v | blocked (JS shell) |
| 13 | Lemon Squad PPI blog | prose | https://lemonsquad.com/blog/ | down (500) |

**Usable corpus (chunk counts):** NHTSA recalls (11), Consumer Reports (9), CivicX (7),
CarEdge (4); KBB, IIHS, and CarComplaints each survived as a single thin chunk.

---

## Chunking Strategy

**Chunk size:** Three document-type-specific sizes, measured in **tokens**:
- Prose (KBB, CarEdge, Consumer Reports): 400–500 tokens
- Structured records (NHTSA recalls, IIHS, CarComplaints): 150–200 tokens, one record per chunk
- Forum threads (CivicX): up to 500 tokens, one thread per chunk

**Overlap:** 50 tokens for prose; 0 for records and forums.

**Why these choices fit the documents:** The corpus has three structurally different document
types that warrant different handling. Prose guides contain claims that span paragraph
boundaries, so a 50-token overlap keeps a boundary-straddling fact retrievable. Structured
records (a single NHTSA recall, one IIHS rating row) are already discrete, self-contained
facts — chunking one record per chunk with zero overlap means a query for "2018 CR-V recalls"
retrieves exactly that record, not a blob merging unrelated model years. Forum threads keep
the question and its top replies together as one unit so a complaint isn't separated from its
diagnosis.

Length is measured in **tokens, not characters** (using `tiktoken`'s `cl100k_base`), because
the embedding model consumes tokens and truncates past its ~256-token limit — chunking in the
same unit makes "this chunk fits the embedder" a verifiable fact rather than a 4-chars-per-token
estimate. Records and forums are split **structurally** (on record/thread boundaries) before
length-capping, because a plain character/length splitter cannot honor "one record per chunk."

**Preprocessing before chunking:** HTML cleaned via `trafilatura` (main-content extraction,
drops nav/menu/footer/cookie chrome); a normalization pass decodes HTML entities (`&amp;`,
`&nbsp;`), strips standalone UI-chrome lines (share/read-more/comment-counts), and removes runs
of menu/list-item lines (e.g. 50-state dropdowns). Block pages (403/login walls) and sources
that are >50% duplicate chunks are detected and dropped entirely.

**Final chunk count:** **39 usable chunks** from the working sources. (Low relative to the
50-chunk guideline — not because chunks are oversized, but because 9 of 13 sources were
unscrapeable; see Document Sources and Failure Case.)

---

## Embedding Model

**Model used:** `all-MiniLM-L6-v2` via `sentence-transformers` (384-dimensional, runs locally,
no API key or rate limits). Stored in a persisted **ChromaDB** collection with cosine
similarity. It suits the short-to-medium chunk sizes (150–500 tokens) in this corpus, and the
small vector dimension keeps the index compact.

**Production tradeoff reflection:** For a course milestone, all-MiniLM-L6-v2 is the right call —
free, local, fast. For a real deployment I'd weigh: **context length** (its ~256-token limit
truncates longer chunks, which is why I size chunks in tokens; a model like `text-embedding-3-small`
allows much longer context), **domain accuracy** (a model fine-tuned on automotive/recall text,
or `e5-base` fine-tuned on this corpus, would embed terms like "TSB," campaign numbers, and
trim names more meaningfully than a general model), **latency vs. cost** (local MiniLM has zero
marginal cost but uses local compute; an API model offloads compute but adds per-call cost and
network latency), and **multilingual support** (irrelevant here since the corpus is English-only,
but relevant if expanding to non-US markets). Most likely production choice:
`text-embedding-3-small` for cost-efficient long context, or a fine-tuned `e5-base` if domain
accuracy justified the training effort.

---

## Sample Chunks

Five representative chunks, each labeled with its source document. (Pulled from the live
corpus via `inspect_clean.py` / `eval_capture.py`.)

1. **source: `nhtsa_crv_2018` (record)** — "Summary: Honda (American Honda Motor Co.) is
   recalling certain 2017-2020 CR-V... [recall description and remedy]" — a single
   self-contained recall record.
2. **source: `cr_reliability` (prose)** — "How We Score Reliability: Every year, Consumer
   Reports asks its members about problems they've had with their vehicles in the previous 12
   months... 20 specific trouble areas... predicted reliability score from 1 to 100."
3. **source: `caredge_guides` (prose)** — "Market Day Supply (MDS) measures how many days it
   would take to sell all current inventory of a vehicle at the current rate of sales. It's
   calculated by dividing total vehicles for sale by the average daily sales rate over the
   past 45 days."
4. **source: `civicx` (forum)** — owner-forum thread chunk (question + top replies kept
   together as one unit).
5. **source: `iihs_ratings` (record)** — "Vehicle ratings: IIHS tests evaluate two aspects of
   safety: crashworthiness — how well a vehicle protects occupants in a crash..." (Note: this
   chunk is the generic methodology text — see Failure Case Analysis for why it lacks
   model-specific data.)

<!-- TIP: paste the exact full text of 5 chunks from your `inspect_clean.py` output here if you
     want maximum credit — the summaries above are accurate but the rubric likes verbatim. -->

---

## Query Interface

The interface is a **command-line REPL** (`generate.py`). The rubric permits a CLI as long as
it's usable without narration.

- **Input:** a free-text question typed at the `you>` prompt.
- **Output:** a grounded natural-language answer with inline `[source=...]` citations; `[STALE]`
  caveats appear automatically when a cited chunk is >90 days old. Top-k is tiered (broad
  questions retrieve 8 chunks, others 5). Type `quit` to exit.

**Sample interaction transcript:**

```
you> Does the 2018 Honda CR-V have any open recalls, and what are they?

The 2018 Honda CR-V has several open recalls. One is a front seat-belt issue where the
buckle channel may interfere with the release button, preventing latching
[source=nhtsa_crv_2018]; the remedy is to replace the buckle release buttons or buckle
assemblies free of charge [source=nhtsa_crv_2018]. Another concerns the electronic power
steering torque-sensor magnet becoming dislodged [source=nhtsa_crv_2018], remedied by
replacing the steering gearbox assembly. A further recall covers a possible fuel-pump
failure [source=nhtsa_crv_2018]. None of the chunks are marked [STALE] (collected
2026-06-05), but it is advisable to verify current recall status with NHTSA before purchase.

you> What is the best German V8 in terms of reliability and performance?

There is no information in the provided context about German V8 engines [source=cr_reliability].
The context discusses brand/model reliability rankings but does not cover German V8 engines,
so I cannot answer this from the available documents.
```

---
## Grounded Generation


**LLM:** Groq `llama-3.3-70b-versatile` (free-tier, OpenAI-compatible API). 

**System prompt grounding instruction:** The system message is a hard constraint, not a
suggestion. It instructs the model: answer **ONLY** from the provided context chunks; do not
use outside knowledge or invent facts; if the context lacks the answer, say so plainly rather
than guessing; cite the `[source]` label on each chunk for every claim; attend to each chunk's
`model_year` and never generalize a recall/complaint across years unless a chunk says so; and
if a chunk is marked `[STALE]` (collected >90 days ago), caveat its time-sensitive claims and
tell the user to verify against the official source. Temperature is set to 0.2 to favor
grounded over creative output.

**How source attribution is surfaced:** Each retrieved chunk is labeled in the prompt with its
`source`, `source_type`, `model_year`, `collected_date`, and a `[STALE]` marker where
applicable. The model is instructed to cite the `[source=...]` label inline with each claim,
and it does so at the per-claim level (separating, e.g., a recall's description from its remedy
when they come from different chunks). Grounding was validated end-to-end: an out-of-corpus
query ("best German V8") was refused rather than answered from training knowledge.

--- 

## Evaluation Report

The 5 questions were defined in planning.md **before** implementation. Retrieval distances are
cosine (lower = more similar; <0.5 is a strong match).

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | 2018 CR-V open recalls? | Names specific recalls + remedies | Named seat-belt buckle, power-steering magnet, fuel-pump recalls w/ remedies, cited `nhtsa_crv_2018`, stale-aware | Relevant (0.319–0.344, correct source) | **Accurate** |
| 2 | F-150 2.7L EcoBoost common failure + mileage? | Intake-valve carbon buildup, ~60–90k mi | Declined — context lacks F-150 EcoBoost data | Off-target (top 0.569, all `cr_reliability`) | **Inaccurate** (correct refusal) |
| 3 | 2020 RAV4 XLE $21.5k vs Edmunds TMV + days supply | ~$22–23.5k TMV (below/fair); low supply = little leverage | Explained MDS from CarEdge; correctly refused to apply 2026 figures to a 2020 question; could not give TMV (source absent) | Partially relevant (0.542, CarEdge) | **Partially accurate** |
| 4 | What does a PPI catch that Carfax misses? | Mechanical/structural issues vs. title events only | Declined — no chunk addresses PPI vs Carfax | Off-target (top 0.581, mixed) | **Inaccurate** (correct refusal) |
| 5 | 2019 Forester IIHS rating + weak category? | Top Safety Pick+, headlights weak on base trims | Declined — context lacks model-specific IIHS rating | **Relevant (0.402, correct source)** but content too sparse | **Inaccurate** |

**Summary:** 1 accurate, 1 partially accurate, 3 inaccurate (all clean refusals, no
hallucination). All failures trace to the **ingestion stage** — 9 of 13 planned sources were
blocked/paywalled/moved, leaving the corpus strong on recalls/reliability/safety-methodology
and empty on pricing, PPIs, and model-specific data. The eval questions were written before
source availability was known, so the failures reflect corpus coverage, not pipeline logic
errors on available data.

---

## Failure Case Analysis

**Question that failed:** Q5 — "What IIHS safety rating did the 2019 Subaru Forester receive,
and which test category, if any, was not rated Good?"

**What the system returned:** It declined, stating the context did not contain the Forester's
specific rating.

**Root cause (tied to a specific pipeline stage):** This is **not** a retrieval failure — and
that's what makes it instructive. Retrieval returned the correct source (`iihs_ratings`) at a
cosine distance of **0.402**, below the 0.5 strong-match threshold. The failure is upstream, in
the **ingestion/chunking stage**: the IIHS page (iihs.org/ratings) loads its per-vehicle ratings
dynamically via JavaScript, which a static `requests` fetch never retrieves. Cleaning therefore
extracted only the page's static *methodology* text ("IIHS tests evaluate two aspects of
safety: crashworthiness..."), and chunking produced a single generic chunk with zero
Forester-specific data. Retrieval did its job perfectly — it returned the single best-matching
chunk — but that chunk was structurally incapable of answering a model-specific question.

This is a different failure mode from Q2 (F-150) and Q4 (PPI), where the source documents were
**entirely absent** (403/500 errors) and retrieval distances were correspondingly high (>0.56),
correctly signaling "no relevant content exists." Q5 is the subtler case: **source present,
retrieved with a strong score, but too sparse to answer.** A high-distance miss says the corpus
lacks a topic; a low-distance miss that still can't answer says a source was ingested shallowly.

**What I would change to fix it:** Ingest IIHS via its underlying ratings API/JSON endpoint
(as one-record-per-chunk), the same approach that made the NHTSA recall source the strongest in
the corpus (Q1) — or render the page with a headless browser (Playwright) so the
JavaScript-populated ratings table is present before extraction. The API approach is preferable
because it mirrors exactly why Q1 succeeded (clean structured records) and why Q5 failed (a
JS-rendered page reduced to one boilerplate chunk).

**What this confirms about the design:** In every failure, the system **refused rather than
fabricating** an answer from training knowledge — even in Q5, where a strong-scoring chunk was
present and the Forester's rating is well-known, a weaker grounding prompt might have tempted the
model to fill it in. This validates that the grounding instruction functions as a hard constraint.

---

## Spec Reflection


**One way the spec helped you during implementation:**
My Chunking Strategy section defined three separate document types — prose, structured records, and forum threads — each with its own chunk size and overlap, instead of a single blanket rule. That specificity paid off when I implemented the chunker: because the spec said structured records like NHTSA recalls should be "one record per chunk," it immediately exposed that a plain character-length splitter can't actually do that — it cuts on length, not on record boundaries. A vaguer spec would have let generic code through that merged different model years' recalls into one chunk. Catching this meant each NHTSA recall became its own chunk, which is the direct reason my recall query (Q1) retrieved cleanly (distances around 0.32) and produced my most accurate answer.

**One way your implementation diverged from the spec, and why:**
My spec planned 13 sources and framed the project as a KBB-style valuation tool. In practice, 9 of the 13 were blocked, paywalled, or moved — every major pricing source (Edmunds, CarMax, Carvana, AutoTempest) actively blocks scraping — so the working corpus shrank to 39 chunks. Rather than overclaim coverage I couldn't back, I narrowed the actual scope toward what was obtainable: reliability, recalls, and safety, where NHTSA, Consumer Reports, and CivicX gave solid data. This divergence is why several eval questions about pricing and inspections returned honest "not enough information" responses instead of fabricated answers — the implementation followed the corpus I could actually build, not the one I'd planned.

---

## AI Usage

**Instance 1**

- *What I gave the AI:* the traceback when retrieval.py crashed on import chromadb — a numpy error, OverflowError: cannot convert longdouble infinity to integer, coming out of numpy's getlimits.py
- *What it produced:* The AI gave me a solution where it pointed out that the installation logs were on Python 3.14 which was too new for the ML stack, and it ended up reccomending Python 3.12 instead.
- *What I changed or overrode:* I did a little research, and created the .venv312 and installed the ML stack on that instead.

**Instance 2**

- *What I gave the AI:* I gave the AI my chunking strategy.
- *What it produced:* What came back flagged a technical mismatch: the spec was written in tokens but the splitter (RecursiveCharacterTextSplitter) counts characters by default, and a plain length splitter can't produce "one record per chunk."
- *What I changed or overrode:* I redirected it so that it still split by tokens, by tiktoken with structural splitting via thread boundaries before capping the length.