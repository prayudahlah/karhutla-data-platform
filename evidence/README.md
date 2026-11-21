# Evidence Index

| Req | Bukti | Test command | Status | Owner |
|---|---|---|---|---|
| F-01 | Compose, health check, deploy log | TBD | TBD | TBD |
| F-02 | [Open-Meteo Bronze](F-02-openmeteo-bronze.md) | `pytest -q -m integration` | Done | Batch |
| F-03 | Backfill report | TBD | TBD | TBD |
| F-04 | Producer, consumer, lag | `compose/vps-stream.yml` + `compose/vps-batch.yml`; `task lag` = 0; `stream/README.md` | `task selftest` lalu `task lag` | selesai | Kelompok 8 |
| F-05 | Dedup, DLQ, watermark | dedup producer (`firms_seen.json`), DLQ `firms.hotspot.dlq`, watermark `data/batch/state/watermark.json` | `task dlq`, `task bronze-files` | selesai | Kelompok 8 |
| F-06 | Bronze, Silver, Gold | [Kontrak Silver](../docs/data-contracts/README.md); Silver final di `silver/`; Gold `cell_daily`, `province_daily`, `burn_scar_monthly` (95.360 / 1.216 / 34 baris) | `task gold-build` | sebagian (risk_prediction_daily menunggu ML) | Batch |
| F-07 | Format tabel dan snapshot | [Iceberg v2](F-07-iceberg.md): Parquet staging + Iceberg canonical; parity + `current.json`; 95.360 / 1.216 / 34 baris; snapshot, upsert, schema evolution, backup/restore | `task gold-refresh`; `python -m batch.gold.publish --check` | selesai (Garage/expire/jadwal pending) | Batch |
| F-08 | DQ report dan quarantine | [Kontrak Silver](../docs/data-contracts/README.md); `silver/_dq/` dan `silver/_quarantine/`; 57 uji Gold termasuk rekonsiliasi dan label | `task gold-test` | sebagian | Batch |
| F-09 | Catalog dan lineage | Kontrak Gold 3 tabel + `catalog.json`/`lineage.json` (4 tabel, 13 node, 13 edge) di `data/gold/_catalog/` | `task gold-catalog` | sebagian (risk_prediction_daily `planned`) | Batch |
| F-10 | Query dan OpenAPI | 3 mart di Postgres (`gold_*`) via `serving.sync_marts` dari snapshot Iceberg `current.json`; FastAPI membaca Postgres; 10 endpoint + `/predictions/daily` 503; tanggal salah 400; `/health` memuat snapshot + `stale`; OpenAPI `/docs`; tes integrasi Postgres memakai schema sementara | `pytest -q tests/unit/test_serving_api.py tests/unit/test_serving_sync.py`; `pytest -m integration tests/integration/test_serving_postgres.py` (butuh `DATABASE_DSN`); `task serving-sync` | selesai (prediksi menunggu ML) | Kelompok 8 |
| F-11 | MLflow experiment | TBD | TBD | TBD |
| F-12 | Predictions table | TBD | TBD | TBD |
| F-13 | Dashboard dan SQL | Dashboard HTML (bukan Metabase) menyusul; API + mart Postgres sudah ada; peta panel di `docs/serving.md`; Metabase opsional | `task up-core` lalu `task serving-sync` | sebagian (HTML belum ada, prediksi menunggu ML) | Kelompok 8 |
| F-14 | Metrics dan structured log | TBD | TBD | TBD |
| F-15 | Tiga alert | TBD | TBD | TBD |
| F-16 | Auth, role, audit | TBD | TBD | TBD |
| F-17 | Backup dan restore | TBD | TBD | TBD |
| F-18 | Unit dan integration test | TBD | TBD | TBD |
| F-19 | Benchmark CSV dan grafik | TBD | TBD | TBD |
| F-20 | Laporan, ppt, demo | TBD | TBD | TBD |
