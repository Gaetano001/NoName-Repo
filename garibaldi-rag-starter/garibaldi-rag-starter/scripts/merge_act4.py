import json
from pathlib import Path

def merge_manifest(base_manifest: dict, patch: dict) -> dict:
    by_id = {row["document_id"]: row for row in base_manifest.get("documents", [])}
    for row in patch.get("documents", []):
        by_id[row["document_id"]] = row
    base_manifest["documents"] = sorted(by_id.values(), key=lambda row: (row.get("act", 0), row["document_id"]))
    base_manifest["available_acts"] = sorted(
        {int(x) for x in base_manifest.get("available_acts", []) + patch.get("available_acts", [])}
    )
    base_manifest["last_release_id"] = patch.get("release_id", base_manifest.get("last_release_id"))
    return base_manifest

def main():
    project_root = Path(__file__).parent.parent
    base_manifest_path = project_root / "data" / "manifest.json"
    patch_manifest_path = project_root / "data" / "release_manifest.json"
    
    if base_manifest_path.exists() and patch_manifest_path.exists():
        base = json.loads(base_manifest_path.read_text(encoding="utf-8"))
        patch = json.loads(patch_manifest_path.read_text(encoding="utf-8"))
        merged = merge_manifest(base, patch)
        base_manifest_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] Manifest unificato con successo per Act 4. Atti disponibili: {merged['available_acts']}")
    else:
        print("[ERRORE] File manifest non trovati.")

if __name__ == "__main__":
    main()
