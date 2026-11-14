# Karhutla Data Platform

Platform data untuk memantau dan memprediksi risiko hotspot karhutla dari FIRMS dan Open-Meteo.

Status: **skeleton**. Struktur folder dan kontrak awal sudah ada, implementasi masih belum, sabar yach.

## Arsitektur singkat

| VM | Peran | Isi |
|---|---|---|
| `stream` | Near-stream ingestion | Redpanda, producer FIRMS |
| `batch` | Batch, lakehouse, ML | MinIO, consumer, Prefect worker, DuckDB, MLflow, LightGBM |
| `core` | Serving, portal, observability | Postgres, Prefect server, FastAPI, portal, Metabase, Prometheus, Grafana, Loki, Caddy, Authelia |

Detail ada di `docs/architecture.md`.

## Sumber data

- FIRMS hotspot, near-stream.
- Open-Meteo historis dan forecast, batch.

Detail ada di `docs/data-sources.md`.

## Quick start

Belum bisa dijalankan karena service Compose masih placeholder.

1. Copy `.env.example` menjadi `.env` untuk dev lokal, atau `.env.stream`, `.env.batch`, `.env.core` di tiap VM.
2. Install `just`.
3. Lihat daftar perintah.

```bash
task --list
task dev
```

## Open-Meteo ke Bronze

Ingestion weather dan air quality ke Garage Bronze sudah tersedia:

```bash
python -m flows.openmeteo_ingestion --limit 2
python -m flows.openmeteo_ingestion
python -m flows.openmeteo_ingestion --verify-only <run_id>
```

Panduan lengkap, termasuk menjalankan Garage lokal, ada di
`docs/runbooks/garage-bronze.md`.

Garage dan browser bucket-nya jalan lewat Compose, lalu web UI ada di
<http://localhost:3909>:

```bash
docker compose -f compose/base.yml -f compose/vps-batch.yml up -d
```

## Struktur

- `src/` kode aplikasi
- `compose/` Compose per VM
- `docs/` arsitektur, ADR, runbook
- `evidence/` indeks bukti F-01 sampai F-20
- `metadata/` data contract
- `lineage/` event lineage

## Lisensi

Kode berlisensi MIT. Data pihak ketiga mengikuti lisensi masing-masing sumber.

## Aturan tim

Baca `CONTRIBUTING.md`.
