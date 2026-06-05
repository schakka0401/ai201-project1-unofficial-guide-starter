"""
eval_capture.py — print retrieved chunks (source + distance) for each of the
5 evaluation questions, so the README eval report can document WHICH chunks
were retrieved (not just the final answer).

Run:  python eval_capture.py
"""

from retrieval import retrieve

EVAL_QUESTIONS = [
    ("Q1", "Does the 2018 Honda CR-V have any open recalls, and what are they?", 3),
    ("Q2", "According to owner forums and CarComplaints, what is the most commonly "
           "reported failure on the 2015-2017 Ford F-150 2.7L EcoBoost, and at what "
           "mileage does it appear?", 5),
    ("Q3", "A dealer is asking $21,500 for a 2020 Toyota RAV4 XLE with 38,000 miles. "
           "Is that above or below Edmunds TMV, and what does market days supply "
           "suggest about negotiating room?", 5),
    ("Q4", "What does a pre-purchase inspection catch that a Carfax report misses?", 5),
    ("Q5", "What IIHS safety rating did the 2019 Subaru Forester receive, and which "
           "test category, if any, was not rated Good?", 5),
]

for qid, q, k in EVAL_QUESTIONS:
    print(f"\n{'='*70}\n{qid} (k={k}): {q}\n{'='*70}")
    results = retrieve(q, k=k)
    if not results:
        print("  (no chunks retrieved)")
        continue
    for i, r in enumerate(results, 1):
        snippet = r["text"][:90].replace("\n", " ")
        print(f"  {i}. [dist {r['distance']:.3f}] source={r['source']:<16} "
              f"type={r['source_type']}")
        print(f"     {snippet}...")