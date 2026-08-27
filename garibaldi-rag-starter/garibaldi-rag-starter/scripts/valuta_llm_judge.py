import json
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from datapizza.clients.openai import OpenAIClient

def judge_faithfulness(llm, contesto, risposta) -> float:
    prompt = (
        "Sei un giudice di controllo qualità per sistemi RAG. Il tuo compito è valutare se la RISPOSTA "
        "è supportata al 100% dal CONTESTO fornito. Non deve contenere alcuna informazione aggiuntiva o inventata.\n\n"
        f"CONTESTO:\n{contesto}\n\n"
        f"RISPOSTA:\n{risposta}\n\n"
        "Rispondi esclusivamente con il numero 1 (se la risposta è totalmente fedele) o con il numero 0 "
        "(se contiene allucinazioni o non è supportata). Non aggiungere altre parole."
    )
    res = llm.invoke(input=prompt, system_prompt="Rispondi solo con 1 o 0.")
    out = (getattr(res, "text", None) or str(res)).strip()
    return 1.0 if "1" in out else 0.0

def judge_relevancy(llm, domanda, risposta) -> float:
    prompt = (
        "Sei un giudice. Valuta se la RISPOSTA risponde in modo pertinente alla DOMANDA fornita, "
        "senza andare fuori tema.\n\n"
        f"DOMANDA:\n{domanda}\n\n"
        f"RISPOSTA:\n{risposta}\n\n"
        "Rispondi esclusivamente con il numero 1 (se risponde alla domanda) o con il numero 0 "
        "(se è fuori tema o incompleta). Non aggiungere altre parole."
    )
    res = llm.invoke(input=prompt, system_prompt="Rispondi solo con 1 o 0.")
    out = (getattr(res, "text", None) or str(res)).strip()
    return 1.0 if "1" in out else 0.0

def valuta_submission(submission_path: Path, annotations_path: Path, llm):
    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    
    anno_dict = {q["question_id"]: q for q in annotations["questions"]}
    
    recalls = []
    mrrs = []
    tempi = []
    costi = []
    faith_scores = []
    relev_scores = []
    dettagli = []
    
    print("Avvio valutazione risposte con LLM-as-a-Judge...")
    for index, ans in enumerate(submission["answers"], start=1):
        q_id = ans["question_id"]
        if q_id not in anno_dict:
            continue
            
        gold = anno_dict[q_id]
        
        # 1. Retrieval
        retrieved_ids = [c["document_id"] for c in ans["contexts"]]
        correct_sources = gold["relevant_sources"]
        
        has_recall = False
        rank = None
        if correct_sources:
            has_recall = any(src in retrieved_ids for src in correct_sources)
            recalls.append(1.0 if has_recall else 0.0)
            
            rank = next((i + 1 for i, doc_id in enumerate(retrieved_ids) if doc_id in correct_sources), None)
            mrrs.append((1.0 / rank) if rank else 0.0)
        
        # 2. Tempi e Costi
        latency_s = ans["telemetry"]["latency_ms"] / 1000.0
        tempi.append(latency_s)
        costi.append(ans["telemetry"].get("declared_cost_eur", 0.0))
        
        # 3. Giudici LLM
        risposta_testo = ans["answer"]
        contesto_testo = "\n\n".join(f"[{c['document_id']}]\n{c['content']}" for c in ans["contexts"])
        
        f_score = judge_faithfulness(llm, contesto_testo, risposta_testo)
        r_score = judge_relevancy(llm, ans["question"], risposta_testo)
        
        faith_scores.append(f_score)
        relev_scores.append(r_score)
        
        dettagli.append({
            "question_id": q_id,
            "question": ans["question"],
            "answer": risposta_testo,
            "expected_answer": gold.get("expected_answer", ""),
            "retrieval_ok": "✅" if has_recall else "❌",
            "rank": rank if rank else "-",
            "faithfulness": "✅ 1.0 (Fedele)" if f_score == 1.0 else "❌ 0.0 (Allucinata/Non supportata)",
            "relevancy": "✅ 1.0 (Pertinente)" if r_score == 1.0 else "❌ 0.0 (Non pertinente)"
        })
        
        print(f"[{index}/8] Domanda {q_id}: Faithfulness={f_score} | Relevancy={r_score}")
        
    tempi.sort()
    p95_latency = tempi[min(len(tempi) - 1, int(0.95 * (len(tempi) - 1)))]
    
    pagella = {
        'recall@5':           round(sum(recalls) / len(recalls), 4) if recalls else 1.0,
        'MRR':                round(sum(mrrs) / len(mrrs), 4) if mrrs else 1.0,
        'faithfulness':       round(sum(faith_scores) / len(faith_scores), 4),
        'relevancy':          round(sum(relev_scores) / len(relev_scores), 4),
        'latency_p95_s':      round(p95_latency, 4),
        'cost_per_query_eur': round(sum(costi) / len(costi), 6),
    }
    
    return pagella, dettagli

