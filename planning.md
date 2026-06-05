# Project 1 Planning: The Unofficial Guide

> Write this document before you write any pipeline code.
> Your spec and architecture diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Update the Retrieval Approach and Chunking Strategy sections if you change your approach during implementation.
> Update this file before starting any stretch features.

---

## Domain

<!-- What domain did you choose? Why is this knowledge valuable and hard to find through official channels? -->
I chose the used car market as my domain, specifically focusing on building an AI version of the Kelley Blue Book. This would help people determine what a car actually is worth, what to watch out for when buying a specific car, and what previous owners rate the car. The knowledge is hard to obtain because KBB gives you a single number with no context, reliability data, and no buyer stories. The real signal is scattered across forums, recall databases, owner reviews, and auction data — none of which KBB synthesizes. An AI guide that chunks and indexes all of this would let someone ask "is this 2018 Honda CR-V worth $18k?" and get a real answer.
---

## Documents

<!-- List your specific sources: URLs, subreddit names, forum threads, or file descriptions.
     Aim for at least 10 sources that together cover different subtopics or perspectives within your domain. -->

The **Source status** column records what each URL actually returned when `collect.py`
was run (HTTP status / outcome of the first scrape pass). This drives which sources are
usable as-is versus which need a workaround (see Anticipated Challenges #4).

| # | Source | Description | URL or location | Source status |
|---|--------|-------------|-----------------|---------------|
| 1 | KBB Fair Purchase Price methodology | Explains how KBB calculates its value estimates — useful for documenting exactly what the guide improves upon | https://www.kbb.com/faq/used-cars/ | **URL corrected** (was 404). Re-scrape pending; KBB may still bot-block at the new address. Alt: b2b.kbb.com/.../definitions-of-our-values/ |
| 2 | CarMax used-car inventory | Live used-car listings (price, mileage, year, trim) from the largest US used-car retailer; real transaction-adjacent pricing | https://www.carmax.com/cars | **REPLACED edmunds_tmv** (403). Inventory is JS/API-rendered — re-scrape pending; plain requests likely returns an empty shell |
| 3 | r/whatcarshouldibuy subreddit | Buyer threads with real offer prices and crowd-sourced "fair/too high/steal" verdicts; rich with regional variation | https://www.reddit.com/r/whatcarshouldibuy/ | **403** — Reddit blocks unauthenticated `.json`; needs API/old.reddit |
| 4 | CarEdge market days supply & buying guides | Days-on-lot data and negotiation leverage by make/model; covers supply-side pricing KBB ignores | https://caredge.com/guides/fastest-selling-cars | **URL corrected** (was 404). New slug explicitly explains Market Day Supply; re-scrape pending |
| 5 | Consumer Reports reliability summaries | Model-year reliability scores broken down by system (engine, transmission, brakes, etc.) | https://www.consumerreports.org/cars/car-reliability-owner-satisfaction/who-makes-the-most-reliable-cars-a7824554938/ | **URL corrected** (was 404). Page explains scoring methodology; CR is partly paywalled so expect possibly intro-only; re-scrape pending |
| 6 | r/MechanicAdvice — model-specific threads | Real owner-reported failure modes and repair costs; best source for year-specific "gotchas" | https://www.reddit.com/r/MechanicAdvice/ | **403** — same Reddit block as #3 |
| 7 | CarComplaints.com model pages | Aggregated owner complaints with severity ratings, mileage at failure, and avg repair cost per model year | https://www.carcomplaints.com/ | **200 — usable** (~29 KB); verify content isn't a landing shell |
| 8 | Model-specific owner forums (CivicX, ToyotaNation) | Long-running threads on known defects, TSBs, and pre-purchase inspection tips from marque owners | https://www.civicx.com/forum/ · https://www.toyotanation.com/forums/ | **200 — usable** (~234 KB) |
| 9 | NHTSA recall database | Official recall records by model/year — standardized short entries; flags open recalls KBB never surfaces | https://api.nhtsa.gov/recalls/recallsByVehicle?make=honda&model=cr-v&modelYear=2018 | **200 — usable** (~6.6 KB clean JSON); highest-value source |
| 10 | Carvana used-car inventory | Live online used-car listings with fixed pricing; contrast to dealer/negotiated pricing | https://www.carvana.com/cars | **REPLACED nhtsa_tsb** (403). Same JS/API caveat as CarMax; re-scrape pending |
| 11 | IIHS safety ratings | Crash test grades (Good/Acceptable/Marginal/Poor) by test category and model year; consistent structure | https://www.iihs.org/ratings | **200 — usable** (~24 KB); verify it isn't JS-rendered shell |
| 12 | AutoTempest aggregated listings | Meta-search across multiple listing sites; broad price/availability comparison for a given make/model | https://www.autotempest.com/results?make=honda&model=cr-v | **REPLACED r_pf_vehicles** (403). Aggregator — most JS-dependent of the three, lowest scrape odds; re-scrape pending |
| 13 | Lemon Squad pre-purchase inspection blog | Explains what a third-party PPI catches vs. what a CarFax report misses; short single-topic posts | https://lemonsquad.com/blog/ | **500** — server error (~3.3 KB); retry before treating as dead |

**Collection summary (first pass + URL fixes):** First scrape returned 4 of 13 usable (200):
CarComplaints, CivicX, NHTSA recalls JSON, IIHS. The 3 sources that returned 404 (KBB,
CarEdge, Consumer Reports) have since had their URLs corrected to current working pages
(see rows above) and are pending a re-scrape to confirm they actually return content rather
than a bot-block or paywall at the new address. Still outstanding: 5 × 403 (Edmunds, three
Reddit endpoints, NHTSA TSBs) and 1 × 500 (Lemon Squad). Workaround plan in Anticipated
Challenges #4.

---

## Chunking Strategy

<!-- How will you split documents into chunks?
     State your chunk size (in tokens or characters), overlap size, and explain why those
     numbers fit the structure of your documents.
     A review-heavy corpus warrants different chunking than a long FAQ. -->

**Length unit:** Chunk sizes below are measured in **tokens**, not characters. This is a
deliberate choice (resolving the earlier mismatch between this section and the Milestone 3
prompt, which was written in characters): the embedding model consumes tokens and truncates
input past its token limit, so chunking in tokens makes "this chunk fits the embedder" a
verifiable fact rather than a character-count estimate. Token counts use the `cl100k_base`
tokenizer via `tiktoken` for budgeting; note that all-MiniLM-L6-v2 uses its own tokenizer,
so these counts are a close approximation, not an exact match — adequate for sizing chunks.

**Chunk size:** 400–500 tokens for prose sources (KBB/Edmunds explainers, CarEdge guides,
r/personalfinance wiki, Lemon Squad blog posts). 150–200 tokens for structured record sources
(NHTSA recalls, NHTSA TSBs, IIHS ratings, CarComplaints entries) — each record is naturally
self-contained and short, so larger chunks would just merge unrelated model years together.
Forum and subreddit threads (r/whatcarshouldibuy, r/MechanicAdvice, CivicX, ToyotaNation)
get chunked at the thread level, not the post level — one chunk per thread, capped at 500
tokens, keeping the question and its top replies together.

**Overlap:** 50 tokens for prose sources. Zero overlap for structured record sources —
a 2019 Civic recall entry and a 2018 Civic recall entry share no context worth bridging,
and overlapping them would confuse retrieval. Forum threads get no overlap either since
each thread is already treated as a single atomic unit.

**Reasoning:** The corpus has three structurally distinct document types that warrant
different strategies:

1. **Prose guides** (KBB, Edmunds, CarEdge, Reddit wiki, Lemon Squad): These are
   mid-length explanations where a key claim — say, "dealer markup is highest in the
   first 30 days on lot" — might span two sentences across a paragraph boundary. A
   50-token overlap ensures that boundary-straddling facts survive chunking intact and
   don't get orphaned in retrieval.

2. **Structured records** (NHTSA recalls/TSBs, IIHS ratings, CarComplaints): Each entry
   is already a discrete, self-contained fact with its own model year, mileage, and
   severity. Chunking one record per chunk and using zero overlap means a query for
   "2018 CR-V recalls" retrieves exactly that record — not a blob that also contains
   three unrelated entries from nearby years.

3. **Forum threads** (subreddits, CivicX, ToyotaNation): The question post and its
   highest-signal replies form one unit of meaning. Splitting mid-thread would separate
   a complaint from its diagnosis. Treating the full thread (question + top 3–5 replies,
   capped at 500 tokens) as one chunk preserves that Q&A structure. Threads longer than
   500 tokens get split after a complete reply, never mid-sentence.

---

## Retrieval Approach

<!-- Which embedding model are you using (e.g., all-MiniLM-L6-v2 via sentence-transformers)?
     How many chunks will you retrieve per query (top-k)?
     If you were deploying this for real users and cost wasn't a constraint, what tradeoffs
     would you weigh in choosing a different embedding model — context length, multilingual
     support, accuracy on domain-specific text, latency? -->

**Embedding model:** all-MiniLM-L6-v2 via sentence-transformers. Fast, free to run locally,
and well-suited for the short-to-medium chunk sizes (150–500 tokens) in this corpus. Its
384-dimension output keeps the vector index small, which matters when storing hundreds of
recall records and forum threads. Note its ~256-token input limit — chunk sizes above are
sized in tokens partly to stay within it so no chunk is silently truncated at embedding time.

**Top-k:** 5 for most queries. Bumped to 8 for broad queries like "what should I inspect
before buying a used Honda CR-V" — those legitimately need chunks from multiple source
types (reliability records, forum threads, PPI guide) to compose a full answer. Kept at
3 for highly specific record lookups like "2018 CR-V open recalls" where precision matters
more than coverage and extra chunks would just add noise.


**Production tradeoff reflection:** all-MiniLM-L6-v2 is the right choice for a course milestone — it runs locally with zero API cost and its limitations (truncation, English-only,
general vocabulary) are manageable at this scale. A production KBB alternative would
most likely land on `text-embedding-3-small` (cost-efficient, long context, good
accuracy) or a fine-tuned `e5-base` if automotive recall data could be used as
training signal.

---

## Evaluation Plan

<!-- List your 5 test questions with their expected correct answers.
     Questions should be specific enough that you can judge whether the system's response
     is right or wrong. "What are good dining halls?" is too vague.
     "What do students say about wait times at [dining hall name] during lunch?" is testable. -->

| # | Question | Expected answer |
|---|----------|-----------------|
| 1 | Does the 2018 Honda CR-V 1.5T have any open NHTSA recalls, and if so what are they? | Yes — the 2018 CR-V 1.5T has a documented recall and associated TSB related to engine oil dilution with gasoline, primarily in cold climates. The system should name the specific recall campaign number and describe the fix (software update / oil change interval adjustment), not just say "there may be recalls." |
| 2 | According to owner forums and CarComplaints, what is the most commonly reported failure on the 2015–2017 Ford F-150 2.7L EcoBoost and at what mileage does it typically appear? | Carbon buildup on intake valves due to direct injection (no port wash); typically reported between 60,000–90,000 miles. The system should cite forum or CarComplaints sources, not generic engine advice, and should include the mileage range. |
| 3 | A dealer is asking $21,500 for a 2020 Toyota RAV4 XLE with 38,000 miles. Is that above or below Edmunds TMV, and what does current market days supply suggest about negotiating room? | Edmunds TMV for a 2020 RAV4 XLE in that mileage range is approximately $22,000–$23,500 (as of corpus collection date), making $21,500 below TMV — a fair-to-good deal. Days supply for RAV4 has historically been low (under 30 days), meaning limited negotiating leverage; the system should flag both the price assessment and the supply context rather than just one. |
| 4 | What does a pre-purchase inspection (PPI) catch that a Carfax report misses? | A PPI catches mechanical and structural issues not reflected in title history: worn brake pads/rotors, frame damage from minor unreported accidents, oil leaks, suspension wear, deferred maintenance, and compression issues. Carfax only shows title events (accidents reported to insurance, odometer fraud, total-loss branding). The system should give at least 3 specific examples from the Lemon Squad or r/personalfinance wiki sources — not a generic answer. |
| 5 | What IIHS safety rating did the 2019 Subaru Forester receive, and which specific test category, if any, was not rated "Good"? | The 2019 Forester received IIHS Top Safety Pick+ with "Good" ratings across most categories. The system should correctly identify the headlight rating for specific trim levels as the one variable result (base trims historically rated "Acceptable" or lower) — this tests whether retrieval pulls the detailed per-trim data rather than just the headline TSP+ label. |

> **Note on eval feasibility after collection:** Q3 depends on Edmunds (403) and Q4 partly on
> Lemon Squad (500) / r/personalfinance (403) — all currently unavailable. Until those
> sources are recovered (see Challenge #4), these questions can't be answered from the
> corpus. Q1 (NHTSA, 200) and Q5 (IIHS, 200) are fully answerable now; Q2 partly (CarComplaints
> 200, but Ford-specific forum data depends on sources not yet collected).

---

## Anticipated Challenges

<!-- What could go wrong? Name at least two specific risks with reasoning.
     Consider: noisy or inconsistent documents, missing source attribution, off-topic
     retrieval, chunks that split key information across boundaries. -->

1. **Model-year bleed across chunk boundaries in forum threads.**
   Forum threads about a specific car model frequently span multiple years in a single
   conversation — an owner will say "I had the same issue on my 2016, but the 2017 fixed
   it with a revised part." If that sentence straddles a chunk boundary, the 2016 complaint
   gets embedded without the 2017 resolution, and the 2017 fix gets embedded without the
   original complaint. The retrieval system then surfaces the complaint chunk in response
   to a query about the 2016 model, presenting a known-fixed problem as an active concern.
   This is especially dangerous for a car-buying tool because a user might pass on a
   perfectly good 2017 vehicle based on a chunk that only captured half the story. The
   mitigation is to enforce chunk splits only at reply boundaries (never mid-reply) and
   to include the thread title — which usually contains the model year — as a metadata
   prefix on every chunk so the LLM has year context even when the body text omits it.

2. **NHTSA and CarComplaints records becoming stale without versioning.**
   Recall statuses change: an open recall gets remedied, a TSB gets superseded, a
   complaint investigation gets closed. If the corpus is collected once and never
   refreshed, the system will confidently cite outdated recall information — telling a
   user an open recall exists on a car they already had serviced, or worse, missing a
   recall that was filed after collection. This is the highest-stakes risk in the corpus
   because recall information has direct safety implications, not just financial ones.
   Unlike forum opinions (which age gracefully — "owners in 2021 reported X" is still
   useful context), a stale "open recall" label is actively misleading. The mitigation
   requires two things: stamping every NHTSA and CarComplaints chunk with a
   `collected_date` metadata field so the LLM can caveat its answer ("as of [date],
   this recall was open — verify at nhtsa.gov before purchase"), and building a
   re-ingestion schedule into the pipeline so these sources are re-scraped at least
   monthly rather than treated as static documents. *(Implemented: `collect.py` stamps
   `collected_date` on every manifest entry and `load.py` carries it onto every chunk.)*

3. **Bonus risk — price data that looks precise but reflects a different market.**
   Edmunds TMV and KBB values are computed from regional transaction data, but the
   corpus captures a snapshot of national averages. A user in Houston asking whether
   $21,500 is fair for a RAV4 is getting an answer calibrated to a national price, not
   the Gulf Coast market, which may run $800–$1,500 higher or lower depending on supply
   at the time of query. The system has no way to signal this gap unless the chunk
   explicitly contains regional breakdowns — which the free-tier Edmunds pages generally
   do not. The risk is that a user accepts a price the system calls "below TMV" when
   local comps actually say it's overpriced, or walks away from a deal the system flags
   as high when it's actually competitive locally. The mitigation is to add a
   disclaimer template to any chunk tagged `source: pricing` reminding the user to
   cross-check against local listings on Marketplace or AutoTempest before negotiating.

4. **Source availability — most planned sources resist scraping (discovered during collection).**
   The first `collect.py` run revealed that only 4 of 13 sources return usable content with a
   plain `requests` call. The failures cluster into three predictable kinds:
   - **Bot blocks (403):** Edmunds and all three Reddit endpoints rejected the request.
     Reddit is the clearest case — all three `.json` URLs returned an identical 189,908-byte
     block page, confirming it's a uniform anti-scraping response, not real content. Reddit
     now requires authenticated API access (OAuth) or the `old.reddit.com` host for
     unauthenticated reads, and even those are unreliable. NHTSA's TSB page also 403'd with a
     432-byte stub.
   - **Moved pages (404):** KBB, CarEdge, and Consumer Reports URLs no longer resolve as
     written in the table. The KBB 404 returned a full ~169 KB styled error page, which is
     why a naive byte-count check would have wrongly treated it as "collected." These need
     their current URLs located.
   - **Server error (500):** Lemon Squad — possibly transient; worth a retry before abandoning.

   **Why this matters for the project:** the working four (CarComplaints, CivicX, NHTSA
   recalls, IIHS) skew toward *records and forums* and away from *pricing/valuation prose*.
   That directly undercuts the original KBB-replacement premise (valuation) while leaving the
   reliability/recall/safety angle well-supported. Several eval questions (Q3 pricing, Q4 PPI)
   can't be answered until their sources are recovered.

   **Mitigation plan, in priority order:**
   (a) Fix the three 404s first — these are likely just moved pages and the cheapest wins;
       locate current URLs and update the table.
   (b) Recover Reddit via the official API or `old.reddit.com`, since forum data underpins
       the model-year "gotchas" that differentiate this guide; if that proves too costly,
       substitute the marque forums (CivicX already works, add ToyotaNation) which cover the
       same Q&A signal without the auth wall.
   (c) For Edmunds/CR pricing prose, fall back to a headless browser (Playwright) or accept
       the gap and narrow the project's stated scope toward reliability/recalls rather than
       valuation — and say so explicitly rather than claiming valuation coverage the corpus
       can't back.
   (d) Retry Lemon Squad once; if it stays down, lean on the r/personalfinance wiki (also
       Reddit-blocked, so contingent on (b)) for PPI content.

   **Process note:** a 200 status alone does not guarantee usable content — a page can return
   200 with a captcha or a JS shell. The next step is to run `load.py` over the four working
   sources and treat any `[warn] empty after cleaning` as a hidden failure on top of the
   status-code failures above.

   **Final corpus outcome (after cleaning + replacement attempts):** The pipeline ended with
   **39 usable chunks**. The CarMax / Carvana / AutoTempest inventory replacements all failed
   (403 hard-blocks and a JS-shell 200) — confirming that major used-car retailers actively
   block scraping, a real finding about the domain rather than a pipeline bug. The substantive
   corpus is concentrated in four strong sources: NHTSA recalls (11 chunks), Consumer Reports
   reliability (9), CivicX owner forum (7), and CarEdge market-day-supply (4). KBB, IIHS,
   CarComplaints, and Edmunds each survived as a single thin chunk. Net effect on scope: the
   guide is well-supported on **recalls, reliability, and safety**, but **thin on live
   valuation/pricing** because every pricing-data source (Edmunds, KBB depth, the three
   retailers) was either blocked or paywalled. The honest framing for this project is a
   "reliability & ownership-risk research assistant" rather than a live-pricing KBB
   replacement. End-to-end retrieval and grounded generation were verified working: the
   2018 CR-V recall query returned specific, correctly-cited NHTSA recalls, and out-of-corpus
   queries (e.g. "best German V8") were correctly declined rather than hallucinated.

---

## Architecture

<!-- Draw a diagram of your pipeline showing the five stages:
     Document Ingestion → Chunking → Embedding + Vector Store → Retrieval → Generation
     Label each stage with the tool or library you're using.
     You can use ASCII art, a Mermaid diagram, or embed a sketch as an image.
     You'll use this diagram as context when prompting AI tools to implement each stage. -->
     ```mermaid
     flowchart TD
          A["Document ingestion\n──────────────\nrequests · BeautifulSoup · pdfplumber\n(HTML, PDFs, JSON from 13 sources)\ncollect.py saves raw bytes + manifest.jsonl"]
          B["Chunking\n──────────────\nLangChain RecursiveCharacterTextSplitter\n400–500 tok prose · 150–200 tok records\n50 tok overlap (prose) · 0 (records)\nload.py cleans by type + attaches metadata"]
          C["Embedding + vector store\n──────────────\nall-MiniLM-L6-v2 (sentence-transformers)\nChromaDB persisted · 384-dim vectors\n+ metadata: source, model_year, collected_date"]
          D["Retrieval\n──────────────\nChromaDB cosine similarity\ntop-k 5 (default) · 8 (broad) · 3 (precise)"]
          E["Generation\n──────────────\nGroq llama-3.3-70b-versatile (OpenAI-compatible)\nchunks + query → grounded answer\nwith source citations + stale-data flagging"]

          A --> B --> C --> D --> E
     ```

---

## AI Tool Plan

<!-- For each part of the pipeline below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, which requirements)
     - What you expect it to produce
     - How you'll verify the output matches your spec

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Chunking Strategy section and ask it to implement chunk_text()
     with my specified chunk size and overlap" is a plan. -->

**Milestone 3 — Ingestion and chunking:**

Tool: Claude

Input: I'll paste in (1) my Sources table with all 13 URLs and source types, (2) my
Chunking Strategy section specifying the three document categories and their chunk
sizes (400–500 tok prose, 150–200 tok records, thread-level forum), and (3) this
exact prompt:

  "Implement two Python functions: fetch_document(url) that uses requests and
  BeautifulSoup to return cleaned plain text from a URL, and chunk_text(text,
  source_type) that takes a string and one of ['prose', 'record', 'forum'] and
  returns a list of chunk dicts — each with keys 'text', 'source_type', and
  'char_count'. Use LangChain's RecursiveCharacterTextSplitter. For 'prose':
  chunk_size=1800, chunk_overlap=200. For 'record': chunk_size=700,
  chunk_overlap=0. For 'forum': chunk_size=1800, chunk_overlap=0, split only
  at double newlines. Return no chunk shorter than 100 characters."

> **Implementation note (updated):** the delivered code chunks in **tokens**, not
> characters, and splits records/forums **structurally** (one record/thread per chunk)
> before length-capping — a plain character splitter can't honor "one record per chunk."
> Collection was also split into a separate `collect.py` (raw bytes + manifest) ahead of
> `load.py` (clean + chunk), so cleaning can be re-run without re-scraping. See Chunking
> Strategy for the token rationale.

Expected output: A working ingest.py with both functions, imports, and a
__main__ block that loops over a hardcoded list of 3 test URLs (one of each
source type) and prints chunk counts.

Verification: I'll run it against all three source types and manually inspect
5 random chunks per type — checking that (a) prose chunks don't split mid-
sentence, (b) record chunks contain exactly one NHTSA or CarComplaints entry
each, and (c) forum chunks don't split mid-reply. I'll also assert that no
chunk's char_count falls below 100 and none exceeds 2200 characters.

---

**Milestone 4 — Embedding and retrieval:**

Tool: Claude

Input: I'll paste in (1) my Embedding Model section specifying all-MiniLM-L6-v2
and ChromaDB, (2) the chunk dict schema produced by Milestone 3 (keys: 'text',
'source_type', 'char_count'), and (3) this exact prompt:

  "Implement two Python functions using the output of ingest.py:
  build_index(chunks, persist_path) that takes a list of chunk dicts, embeds
  each with sentence-transformers all-MiniLM-L6-v2, and stores them in a
  persisted ChromaDB collection at persist_path with metadata fields
  source_type and char_count. And retrieve(query, persist_path, k) that
  loads the persisted collection, embeds the query string, and returns the
  top-k most similar chunks as a list of dicts with keys 'text',
  'source_type', and 'distance'. Default k=5."

Expected output: A working retrieval.py with both functions, a requirements
block listing exact package versions, and a __main__ block that builds an
index from 20 sample chunks and runs 3 test queries printing results.

Verification: I'll run all 5 evaluation questions from my Test Questions
section through retrieve() with k=5 and manually check that at least 3 of
the 5 returned chunks per question are topically relevant. I'll also verify
that build_index() is idempotent — running it twice on the same chunks
should not duplicate entries in the collection — by checking
collection.count() before and after a second build call.

---

**Milestone 5 — Generation and interface:**

Tool: Claude

Input: I'll paste in (1) my 5 test questions with expected answers, (2) the
retrieve() function signature from Milestone 4, (3) my Risk section describing
the stale-data and model-year-bleed failure modes, and (4) this exact prompt:

  "Implement a Python function answer(query, persist_path, k=5) that calls
  retrieve() to fetch the top-k chunks, builds a prompt that includes: (a)
  a system instruction telling the model it is a used car research assistant
  that must cite sources and flag any chunk whose metadata collected_date is
  more than 90 days old, (b) the retrieved chunks each labeled with their
  source_type, and (c) the user's query. Call the Groq API (OpenAI-compatible)
  with llama-3.3-70b-versatile and return the model's response string. Then
  implement a minimal CLI loop: print a prompt, read a query, print the
  answer, repeat until the user types 'quit'."

> **Implementation note (updated):** the generation LLM is Groq's
> `llama-3.3-70b-versatile` (free tier, OpenAI-compatible API), not Anthropic's
> Claude as originally planned — a deliberate substitution for cost. The `groq`
> Python package is used with the key in `.env` as `GROQ_API_KEY`. The prompt
> template labels each chunk with source, source_type, and model_year, and
> marks chunks older than 90 days `[STALE]`; the system instruction enforces
> answering only from context, citing sources, not generalizing across model
> years, and caveating stale recall data. ("Tool: Claude" above refers to
> Claude as the coding assistant used to write the pipeline, separate from the
> runtime LLM.)

Expected output: A working generate.py with answer(), a CLI loop, and
inline comments explaining how the prompt template addresses the two risks
named in my planning doc (stale recall data and model-year bleed).

Verification: I'll run all 5 evaluation questions through the full CLI and
score each answer against my expected answers table — pass requires the
answer to contain the specific data point called out in the Expected Answer
column (e.g. the recall campaign description for Q1, the mileage range for
Q2). I'll also deliberately submit a query with no relevant chunks in the
index and confirm the model says it cannot find relevant information rather
than hallucinating an answer.