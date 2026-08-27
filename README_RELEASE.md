# Release after_round_1

Archivio didattico: `origin_type` e `reliability` sono nel manifest; licenze/URL in `license_manifest.csv`.

Estrarre nella radice della starter repository, poi eseguire `python install_release.py`. Lo script unisce `data/release_manifest.json` in `data/manifest.json` senza perdere le fonti della track.
Verificare `data/checksums.sha256` prima dell'ingestion.
