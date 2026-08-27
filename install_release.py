from __future__ import annotations
import json
from pathlib import Path

root = Path(__file__).resolve().parent
base_path = root / "data" / "manifest.json"
patch_path = root / "data" / "release_manifest.json"
if not base_path.exists() or not patch_path.exists():
    raise SystemExit("Mancano data/manifest.json o data/release_manifest.json")
base = json.loads(base_path.read_text(encoding="utf-8"))
patch = json.loads(patch_path.read_text(encoding="utf-8"))
by_id = {row["document_id"]: row for row in base.get("documents", [])}
for row in patch.get("documents", []):
    by_id[row["document_id"]] = row
base["documents"] = sorted(by_id.values(), key=lambda row: (row.get("act", 0), row["document_id"]))
base["available_acts"] = sorted({int(x) for x in base.get("available_acts", []) + patch.get("available_acts", [])})
base["last_release_id"] = patch.get("release_id")
base_path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Manifest aggiornato: {len(base['documents'])} documenti, Act {base['available_acts']}")