def main():
    parser = argparse.ArgumentParser(description="Valuta una sottomissione con LLM-as-a-Judge.")
    parser.add_argument("--submission", type=Path, default=Path("outputs/submission_round_1.json"))
    parser.add_argument("--annotations", type=Path, default=Path("../../annotations_private_round1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/feedback"))
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
    
    if not api_key:
        print("[ERRORE] Chiave API OPENAI_API_KEY mancante nel .env")
        return
        
    llm = OpenAIClient(api_key=api_key, model=model)
    
    pagella, dettagli = valuta_submission(args.submission, args.annotations, llm)
    
    # Stampa a schermo
    print("\n=== PAGELLA FINALE (LLM-as-a-Judge) ===")
    for metrica, voto in pagella.items():
        print(f"   {metrica:25s} -> {voto}")
        
    # Salva il report in markdown
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_file = args.output_dir / f"llm_judge_{args.submission.stem}.md"
    
    report_content = []
    report_content.append(f"# Report LLM-as-a-Judge - `{args.submission.name}`\n")
    report_content.append("## 📊 Pagella Riassuntiva\n")
    report_content.append("| Metrica | Valore | Dettaglio |")
    report_content.append("| --- | --- | --- |")
    report_content.append(f"| **Recall@5** | `{pagella['recall@5']:.4f}` | Percentuale di fonti corrette trovate nei top 5 |")
    report_content.append(f"| **MRR (Mean Reciprocal Rank)** | `{pagella['MRR']:.4f}` | Qualità di posizionamento delle fonti nei contesti |")
    report_content.append(f"| **Faithfulness** | `{pagella['faithfulness']:.4f}` | Livello di fedeltà al contesto (0 = allucinazioni, 1 = perfetto) |")
    report_content.append(f"| **Relevancy** | `{pagella['relevancy']:.4f}` | Grado di risposta pertinente alla domanda |")
    report_content.append(f"| **Latenza p95** | `{pagella['latency_p95_s']:.3f} s` | Tempo di risposta per query al 95° percentile |")
    report_content.append(f"| **Costo medio per query** | € {pagella['cost_per_query_eur']:.6f} | Costo stimato dell'interrogazione dell'LLM |")
    report_content.append("\n")
    
    report_content.append("## 📋 Esito per singola domanda\n")
    report_content.append("| Domanda | Retrieval | Pos. Fonte | Faithfulness | Relevancy |")
    report_content.append("| --- | --- | --- | --- | --- |")
    for det in dettagli:
        report_content.append(f"| `{det['question_id']}` | {det['retrieval_ok']} | `{det['rank']}` | {det['faithfulness']} | {det['relevancy']} |")
    report_content.append("\n")
    
    report_content.append("## 🔍 Dettaglio delle risposte analizzate\n")
    for det in dettagli:
        report_content.append(f"### Domanda `{det['question_id']}`")
        report_content.append(f"**Testo:** {det['question']}\n")
        report_content.append(f"**Risposta del tuo RAG:**\n> {det['answer']}\n")
        report_content.append(f"**Risposta attesa (Soluzione):**\n> {det['expected_answer']}\n")
        report_content.append(f"- **Faithfulness Judge:** {det['faithfulness']}")
        report_content.append(f"- **Relevancy Judge:** {det['relevancy']}")
        report_content.append("\n---\n")
        
    report_file.write_text("\n".join(report_content), encoding="utf-8")
    print(f"\n[OK] Report LLM-as-a-Judge salvato in: {report_file}")

if __name__ == "__main__":
    main()
