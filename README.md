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
`/predictions/daily` mengembalikan 503 sampai model ML tersedia.
Portal HTML disajikan di `/portal` bila `src/serving/portal/index.html` ada.
Detail ada di `docs/serving.md`.

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

### Pipeline temporal (Feast + Prefect)

Dua konfigurasi temporal (`lr-temporal-29` dan `lgbm-temporal-29`) dilatih
lewat satu flow Prefect. Fitur siap-model ditulis ke Gold, didaftarkan di
Feast, lalu diambil kembali dengan point-in-time join sebelum training.

```bash
pip install -e ".[dev,ml,feast]"

task ml-features        # tabel fitur Gold untuk Feast
task feast-apply        # daftarkan entity + feature view
task feast-materialize  # isi online store SQLite
task ml-pipeline        # flow Prefect manual, tanpa jadwal
```

Output ada di `data/gold/models/temporal/<run_id>/`, termasuk
`comparison.json` dan `pipeline_manifest.json`. MLflow mencatat satu parent
run, dua nested run, dan dua registered model dengan alias `candidate`.
Alias `champion` hanya di-set bila flow dijalankan dengan `promote=true`.

Detail arsitektur, kontrak fitur, dan kriteria promosi ada di
`docs/ml-temporal-pipeline.md`. Deployment Prefect-nya bernama
`ml-temporal-training` dan sengaja tidak punya jadwal.

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
