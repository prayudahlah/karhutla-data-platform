# ADR-002: Storage dan Table Format

## Status

Accepted (21 November 2026). Menggantikan versi “Iceberg sebagai salinan audit”.

## Context

Gold dipakai bersama oleh ML, API, dan dashboard. F-07 meminta satu table
format dengan bukti snapshot/upsert. Sebelumnya Parquet adalah jalur yang
dibaca konsumen, sedangkan Iceberg hanya salinan kedua. Akibatnya ada dua
kebenaran: kalau `gold-publish` dilewati, Iceberg basi tanpa alarm.

Keputusan: **Iceberg menjadi jalur resmi Gold.** Parquet hanya staging dbt.

## Decision

- **Canonical Gold: Iceberg v2.**
  - `cell_daily` dan `province_daily` dipartisi per `date`.
  - `burn_scar_monthly` dipartisi per `burn_month`.
  - Snapshot disimpan 30 hari; expire dijadwalkan.
- **Parquet: staging dbt.**
  - dbt menulis Parquet karena adapter dbt-DuckDB belum bisa menulis Iceberg.
  - Parquet **tidak** dibaca API, dashboard, atau ML.
- **Postgres: serving cache.**
  - `sync_marts` membaca snapshot Iceberg aktif (`current.json`) lalu menyalin
    ke Postgres.
  - FastAPI dan Metabase membaca Postgres.
- **ML: membaca Iceberg.**
  - `cell_daily` dibaca dari snapshot yang sama dengan `current.json`.
- **Publish gate.**
  - `gold-publish --strict` menulis Iceberg, menjalankan parity Parquet vs
    Iceberg, lalu menulis `publish_state.json` dan `current.json`.
  - `current.json` hanya berubah setelah semua tabel lolos parity.
  - Gagal publish/parity: serving tetap snapshot lama; tidak ada data setengah
    jadi.
- **Katalog dan warehouse.**
  - Katalog SQLite di `data/gold/_iceberg/catalog.db` untuk demo lokal; dapat
    diganti katalog REST/Glue saat deploy.
  - Warehouse lokal `data/gold/_iceberg/warehouse`, atau
    `s3://lakehouse/gold/iceberg` untuk Garage.
- **Backup.**
  - Katalog SQLite dan warehouse di-backup terjadwal.
  - Catalog hilang = snapshot tidak terbaca walau file Parquet/warehouse ada.
- **Retensi.**
  - Bronze tanpa batas, Silver boleh dibangun ulang, Gold snapshot 30 hari
    dengan minimal 2 snapshot.

## Alternatives

- **Parquet canonical + Iceberg salinan audit** (Opsi A): ditolak karena dua
  kebenaran dan staleness tidak terlihat.
- **Delta Lake**: lebih terikat ke Spark, sedangkan mesin kita DuckDB.
- **Hudi**: fokus upsert incremental yang tidak dibutuhkan.
- **MinIO**: tidak lagi dimaintain (diarsipkan April 2026).

## Consequences

- `gold-publish` wajib dijalankan setelah `dbt build --select tag:gold`.
  `gold-refresh` merangkai keduanya dan gagal bila publish/parity gagal.
- `sync_marts` berubah dari `read_parquet` menjadi pembacaan Iceberg.
- ML harus memakai helper Iceberg, bukan Parquet.
- Katalog Iceberg masuk cakupan backup; restore harus diuji.
- Snapshot lama harus di-expire agar tidak tumbuh tanpa batas.
- Masa transisi: konsumen lama masih membaca Parquet; parity memastikan isinya
  sama sampai migrasi selesai.

## Bukti dan batasan

- **Pengecualian transisi:** pipeline ML temporal masih membaca Parquet
  `hotspot_cell_day` (label same-day) untuk menjaga baseline 29 fitur. Migrasi
  ke `cell_daily`/Iceberg dan label D..D+2 dicatat sebagai pekerjaan lanjutan.
- Bukti F-07 saat ini memakai **warehouse lokal**
  (`data/gold/_iceberg_evidence`).
- Jalur Garage `s3://lakehouse/gold/iceberg` belum diuji. Sampai integration
  test Garage ada, kontrak menyebut warehouse lokal untuk Iceberg; Garage tetap
  dipakai untuk Bronze/Silver.
- Penjadwalan expire/backup memakai `task gold-maintenance`; deployment
  Prefect/cron menyusul.

## Implementasi

| Perintah | Fungsi |
|---|---|
| `task gold-build` | bangun Gold Parquet + katalog |
| `task gold-publish` | publish Iceberg + parity + pointer |
| `task gold-refresh` | build → publish strict → sync marts |
| `task gold-maintenance` | expire snapshot → backup → verify |
| `python -m batch.gold.publish --check` | parity Parquet vs Iceberg |
| `python -m batch.gold.publish --verify` | snapshot + jumlah baris |
| `python -m batch.gold.publish --expire --retention-days 30 --min-snapshots 2` | expire snapshot |
| `python -m batch.gold.publish --backup <dir>` | backup katalog + warehouse |
| `python -m batch.gold.publish --restore <dir>` | restore katalog + warehouse |

Bukti F-07:

- publish penuh pada data asli 95.360 / 1.216 / 34 baris;
- `current.json` menunjuk snapshot ID yang sama untuk ketiga tabel;
- upsert satu partisi menghasilkan snapshot `delete` + `append`;
- schema evolution menambah kolom tanpa rewrite;
- expire menyisakan minimal N snapshot;
- backup/restore katalog diuji.
