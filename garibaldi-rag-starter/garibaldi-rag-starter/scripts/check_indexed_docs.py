import json
from pathlib import Path
from qdrant_client import QdrantClient

def check_db():
    manifest_path = Path("data/manifest.json")
    qdrant_path = Path("outputs/qdrant")
    
    if not manifest_path.exists():
        print("[ERRORE] manifest.json non trovato.")
        return
    if not qdrant_path.exists():
        print("[ERRORE] Database Qdrant non trovato in outputs/qdrant.")
        return
        
    # Leggi i documenti attesi dal manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_docs = {doc["document_id"] for doc in manifest["documents"]}
    
    # Leggi i documenti reali indicizzati in Qdrant
    client = QdrantClient(path=str(qdrant_path))
    collection = "caso_dei_mille"
    
    if not client.collection_exists(collection):
        print(f"[ERRORE] Collezione '{collection}' non trovata nel database.")
        return
        
    # Recupera tutti i punti indicizzati (limite a 1000 per sicurezza)
    points, _ = client.scroll(
        collection_name=collection,
        limit=1000,
        with_payload=["document_id"]
    )
    
    indexed_docs = {p.payload.get("document_id") for p in points if p.payload and p.payload.get("document_id")}
    
    print("\n=== VERIFICA DATABASE QDRANT ===")
    print(f"Documenti attesi dal Manifest : {len(expected_docs)}")
    print(f"Documenti trovati in Qdrant   : {len(indexed_docs)}")
    
    missing = expected_docs - indexed_docs
    if not missing:
        print("\n[OK] Tutti i documenti del manifest sono stati indicizzati con successo!")
    else:
        print(f"\n[ATTENZIONE] Mancano {len(missing)} documenti all'appello:")
        for doc in sorted(list(missing)):
            print(f"   - {doc}")

if __name__ == "__main__":
    check_db()
