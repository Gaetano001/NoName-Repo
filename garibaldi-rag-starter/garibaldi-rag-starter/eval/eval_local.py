"""eval_local.py — scoring locale di una submission contro le annotazioni.

Replica in locale le metriche di retrieval della piattaforma (Recall@5,
Precision@up-to-5, Hit@5, rank quality) e fa i check "cheap" sulla generation
(required_facts, forbidden_claims, abstention) per l'error analysis rapida
durante i build sprint.

Non sostituisce lo scoring ufficiale (Faithfulness/judge restano privati):
serve a capire in pochi secondi dove si perdono punti.

Uso:
  python eval/eval_local.py \
    --submission outputs/submission_sample.json \
    --annotations eval/sample_annotations.json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def eval_question(answer: dict, annotation: dict) -> dict:
    relevant = set(annotation.get("relevant_sources", []))
    acceptable = set(annotation.get("acceptable_sources", []))
    distractors = set(annotation.get("distractor_sources", []))
    harmful = set(annotation.get("harmful_if_unqualified", []))
    good = relevant | acceptable

    retrieved = [c["document_id"] for c in answer.get("contexts", [])]
    retrieved_set = set(retrieved)

    recall = len(relevant & retrieved_set) / len(relevant) if relevant else 1.0
    precision = len(good & retrieved_set) / len(retrieved_set) if retrieved_set else 0.0
    hit = bool(relevant & retrieved_set) if relevant else True

    # rank quality: reciprocal rank della prima fonte relevant
    rr = 0.0
    for i, doc in enumerate(retrieved, start=1):
        if doc in relevant:
            rr = 1.0 / i
            break

    text = _norm(answer.get("answer", ""))

    # required_facts: lista di gruppi; ogni gruppo è una lista di alternative accettate
    facts = annotation.get("required_facts", [])
    facts_hit = sum(1 for group in facts if any(_norm(alt) in text for alt in group))

    forbidden_hits = [
        claim for claim in annotation.get("forbidden_claims", []) if _norm(claim) in text
    ]

    abst_markers = ("non lo so", "non e possibile", "le fonti non", "le carte non",
                    "le evidenze non", "insufficien", "non consente", "non bastano",
                    "non provano", "non e provato", "nessuna prova")
    abstained = any(m in text for m in abst_markers)
    requires_abstention = annotation.get("requires_abstention", False)

    return {
        "question_id": answer["question_id"],
        "recall@5": round(recall, 3),
        "precision": round(precision, 3),
        "hit@5": hit,
        "rank_rr": round(rr, 3),
        "required_facts": f"{facts_hit}/{len(facts)}",
        "facts_ok": facts_hit == len(facts),
        "forbidden_claims_hit": forbidden_hits,
        "requires_abstention": requires_abstention,
        "abstained": abstained,
        "abstention_ok": abstained == requires_abstention or (abstained and not requires_abstention and not facts),
        "distractors_retrieved": sorted(retrieved_set & distractors),
        "harmful_retrieved": sorted(retrieved_set & harmful),
        "retrieved": retrieved,
        "expected_relevant": sorted(relevant),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval locale submission vs annotations")
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true", help="mostra anche i dettagli per domanda OK")
    args = parser.parse_args()

    submission = json.loads(args.submission.read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    ann_by_id = {row["question_id"]: row for row in annotations["questions"]}

    rows = []
    for answer in submission["answers"]:
        annotation = ann_by_id.get(answer["question_id"])
        if annotation is None:
            print(f"!! {answer['question_id']}: nessuna annotazione, salto")
            continue
        rows.append(eval_question(answer, annotation))

    if not rows:
        print("Nessuna domanda valutabile.")
        return 1

    n = len(rows)
    mean = lambda key: sum(r[key] for r in rows) / n  # noqa: E731
    print(f"\n===== EVAL LOCALE — {n} domande =====")
    print(f"Recall@5 medio:    {mean('recall@5'):.3f}   (piattaforma: 20 pt)")
    print(f"Precision media:   {mean('precision'):.3f}   (piattaforma: 10 pt)")
    print(f"Hit@5:             {sum(r['hit@5'] for r in rows)}/{n}      (piattaforma: 5 pt)")
    print(f"Rank RR medio:     {mean('rank_rr'):.3f}   (proxy rank quality: 5 pt)")
    print(f"Required facts OK: {sum(r['facts_ok'] for r in rows)}/{n}")
    print(f"Abstention OK:     {sum(r['abstention_ok'] for r in rows)}/{n}")
    bad_forbidden = [r for r in rows if r["forbidden_claims_hit"]]
    if bad_forbidden:
        print(f"⚠ FORBIDDEN CLAIMS in {len(bad_forbidden)} risposte!")

    print("\n--- Dettaglio problemi ---")
    clean = True
    for r in rows:
        problems = []
        if r["recall@5"] < 1.0:
            missing = [d for d in r["expected_relevant"] if d not in r["retrieved"]]
            problems.append(f"recall {r['recall@5']} (mancano: {missing})")
        if r["precision"] < 1.0:
            extra = [d for d in dict.fromkeys(r["retrieved"]) if d not in r["expected_relevant"]]
            problems.append(f"precision {r['precision']} (fuori target: {extra})")
        if r["distractors_retrieved"]:
            problems.append(f"distrattori recuperati: {r['distractors_retrieved']}")
        if r["harmful_retrieved"]:
            problems.append(f"fonti harmful (da qualificare!): {r['harmful_retrieved']}")
        if not r["facts_ok"]:
            problems.append(f"required_facts {r['required_facts']}")
        if r["forbidden_claims_hit"]:
            problems.append(f"FORBIDDEN: {r['forbidden_claims_hit']}")
        if r["requires_abstention"] and not r["abstained"]:
            problems.append("doveva ASTENERSI/segnalare insufficienza e non l'ha fatto")
        if problems:
            clean = False
            print(f"\n{r['question_id']}:")
            for p in problems:
                print(f"  - {p}")
            print(f"  retrieved: {r['retrieved']}")
        elif args.verbose:
            print(f"\n{r['question_id']}: OK  retrieved={r['retrieved']}")
    if clean:
        print("nessun problema rilevato ✔")

    # telemetria
    lat = [a["telemetry"]["latency_ms"] for a in submission["answers"]]
    cost = [a["telemetry"]["declared_cost_eur"] for a in submission["answers"]]
    print(f"\n--- Telemetria ---")
    print(f"Latenza: media {sum(lat)/len(lat)/1000:.2f}s, max {max(lat)/1000:.2f}s  (soglie: 4s=7pt, 8s=5pt, 15s=3pt)")
    print(f"Costo medio dichiarato: €{sum(cost)/len(cost):.5f}/domanda  (soglie: 0.005=8pt, 0.02=6pt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
