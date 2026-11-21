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

1. Copy `.env.example` menjadi `.env` untuk node batch dan core, lalu `stream/.env.example` menjadi `stream/.env` untuk node stream. Keduanya `chmod 600`.
2. Install [Task](https://taskfile.dev): `winget install Task.Task` di Windows.
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

## Machine learning

Dataset ML adalah tabel Gold `hotspot_cell_day`: satu baris per sel 0,25° per
hari. Label biner bernilai 1 bila ada hotspot `kuat` atau `sedang` di sel-hari
itu, dan 0 bila hanya `lemah`/`kandidat`.

Pasang extra ML, bangun Gold, lalu audit sebelum training:

```bash
pip install -e ".[dev,ml]"
task dbt-build
task ml-audit
task ml-dataset
```

`dbt-build` menulis parquet Gold ke `data/gold/published/`. `ml-audit` menulis
laporan ke `data/gold/audit/`, dan `ml-dataset` menulis manifest split temporal
ke `data/gold/splits/`.

Hanya baris dengan jendela label lengkap yang dipakai: burn scar harus tersedia
pada rentang tanggal -7 sampai +7 hari. Dengan scar Agustus-September 2026,
rentang lengkap adalah 1-23 September (23 tanggal). Default split 5/5/3
menyisakan 7 hari training; ubah lewat environment atau CLI:

```bash
task ml-dataset -- --test-days 4 --valid-days 4 --purge-days 2 --min-train-rows 0
```

MCD64A1 Oktober 2026 belum dirilis saat dataset ini dibangun, jadi 24-30
September belum punya jendela lengkap. Setelah produk itu tersedia, jalankan
`task silver-mcd64a1 -- 2026-10` lalu `task dbt-build` lagi.

`--include-incomplete` ikut menyertakan baris yang jendela labelnya belum
lengkap; jangan dipakai untuk angka laporan.

Latih baseline Logistic Regression setelah dataset siap:

```bash
task ml-train -- --model lr --features t3
task ml-train -- --model lr --features nhotspot
```

Artefak tersimpan di `data/gold/models/lr-<grup>/`: pipeline `joblib`, metrik,
koefisien, ambang, dan tabel kalibrasi. `nhotspot` adalah pembanding satu fitur
untuk mengukur berapa besar performa yang berasal dari kepadatan deteksi. Tanpa
`MLFLOW_TRACKING_URI`, run dicatat ke folder `mlruns/` lokal.

MLflow berjalan di node batch:

```bash
docker compose -f compose/base.yml -f compose/vps-batch.yml up -d mlflow
```

UI: <http://localhost:5000>.

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
