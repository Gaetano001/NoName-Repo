import json
import shutil
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
    repo_root = project_root.parent.parent
    
    src_act3 = repo_root / "data" / "act_3"
    dst_act3 = project_root / "data" / "act_3"
    
    # 1. Copia i file fisicamente
    if src_act3.exists():
        dst_act3.mkdir(parents=True, exist_ok=True)
        copied = 0
        for item in src_act3.glob("*"):
            if item.is_file():
                shutil.copy2(item, dst_act3 / item.name)
                copied += 1
        print(f"[OK] Copiati {copied} file in {dst_act3.relative_to(project_root)}")
    else:
        print("[ERRORE] Cartella sorgente act_3 non trovata!")
        return
        
    # 2. Unisci il manifest
    base_manifest_path = project_root / "data" / "manifest.json"
    patch_manifest_path = repo_root / "data" / "release_manifest.json"
    
    if base_manifest_path.exists() and patch_manifest_path.exists():
        base = json.loads(base_manifest_path.read_text(encoding="utf-8"))
        patch = json.loads(patch_manifest_path.read_text(encoding="utf-8"))
        merged = merge_manifest(base, patch)
        base_manifest_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] Manifest aggiornato. Act disponibili: {merged['available_acts']}")
    else:
        print("[ERRORE] Impossibile trovare i file manifest per l'unione!")

if __name__ == "__main__":
    main()
