# Evidence Index

| Req | Bukti | Test command | Status | Owner |
|---|---|---|---|---|
| F-01 | Compose, health check, deploy log | TBD | TBD | TBD |
| F-02 | [Open-Meteo Bronze](F-02-openmeteo-bronze.md) | `pytest -q -m integration` | Done | Batch |
| F-03 | Backfill report | TBD | TBD | TBD |
| F-04 | Producer, consumer, lag | `compose/vps-stream.yml` + `compose/vps-batch.yml`; `task lag` = 0; `stream/README.md` | `task selftest` lalu `task lag` | selesai | Kelompok 8 |
| F-05 | Dedup, DLQ, watermark | dedup producer (`firms_seen.json`), DLQ `firms.hotspot.dlq`, watermark `data/batch/state/watermark.json` | `task dlq`, `task bronze-files` | selesai | Kelompok 8 |
| F-06 | Bronze, Silver, Gold | TBD | TBD | TBD |
| F-07 | Delta atau Iceberg snapshot | TBD | TBD | TBD |
| F-08 | DQ report dan quarantine | TBD | TBD | TBD |
| F-09 | Catalog dan lineage | TBD | TBD | TBD |
| F-10 | Query dan OpenAPI | TBD | TBD | TBD |
| F-11 | MLflow experiment | TBD | TBD | TBD |
| F-12 | Predictions table | TBD | TBD | TBD |
| F-13 | Dashboard dan SQL | TBD | TBD | TBD |
| F-14 | Metrics dan structured log | TBD | TBD | TBD |
| F-15 | Tiga alert | TBD | TBD | TBD |
| F-16 | Auth, role, audit | TBD | TBD | TBD |
| F-17 | Backup dan restore | TBD | TBD | TBD |
| F-18 | Unit dan integration test | TBD | TBD | TBD |
| F-19 | Benchmark CSV dan grafik | TBD | TBD | TBD |
| F-20 | Laporan, ppt, demo | TBD | TBD | TBD |
