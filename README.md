# Karhutla Data Platform

Platform data untuk memantau dan memprediksi risiko hotspot karhutla dari FIRMS dan Open-Meteo.

Status: **Bronze, Silver, Gold, dan serving read-only berjalan**. Dashboard
Metabase disiapkan; ML belum diimplementasikan.

## Arsitektur singkat

| VM | Peran | Isi |
|---|---|---|
| `stream` | Near-stream ingestion | Redpanda, producer FIRMS |
| `batch` | Batch, lakehouse | Garage, consumer, Prefect worker, DuckDB + dbt |
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

## Gold

Gold dibangun dbt dari Silver, tanpa menyentuh Bronze. Jalankan `task dbt-build`
dulu sekali supaya view Silver ada di DuckDB lokal:

```bash
task gold-build   # bersihkan tabel Gold dbt, dbt build --select tag:gold, lalu katalog
task gold-test    # uji model Gold saja
task gold-catalog # catalog.json + lineage.json di data/gold/_catalog/
task gold-publish # publish Iceberg canonical + parity + pointer
task gold-refresh # gold-build lalu gold-publish
task gold-maintenance # expire snapshot + backup katalog + verify
```

| Tabel | Grain | Baris |
|---|---|---|
| `cell_daily` | `cell_id` × `date` (grid 0,25°) | 95.360 |
| `province_daily` | `province` × `date` | 1.216 |
| `burn_scar_monthly` | `burn_month` × `province` | 34 |

Semua uji rekonsiliasi lulus: 486.238 hotspot, 36.916 piksel scar (7.922 km²),
6.377 label positif. Katalog Gold memuat 4 tabel (3 `implemented`, 1 `planned`
untuk ML) beserta owner, klasifikasi, retensi, dan lineage Bronze → Silver →
Gold. **Iceberg v2 adalah jalur resmi Gold**: Parquet hanya staging dbt,
Postgres adalah serving cache, dan ML membaca Iceberg. Detail ada di
`docs/roadmap-gold.md` dan `docs/adr/ADR-002-storage.md`.

Garage dan browser bucket-nya jalan lewat Compose, lalu web UI ada di
<http://localhost:3909>:

```bash
docker compose -f compose/base.yml -f compose/vps-batch.yml up -d
```

## Serving dan dashboard

API read-only membaca **Postgres** yang disalin dari Iceberg. Tanpa
`DATABASE_DSN`, API memakai Parquet Gold untuk lokal/tes. Dashboard HTML
menyusul; Metabase opsional.

```bash
task serving-dev    # http://127.0.0.1:8000/docs
task serving-sync   # salin 3 mart dari Iceberg ke Postgres (butuh DATABASE_DSN)
task up-core        # Prefect + Postgres + API + Metabase (opsional)
```

10 endpoint: health, provinsi, hotspot harian/ringkasan, FRP, scar
bulanan/kumulatif, cuaca, kualitas udara, dan peta sel 0,25°.
`/health` menyertakan snapshot Iceberg dan status `stale`.
`/predictions/daily` mengembalikan 503 sampai model ML tersedia. Detail ada di
`docs/serving.md`.

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
