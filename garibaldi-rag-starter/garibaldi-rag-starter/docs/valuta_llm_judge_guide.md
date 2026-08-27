# 📈 Guida al Simulatore Locale LLM-as-a-Judge (`valuta_llm_judge.py`)

Questo script è un sistema di valutazione offline progettato per simulare il comportamento del correttore ufficiale dell'hackathon. Analizza il file JSON di sottomissione generato dal RAG e lo confronta con il file delle annotazioni corrette (`annotations_private_round1.json`), calcolando in locale le metriche del corso senza rigenerare le risposte (risparmiando tempo e crediti API).

---

## 📊 Le Metriche Calcolate

1. **Recall@5** (Ricerca): Frazione di volte in cui il RAG ha inserito almeno un documento corretto tra i 5 contesti inviati all'LLM.
2. **MRR (Mean Reciprocal Rank)** (Ricerca): Valuta la qualità del posizionamento dei documenti nel contesto. Un punteggio di `1.0` indica che la fonte primaria era sempre al primo posto.
3. **Faithfulness** (LLM Judge): Misura la fedeltà al contesto usando `gpt-4o-mini` come giudice. Controlla se l'AI ha inventato informazioni non presenti nei documenti (`1.0` = nessuna allucinazione, `0.0` = presenza di allucinazioni).
4. **Relevancy** (LLM Judge): Misura la pertinenza della risposta usando `gpt-4o-mini` come giudice. Controlla se l'AI ha effettivamente risposto al quesito dell'utente (`1.0` = pertinente, `0.0` = fuori tema).
5. **Latenza p95**: Il tempo di risposta (in secondi) al 95° percentile delle query.
6. **Costo medio**: Stima in Euro del costo medio per ogni query calcolata dai token consumati.

---

## 🛠️ Come si usa da Terminale

Lo script è flessibile e accetta il file di sottomissione da valutare tramite il parametro `--submission`.

### 1. Valutare la prima prova (Round 1):
```bash
c:\Users\cultr\OneDrive\Desktop\corsoai\.venv\Scripts\python.exe scripts/valuta_llm_judge.py --submission outputs/submission_round_1.json
```

### 2. Valutare il test di ingestione (Act 3 + Act 4):
```bash
c:\Users\cultr\OneDrive\Desktop\corsoai\.venv\Scripts\python.exe scripts/valuta_llm_judge.py --submission outputs/test_ingest.json
```

---

## 📂 Dove trovare i Risultati salvati

Ad ogni esecuzione, oltre a stampare la sintesi sul terminale, lo script crea o aggiorna un report dettagliato in formato Markdown con l'analisi domanda-per-domanda:
*   `outputs/feedback/llm_judge_submission_round_1.md`
*   `outputs/feedback/llm_judge_test_ingest.md`
