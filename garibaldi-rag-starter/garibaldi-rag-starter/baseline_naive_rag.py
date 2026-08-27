"""baseline_naive_rag.py — starter e2e per l'hackathon «Il caso dei Mille».

Questo file è la baseline ufficiale da lanciare: ingest (Docling → chunk → embed →
Qdrant) + naive dense RAG + scrittura/validazione di submission.json.

In produzione conviene spezzare organizzare le varie parti
in moduli separati. Qui restano insieme per chiarezza didattica.

Requisiti: OPENAI_API_KEY nel .env (embedding + LLM). Nessun fallback senza API.

Esempio:
  python baseline_naive_rag.py \\
    --questions eval/sample_questions.json \\
    --round-id sample \\
    --output outputs/submission_sample.json \\
    --rebuild
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ---------------------------------------------------------------------------
# Contratto submission (= forma di eval/submission.example.json)
# ConfigDict(extra="forbid"): campi non previsti → errore (come additionalProperties: false).
# ValidationError: eccezione di Pydantic quando il JSON non rispetta i Field.
# ---------------------------------------------------------------------------


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=5)
    document_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)


class Telemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_ms: int = Field(ge=0)
    declared_cost_eur: float = Field(ge=0)
    model_calls: list[ModelCall] = Field(default_factory=list)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    contexts: list[Context] = Field(default_factory=list, max_length=5)
    telemetry: Telemetry


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    round_id: str = Field(min_length=1)
    answers: list[Answer] = Field(min_length=1)


def validate_payload(
    payload: dict,
    questions: dict | None = None,
    manifest: dict | None = None,
    round_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        submission = Submission.model_validate(payload)
    except ValidationError as exc:
        return [error["msg"] + " @ " + ".".join(map(str, error["loc"])) for error in exc.errors()]
    for answer in submission.answers:
        ranks = [context.rank for context in answer.contexts]
        if ranks != list(range(1, len(ranks) + 1)):
            errors.append(f"{answer.question_id}: i rank dei contesti devono essere 1..N senza buchi")
    ids = [answer.question_id for answer in submission.answers]
    if len(ids) != len(set(ids)):
        errors.append("question_id duplicati")
    if round_id and submission.round_id != round_id:
        errors.append(f"round_id atteso {round_id}, ricevuto {submission.round_id}")
    if questions:
        expected = [row["question_id"] for row in questions["questions"]]
        actual = [row.question_id for row in submission.answers]
        if set(actual) != set(expected) or len(actual) != len(expected):
            errors.append(f"Copertura question_id non esatta. Attesi {expected}; ricevuti {actual}")
    if manifest:
        allowed = {row["document_id"] for row in manifest["documents"]}
        for answer in submission.answers:
            for context in answer.contexts:
                if context.document_id not in allowed:
                    errors.append(f"{answer.question_id}: document_id non disponibile: {context.document_id}")
    return errors


# ---------------------------------------------------------------------------
# Telemetria / costo autodichiarato
# ---------------------------------------------------------------------------


def declared_cost_eur(
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    override = os.getenv("DECLARED_COST_EUR")
    if override is not None and override.strip() != "":
        return max(0.0, float(override))
    input_rate = float(os.getenv("COST_INPUT_PER_MILLION_EUR", "0") or 0)
    output_rate = float(os.getenv("COST_OUTPUT_PER_MILLION_EUR", "0") or 0)
    cached_rate = float(os.getenv("COST_CACHED_INPUT_PER_MILLION_EUR", str(input_rate)) or 0)
    return round(
        (input_tokens / 1_000_000) * input_rate
        + (output_tokens / 1_000_000) * output_rate
        + (cached_input_tokens / 1_000_000) * cached_rate,
        6,
    )


def _token_usage(response: Any) -> tuple[int, int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    input_tokens = int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0)
    cached = int(getattr(usage, "cached_input_tokens", 0) or 0)
    return input_tokens, output_tokens, cached


def _meta_get(metadata: Any, key: str, default: str = "") -> str:
    if metadata is None:
        return default
    if isinstance(metadata, dict):
        value = metadata.get(key, default)
    else:
        value = getattr(metadata, key, default)
    return default if value is None else str(value)


# ---------------------------------------------------------------------------
# Scelta file primario dal manifest
# ---------------------------------------------------------------------------


def choose_primary(document: dict, project_root: Path) -> Path | None:
    """Un documento → un file. Se per errore ce ne fossero più, vince il PDF."""
    candidates: list[Path] = []
    for record in document.get("file_records", []):
        path = project_root / record["path"]
        if path.is_file():
            candidates.append(path)
    if not candidates:
        return None
    if len(candidates) > 1:
        candidates.sort(key=lambda p: (0 if p.suffix.lower() == ".pdf" else 1, p.name))
        print(f"warning: {document['document_id']} ha {len(candidates)} file; uso {candidates[0].name}")
    return candidates[0]


def iter_ingest_files(manifest: dict, project_root: Path) -> list[tuple[Path, str]]:
    rows: list[tuple[Path, str]] = []
    for document in manifest["documents"]:
        primary = choose_primary(document, project_root)
        if primary is None:
            print(f"skip (nessun file): {document['document_id']}")
            continue
        rows.append((primary, document["document_id"]))
    return rows


# ---------------------------------------------------------------------------
# Lab_08: ingest + naive dense RAG
# ---------------------------------------------------------------------------


EMB_NAME = "content_embedding"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def _local_qdrant(path: Path):
    """Qdrant embedded su disco.

    datapizza-ai espone `location`/`host`; per path locale inizializziamo il wrapper
    come fa il client sottostante (`QdrantClient(path=...)`).
    """
    from datapizza.vectorstores.qdrant import QdrantVectorstore

    store = QdrantVectorstore.__new__(QdrantVectorstore)
    store.host = None
    store.port = 6333
    store.api_key = None
    store.kwargs = {"path": str(path)}
    store.batch_size = 100
    return store


def build_clients(api_key: str, model: str):
    from datapizza.clients.openai import OpenAIClient
    from datapizza.embedders.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder(api_key=api_key, model_name=EMBEDDING_MODEL)
    llm = OpenAIClient(api_key=api_key, model=model)
    return embedder, llm


def ingest_corpus(
    *,
    files: list[tuple[Path, str]],
    embedder,
    qdrant_path: Path,
    collection: str,
    rebuild: bool,
):
    from datapizza.core.vectorstore import VectorConfig
    from datapizza.embedders import ChunkEmbedder
    from datapizza.modules.parsers.docling import DoclingParser
    from datapizza.modules.splitters import RecursiveSplitter
    from datapizza.pipeline import IngestionPipeline

    if rebuild and qdrant_path.exists():
        shutil.rmtree(qdrant_path)
    qdrant_path.mkdir(parents=True, exist_ok=True)

    vector_store = _local_qdrant(qdrant_path)
    client = vector_store.get_client()
    if client.collection_exists(collection):
        if rebuild:
            vector_store.delete_collection(collection)
        else:
            n_chunk = len(list(vector_store.dump_collection(collection)))
            print(f"Indice esistente: {n_chunk} chunk in '{collection}' ({qdrant_path})")
            return vector_store

    vector_store.create_collection(
        collection_name=collection,
        vector_config=[VectorConfig(dimensions=EMBEDDING_DIM, name=EMB_NAME)],
    )
    ingestion = IngestionPipeline(
        modules=[
            DoclingParser(),
            RecursiveSplitter(max_char=1024, overlap=128),
            ChunkEmbedder(client=embedder, embedding_name=EMB_NAME),
        ],
        vector_store=vector_store,
        collection_name=collection,
    )
    for path, document_id in files:
        ingestion.run(
            file_path=str(path),
            metadata={"document_id": document_id, "source_file": path.name},
        )
        print(f"ingest: {document_id} <- {path.name}")
    n_chunk = len(list(vector_store.dump_collection(collection)))
    print(f"Ingest completato: {n_chunk} chunk in '{collection}'")
    return vector_store


GROUNDING = (
    "Sei un Professore d'Archivio esperto in analisi storica. Rispondi alle domande basandoti ESCLUSIVAMENTE "
    "sui documenti forniti nel contesto. Ogni brano nel contesto inizia con il suo document_id tra parentesi quadre, "
    "ad esempio [cronologia_ufficiale_01]. Cita SEMPRE la fonte esatta usando quel document_id.\n\n"
    "Segui rigorosamente queste regole per formulare la risposta:\n"
    "1. **Massima Precisione nei Dettagli**: Non riassumere mai con formule generiche (es. non dire solo 'ci sono anomalie' o "
    "'ci sono preparativi'). Elenca i fatti specifici e precisi riportati nel testo (es. tre cancelli di servizio lasciati aperti, "
    "spostamento delle pattuglie, carri accumulati vuoti o dichiarati destinati a farina, granai sgomberati, dodici carri, date, ecc.).\n"
    "2. **Gestione dell'Incertezza e Astensione**: Se la domanda ti chiede se un fatto è provato o se c'è un accordo formale, "
    "e i documenti nel contesto NON contengono una prova diretta (ma mostrano solo indizi, voci o preparativi):\n"
    "   - Spiega esplicitamente che le evidenze dell'archivio sono INSUFFICIENTI o non provano con certezza quel fatto.\n"
    "   - Descrivi con precisione gli indizi logistici o le voci che sono effettivamente citati, citando le relative fonti.\n"
    "   - Dichiara chiaramente cosa manca (es. 'non ci sono patti firmati, ordini scritti, contratti formali o accordi sottoscritti').\n"
    "   - Se invece l'argomento della domanda non è minimamente menzionato nei documenti forniti, allora rispondi esattamente: 'Non lo so'.\n"
    "3. **Ragionamento Storico**: Distingui criticamente tra prove dirette (es. lettere private firmate, dispacci consolari), "
    "indizi (es. carri pronti prima del tempo) e propaganda/voci (es. notizie dei giornali borbonici o liberali, voci di corridoio). "
    "Se riporti notizie di giornale o di salotto, evidenzia che si tratta di propaganda o voci di parte (es. 'secondo la propaganda "
    "del Giornale Reale...').\n"
    "4. **No Conoscenza Esterna**: Non usare alcuna informazione storica esterna al contesto fornito."
)


# ---------------------------------------------------------------------------
# Selezione smart dei contesti (fix precision + rank quality dal feedback R1)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "della", "dello", "delle", "degli", "sulla", "sullo", "nella", "nello",
    "documento", "originale", "pagine", "pagina", "semplice", "chiave",
    "estratto", "archivio", "ufficiale", "eventi", "luoghi",
}


def _norm_match(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _source_tokens(source: str) -> set[str]:
    tokens: set[str] = set()
    for token in _norm_match(source).replace("_", " ").split():
        if len(token) >= 5 and token not in _STOPWORDS and not token.isdigit():
            # stem leggero: senza vocale finale "giornale" matcha anche "giornali"
            if len(token) >= 6 and token[-1] in "aeio":
                token = token[:-1]
            tokens.add(token)
    return tokens


def matched_docs_for(question: str, manifest: dict) -> set[str]:
    """Documenti che la domanda nomina esplicitamente.

    I token del document_id pesano il doppio di quelli del titolo: la lettera DI
    Salina vince sulla lettera A Salina (che lo cita solo nel titolo). Si tengono
    solo i documenti con il punteggio di match massimo.
    """
    question_norm = " " + _norm_match(question) + " "
    scores: dict[str, int] = {}
    for document in manifest["documents"]:
        id_tokens = _source_tokens(document["document_id"])
        title_tokens = _source_tokens(document.get("title", "")) - id_tokens
        score = 2 * sum(1 for t in id_tokens if f" {t}" in question_norm)
        score += sum(1 for t in title_tokens if f" {t}" in question_norm)
        scores[document["document_id"]] = score
    best = max(scores.values(), default=0)
    return {doc for doc, s in scores.items() if s and s == best}


def scored_retrieve(embedder, vector_store, collection: str, domanda: str, k: int = 12) -> list[dict]:
    """Retrieval denso con score di similarità, via client Qdrant nativo (il wrapper li scarta)."""
    query_vector = embedder.embed(domanda)
    if hasattr(query_vector, "vector"):
        query_vector = query_vector.vector
    elif isinstance(query_vector, list) and query_vector and hasattr(query_vector[0], "vector"):
        query_vector = query_vector[0].vector
    client = vector_store.get_client()
    result = client.query_points(
        collection_name=collection,
        query=query_vector,
        using=EMB_NAME,
        limit=k,
        with_payload=True,
    )
    hits = []
    for point in result.points:
        payload = point.payload or {}
        text = (payload.get("text") or "").strip()
        document_id = str(payload.get("document_id") or "")
        if text and document_id:
            hits.append({"document_id": document_id, "text": text, "score": float(point.score)})
    return hits


def select_contexts(question: str, hits: list[dict], manifest: dict, max_contexts: int = 5) -> list[dict]:
    """Selezione parsimoniosa dei contesti: la precision conta i documenti distinti citati.

    - Se la domanda nomina esplicitamente una fonte ("secondo la cronologia...",
      "il dispaccio del console...") si tengono i chunk di quella fonte in testa
      (rank quality), e altri documenti solo se battono il suo score migliore.
    - Altrimenti (domande generiche/cross-doc) comportamento vicino alla baseline:
      top-k con filtro leggero sulla coda, per non sacrificare la recall (20 pt > 10 pt).
    """
    if not hits:
        return []
    matched_docs = matched_docs_for(question, manifest)
    reference_docs = {
        d["document_id"] for d in manifest["documents"]
        if d.get("reliability") == "reference"
    }

    # dedup chunk identici
    seen: set[tuple[str, str]] = set()
    unique_hits: list[dict] = []
    for hit in hits:
        key = (hit["document_id"], hit["text"][:200])
        if key not in seen:
            seen.add(key)
            unique_hits.append(hit)

    retrieved_matched = [h for h in unique_hits if h["document_id"] in matched_docs]
    if retrieved_matched:
        best_matched = max(h["score"] for h in retrieved_matched)
        selected = sorted(retrieved_matched, key=lambda h: -h["score"])[:max_contexts]
        extras = [
            h for h in unique_hits
            if h["document_id"] not in matched_docs
            and h["score"] > best_matched
            and h["document_id"] not in reference_docs
        ]
        extra_docs_used: set[str] = set()
        for hit in sorted(extras, key=lambda h: -h["score"]):
            if len(selected) >= max_contexts or len(extra_docs_used) >= 1:
                break
            selected.append(hit)
            extra_docs_used.add(hit["document_id"])
        selected.sort(key=lambda h: (h["document_id"] not in matched_docs, -h["score"]))
        return selected[:max_contexts]

    top_score = unique_hits[0]["score"]
    pool = [h for h in unique_hits if h["score"] >= top_score * 0.6]
    # documenti di pura consultazione (elenchi, schede) in coda: riempiono solo se avanza spazio
    non_reference = [h for h in pool if h["document_id"] not in reference_docs]
    reference = [h for h in pool if h["document_id"] in reference_docs]
    selected = (non_reference + reference)[:max_contexts]
    return selected or unique_hits[:max_contexts]


def build_naive_dag(embedder, vector_store, llm):
    from datapizza.modules.prompt import ChatPromptTemplate
    from datapizza.pipeline import DagPipeline

    prompt_template = ChatPromptTemplate(
        user_prompt_template="Domanda: {{ user_prompt }}",
        retrieval_prompt_template=(
            "{% for chunk in chunks %}[{{ chunk.metadata.document_id }}]\n{{ chunk.text }}\n\n{% endfor %}"
        ),
    )
    dag = DagPipeline()
    dag.add_module("embedder", embedder)
    dag.add_module("retriever", vector_store.as_retriever())
    dag.add_module("prompt_template", prompt_template)
    dag.add_module("llm", llm)
    dag.connect("embedder", "retriever", target_key="query_vector")
    dag.connect("retriever", "prompt_template", target_key="chunks")
    dag.connect("prompt_template", "llm", target_key="memory")
    return dag


def dense_retrieve(embedder, vector_store, collection: str, domanda: str, k: int = 5):
    query_vector = embedder.embed(domanda)
    return vector_store.search(
        collection_name=collection,
        query_vector=query_vector,
        k=k,
        vector_name=EMB_NAME,
    )


def naive_rag(dag, collection: str, domanda: str, k: int = 5):
    """RAG densa completa (retrieve + generate). La baseline Lab_08."""
    return dag.run(
        {
            "embedder": {"text": domanda},
            "retriever": {"collection_name": collection, "k": k, "vector_name": EMB_NAME},
            "prompt_template": {"user_prompt": domanda},
            "llm": {"input": domanda, "system_prompt": GROUNDING},
        }
    )


def hits_to_contexts(hits: list[Any], max_contexts: int = 5) -> list[dict]:
    contexts: list[dict] = []
    for index, hit in enumerate(hits[:max_contexts], start=1):
        document_id = _meta_get(getattr(hit, "metadata", None), "document_id")
        content = (getattr(hit, "text", None) or "").strip()
        if not document_id or not content:
            continue
        contexts.append({"rank": index, "document_id": document_id, "content": content})
    # Re-numera 1..N dopo eventuali skip
    for index, row in enumerate(contexts, start=1):
        row["rank"] = index
    return contexts


EXPAND_PROMPT = (
    "Riformula la domanda in 3 query di ricerca brevi e diverse tra loro, per cercare "
    "in un archivio storico sul 1860 in Sicilia. Ogni query deve puntare a un aspetto "
    "diverso (persone, luoghi/logistica, atti/documenti). Una query per riga, nient'altro."
)


def expand_queries(llm, question: str) -> tuple[list[str], Any]:
    """Riformulazioni per il multi-query retrieval sulle domande cross-doc."""
    response = llm.invoke(
        input=f"Domanda: {question}", system_prompt=EXPAND_PROMPT, temperature=0.0, max_tokens=90
    )
    text = getattr(response, "text", None) or str(response)
    queries = [line.strip("-• ").strip() for line in text.splitlines() if line.strip()]
    return [q for q in queries if len(q) > 10][:3], response


def answer_one(
    question: dict,
    *,
    dag,
    embedder,
    vector_store,
    collection: str,
    model: str,
    k: int,
    manifest: dict,
    llm,
) -> dict:
    question_text = question["question"]
    started = time.perf_counter()
    hits = scored_retrieve(embedder, vector_store, collection, question_text, k=12)
    expansion_response = None
    if not matched_docs_for(question_text, manifest):
        # domanda generica/cross-doc: multi-query per non mancare fonti (recall)
        queries, expansion_response = expand_queries(llm, question_text)
        merged: dict[tuple[str, str], dict] = {
            (h["document_id"], h["text"][:200]): h for h in hits
        }
        for query in queries:
            for hit in scored_retrieve(embedder, vector_store, collection, query, k=8):
                key = (hit["document_id"], hit["text"][:200])
                if key not in merged or hit["score"] > merged[key]["score"]:
                    merged[key] = hit
        hits = sorted(merged.values(), key=lambda h: -h["score"])
    selected = select_contexts(question_text, hits, manifest, max_contexts=k)
    context_block = "\n\n".join(f"[{h['document_id']}]\n{h['text']}" for h in selected)
    llm_out = llm.invoke(
        input=f"{context_block}\n\nDomanda: {question_text}",
        system_prompt=GROUNDING,
    )
    latency_ms = max(0, round((time.perf_counter() - started) * 1000))
    answer_text = getattr(llm_out, "text", None) or str(llm_out)
    input_tokens, output_tokens, cached = _token_usage(llm_out)
    contexts = [
        {"rank": index, "document_id": h["document_id"], "content": h["text"]}
        for index, h in enumerate(selected, start=1)
    ]
    model_calls = [
        {
            "provider": "openai",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached,
        }
    ]
    if expansion_response is not None:
        exp_in, exp_out, exp_cached = _token_usage(expansion_response)
        model_calls.append(
            {
                "provider": "openai",
                "model": model,
                "input_tokens": exp_in,
                "output_tokens": exp_out,
                "cached_input_tokens": exp_cached,
            }
        )
        input_tokens += exp_in
        output_tokens += exp_out
        cached += exp_cached
    return {
        "question_id": question["question_id"],
        "question": question_text,
        "answer": answer_text,
        "contexts": contexts,
        "telemetry": {
            "latency_ms": latency_ms,
            "declared_cost_eur": declared_cost_eur(input_tokens, output_tokens, cached),
            "model_calls": model_calls,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _require_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY mancante: copiare .env.example → .env e impostare la chiave.")
    return api_key


def run_validate_only(args: argparse.Namespace) -> int:
    payload = json.loads(args.submission.read_text(encoding="utf-8"))
    questions = json.loads(args.questions.read_text(encoding="utf-8")) if args.questions else None
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
    errors = validate_payload(payload, questions, manifest, args.round_id)
    if errors:
        print("VALIDAZIONE FALLITA")
        for error in errors:
            print(f"- {error}")
        return 1
    print("VALIDAZIONE OK - il tentativo ufficiale non e stato consumato")
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Baseline naive RAG (Lab_08) -> submission.json")
    parser.add_argument("--questions", type=Path, help="JSON domande del round")
    parser.add_argument("--round-id", help="round_id da scrivere nella submission")
    parser.add_argument("--output", type=Path, help="Percorso submission.json in output")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
    parser.add_argument("--qdrant-path", type=Path, default=Path(os.getenv("QDRANT_PATH", "outputs/qdrant")))
    parser.add_argument("--collection", default=os.getenv("COLLECTION_NAME", "caso_dei_mille"))
    parser.add_argument("--k", type=int, default=int(os.getenv("MAX_CONTEXTS", "5")))
    parser.add_argument("--rebuild", action="store_true", help="Ricostruisce l'indice Qdrant")
    parser.add_argument("--validate-only", action="store_true", help="Valida una submission già prodotta")
    parser.add_argument("--submission", type=Path, help="Submission da validare (con --validate-only)")
    args = parser.parse_args()

    if not 1 <= args.k <= 5:
        raise SystemExit("--k deve essere tra 1 e 5")

    if args.validate_only:
        if not args.submission:
            raise SystemExit("--validate-only richiede --submission")
        return run_validate_only(args)

    if not args.questions or not args.round_id or not args.output:
        raise SystemExit("Richiesti --questions, --round-id e --output (oppure --validate-only)")

    api_key = _require_api_key()
    model = (
        os.getenv("OPENAI_MODEL")
        or os.getenv("DATAPIZZA_MODEL")
        or "gpt-4o-mini"
    ).strip()

    project_root = Path.cwd()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    files = iter_ingest_files(manifest, project_root)
    if not files:
        raise SystemExit("Nessun documento ingeribile dal manifest")

    embedder, llm = build_clients(api_key, model)
    vector_store = ingest_corpus(
        files=files,
        embedder=embedder,
        qdrant_path=args.qdrant_path,
        collection=args.collection,
        rebuild=args.rebuild,
    )
    answers = [
        answer_one(
            row,
            dag=None,
            embedder=embedder,
            vector_store=vector_store,
            collection=args.collection,
            model=model,
            k=args.k,
            manifest=manifest,
            llm=llm,
        )
        for row in questions["questions"]
    ]
    payload = {"schema_version": "1.0", "round_id": args.round_id, "answers": answers}
    errors = validate_payload(payload, questions, manifest, args.round_id)
    if errors:
        raise SystemExit("Submission non valida:\n- " + "\n- ".join(errors))
    submission = Submission.model_validate(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(submission.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Submission valida: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
