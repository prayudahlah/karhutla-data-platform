# ADR-002: Storage dan Table Format

## Status

Accepted (21 November 2026).

## Context

Bronze dan Silver selalu bisa dibangun ulang dari sumber, sedangkan Gold dipakai
bersama oleh ML, API, dan dashboard. F-07 meminta bukti versi tabel dan upsert.
Datanya kecil, sekitar 100 MB per bulan, dan penulisnya satu.

dbt-DuckDB menulis Parquet dengan baik, tetapi belum bisa menulis Iceberg
langsung. Karena itu Gold memerlukan langkah *publish* setelah dbt.

## Decision

- **Bronze dan Silver**: Parquet dengan kompresi zstd.
- **Object store**: Garage (S3-compatible), bukan MinIO.
- **Bronze**: dipartisi per dataset dan `ingest_date` atau `period`.
- **Silver**: dipartisi per tanggal event.
- **Gold**: Iceberg v2, ditulis lewat langkah publish di luar dbt.
  - `cell_daily` dan `province_daily` dipartisi per `date`.
  - `burn_scar_monthly` dipartisi per `burn_month`.
  - Snapshot Iceberg disimpan 30 hari
    (`history.expire.max-snapshot-age-ms`).
- **Katalog Iceberg**: SQLite di `data/gold/_iceberg/catalog.db` untuk demo
  lokal; dapat diganti katalog REST/Glue saat deploy.
- **Warehouse**: `data/gold/_iceberg/warehouse` untuk lokal, atau
  `s3://lakehouse/gold/iceberg` untuk Garage.
- **Serving**: Postgres hanya menyalin mart; API tetap membaca Parquet/Postgres,
  bukan Iceberg.
- **Retensi**: Bronze tanpa batas, Silver boleh dibangun ulang, Gold mengikuti
  snapshot 30 hari.

## Alternatives

- **Delta Lake**: lebih terikat ke Spark, sedangkan mesin kita DuckDB.
- **Hudi**: fokus upsert incremental yang tidak dibutuhkan.
- **Parquet tanpa table format di Gold**: tidak bisa memenuhi bukti snapshot dan
  schema evolution.
- **MinIO**: tidak lagi dimaintain (diarsipkan April 2026).

## Consequences

- Gold ditulis lewat dua jalur: Parquet (dbt) dan Iceberg (publish). Keduanya
  harus dijaga konsisten; `task gold-publish` dijalankan setelah
  `dbt build --select tag:gold`.
- Katalog Iceberg masuk cakupan backup dan restore.
- Menghapus Bronze berarti kehilangan kemampuan membangun ulang Silver dan Gold.
- Query Iceberg memakai pyiceberg/DuckDB/Spark; API tidak menunggu Iceberg.
- Menambah kolom di Gold (mis. `island`) otomatis menjadi schema evolution saat
  publish berikutnya.

## Implementasi

| Perintah | Fungsi |
|---|---|
| `task gold-build` | bangun Gold Parquet + katalog |
| `task gold-publish` | publish Gold Parquet ke Iceberg v2 |
| `python -m batch.gold.publish --verify` | tampilkan snapshot dan jumlah baris |
| `python -m batch.gold.publish --schema-evolution-demo` | demo tambah kolom |
| `python -m batch.gold.publish --backup <dir>` | backup katalog + warehouse |
| `python -m batch.gold.publish --restore <dir>` | restore katalog + warehouse |

Bukti F-07:

- dua publish penuh menghasilkan ≥3 snapshot per tabel;
- upsert satu partisi `province_daily` menghasilkan snapshot `delete` + `append`;
- schema evolution menambah kolom tanpa menulis ulang seluruh tabel;
- backup/restore katalog SQLite + warehouse diuji dengan `--verify`.
