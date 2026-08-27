# Scoring, soglie e fairness

## Punteggio totale

- Retrieval: 40
  - Recall@5: 20
  - Precision fino a 5: 10
  - Hit@5: 5
  - qualità del ranking: 5
- Generation: 35
  - Faithfulness: 18
  - Answer Correctness: 12
  - Historical Reasoning: 5
- Latency: 7
- Cost: 8
- Historical Review: 10

Totale: 100.

## Latenza

La latenza dichiarata è wall-clock end-to-end per domanda. Soglie:

- ≤4 s: 7;
- ≤8 s: 5;
- ≤15 s: 3;
- ≤25 s: 1;
- >25 s: 0.

## Costo

I modelli sono liberi. Il team autodichiara il costo in EUR per domanda in `telemetry.declared_cost_eur` (oltre a `latency_ms` e, a fini di audit, `model_calls`). La piattaforma applica le fasce sul valor medio dichiarato. Soglie di riferimento:

- ≤€0,005: 8;
- ≤€0,02: 6;
- ≤€0,05: 3;
- ≤€0,10: 1;
- >€0,10: 0.

Dichiarazioni palesemente implausibili possono essere moderate dalla giuria.

## Antifabrication

Ogni contesto caricato è confrontato con il corpus tramite supporto testuale normalizzato. Se il contenuto non è riconducibile al documento indicato, la domanda viene segnalata e Faithfulness è zero. L'algoritmo è volutamente conservativo: casi di OCR difficile devono essere moderati e documentati.

## Tie-breaker

Ordine consigliato:

1. totale;
2. technical score;
3. Retrieval;
4. Generation;
5. Historical Review;
6. latenza media minore;
7. decisione documentata della giuria.

Il software mostra tutte le componenti necessarie; la decisione finale deve essere esportata nell'audit.
