# Guida partecipanti

## Obiettivo

Costruire una pipeline RAG robusta su un archivio narrativo ambientato nella Sicilia del 1860. Il compito non è indovinare la storia generale: è recuperare le fonti corrette, distinguere prova e indizio, rispondere soltanto con evidenze verificabili e dichiarare l'incertezza quando l'archivio non basta.

## Progressione della giornata

Al kickoff ogni team scarica dalla dashboard: regolamento (`participant_rules`) e lo **starter RAG** della giornata (già con Act 1–2). Dopo Round 1 viene pubblicato Act 3. Tra la fine del round e il pomeriggio arrivano Act 4 e Act 5, con scansioni, mappe annotate, propaganda, versioni aggiornate e fonti contestate. La Gold Run usa lo stesso archivio completo, ma domande nuove e senza feedback.

## Pipeline minima (baseline)

La starter espone un solo entrypoint: `baseline_naive_rag.py`.

1. Ingerire i file del `manifest.json` con Docling → `RecursiveSplitter` → embedding OpenAI → Qdrant.
2. Per mappe/scan: descrizione o OCR; in submission conta il `document_id` citato e il testo passato al modello.
3. Recuperare top-5 denso (taglio hard, niente rerank nella baseline).
4. Generare una risposta fedele e prudente (grounding: solo dal contesto, altrimenti «Non lo so»).
5. Registrare latenza wall-clock, costo autodichiarato in EUR per domanda, e provider/modello/token.
6. Produrre `submission.json` conforme allo schema.

I team possono sostituire o estendere la baseline (hybrid, rerank, ecc.): non è richiesta dalla baseline ufficiale.

## Regola dei contesti

`contexts` contiene le evidenze finali passate al generatore (max 5), nello stesso ordine del top-k. Non inventare contesti né ricostruirli dopo la generazione. Il `content` viene confrontato con il corpus: un contesto non supportato azzera la Faithfulness della domanda.

## Schema di submission

Il file contiene:

- `schema_version` (`"1.0"`);
- `round_id`;
- per ogni domanda: `question_id`, `question` (testo), `answer`, fino a cinque `contexts` (`rank`, `document_id`, `content`), `telemetry`.

Telemetria: `latency_ms`, `declared_cost_eur`, `model_calls`.

Esempio e schema formale sono nello starter: `eval/submission.example.json` e `eval/submission.schema.json` (allineati alla piattaforma).

## Validazione e conferma

La validazione sul sito non consuma il tentativo. Solo il pulsante **Conferma irreversibile** crea la submission ufficiale. Una sola submission ufficiale per round. In locale: `python baseline_naive_rag.py --validate-only ...`.

## Evaluation

Lo scoring ufficiale è sulla piattaforma (retrieval + generation + latency/cost). Sul sample potete confrontare a mano i `document_id` con `eval/sample_annotations.json`. Generation e judge restano privati fino al feedback pack.

## Historical Review

Dalle 16:00 alle 16:30 ogni team prepara le slide mentre viene completata l'evaluation della Gold Run. La presentazione finale dura al massimo 10 minuti e deve coprire: architettura RAG e relative motivazioni; problemi affrontati e soluzioni; evaluation svolta, metodo e risultati; Historical Review sulla domanda assegnata (massimo 5 minuti). La giuria registra la parte storica, ne produce la trascrizione e la valuta con un giudice LLM (Professore d'Archivio). Il punteggio (fino a 10) si somma allo score della Gold Run. Non è richiesta una consegna JSON di Historical Review.

## Consegna repository

Codice, test, README, `TEAM_NOTES.md` (o equivalente), `outputs/submission_gold.json`. URL GitHub sulla piattaforma, non nel JSON.

## Supporto

Canale ufficiale: **Microsoft Teams** (annunci orari e incidenti). I materiali (starter, regole, act, domande) si scaricano dalla **dashboard della piattaforma**. Non chiedete annotazioni private o soluzioni: arrivano solo nel feedback pack dopo la pubblicazione del round.
