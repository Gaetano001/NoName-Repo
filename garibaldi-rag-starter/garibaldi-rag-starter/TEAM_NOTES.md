# Team notes

Diario di lavoro del team. **Non è documentazione della baseline** e non entra nello score tecnico /90.

---

## Architettura / scelte

1. **Integrazione Dati (Act 3 e Act 4):**
   * Abbiamo implementato un sistema di unione dei manifest (`release_manifest.json` dell'Act 3 e Act 4 fonduto nel `manifest.json` principale) che consente al RAG di indicizzare ed effettuare ricerche su tutto l'archivio storico sbloccato fino a questo momento (Atti 1, 2, 3 e 4).
   * Abbiamo pre-popolato la collezione del database Qdrant con tutti i 4 atti per azzerare la latenza di caricamento e Docling all'avvio delle nuove prove.

2. **Retrieval e Query Expansion:**
   * Utilizzo della logica di **Query Expansion** (multi-query) per le domande generiche o trasversali. L'LLM genera tre sotto-domande (Persone, Logistica, Documenti) per massimizzare la *Recall*.
   * Utilizzo del sistema di **Smart Context Selection** per prioritizzare i frammenti di fonti esplicitamente nominate nella domanda (migliorando la *Rank Quality* ed evitando di sprecare token con file di consultazione generici).

3. **Prompting (Historical Reasoning):**
   * Sostituzione del prompt di `GROUNDING` di base con un prompt avanzato che insegna all'LLM ad agire come un **Professore d'Archivio**. Il prompt impone la massima precisione sui dettagli fisici e gestisce l'incertezza storica (distinguendo tra indizi, prove dirette e propaganda) per evitare risposte vaghe o rifiuti ciechi.

---

## Fallimenti e fix

| Round / fonte | Caso | Sintomo | Causa | Fix | Esito |
| --- | --- | --- | --- | --- | --- |
| **Round 1 (Q006)** | Dettagli sulle anomalie rilevate dal funzionario borbonico. | Punteggio basso (24.9/35). La risposta era vaga ed ometteva i dettagli presenti nel testo. | Il prompt originale era troppo generico e permetteva all'LLM di riassumere eccessivamente. | Modificato il prompt di `GROUNDING` imponendo di elencare obbligatoriamente i fatti fisici specifici (es. cancelli aperti, carri, pattuglie). | Risolto (le risposte ora contengono l'elenco completo dei fatti). |
| **Round 1 (Q007)** | Presenza di un accordo formale dei notabili prima dello sbarco. | Punteggio basso (18.5/35). Il RAG ha risposto con un secco e vuoto "Non lo so". | La regola di grounding diceva di arrendersi con "Non lo so" se non c'era prova certa, ma l'archivio conteneva indizi logistici rilevanti. | Istruito il prompt a spiegare la *mancanza di prove formali* (es. assenza di patti o firme) pur elencando gli indizi storici di contorno. | Risolto (l'LLM ora fa astensione motivata spiegando lo stato dell'archivio). |

---

## Eval locale / gate pre-submission

*   Abbiamo sviluppato uno script di **LLM-as-a-Judge locale** (`scripts/valuta_llm_judge.py`) che replica fedelmente il meccanismo della funzione `valuta` spiegato a lezione.
*   Confronta il file JSON di sottomissione con le risposte ideali delle annotazioni e interroga GPT-4o-mini per assegnare i voti di **Faithfulness** (Fedeltà) e **Relevancy** (Pertinenza).
*   Salva i risultati dettagliati della valutazione in file Markdown dedicati sotto `outputs/feedback/` (es. `llm_judge_submission_round_1.md`) per consentirci di misurare i miglioramenti quantitativi prima di effettuare il caricamento sulla piattaforma.

---

## Debito consapevole prima della Gold

*   **Docling su CPU:** La conversione dei PDF scansionati e delle immagini tramite OCR con Docling su CPU locale è molto lenta. Abbiamo scelto di mitigare questo debito effettuando l'ingestione totale una tantum e riutilizzando il database locale per i round ufficiali, evitando la compilazione con `--rebuild` durante i round a tempo.
