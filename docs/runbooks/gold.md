# Runbook — Gold Refresh dan Maintenance

Panduan operasional Gold: build, publish Iceberg, parity, expire, dan backup.

## Prasyarat

- Silver sudah dibangun (`task dbt-build` atau flow Silver).
- `dbt/profiles.yml` tersedia.
- `pyiceberg` terpasang (`pip install -e ".[dev]"`).
- Untuk Garage: `ICEBERG_WAREHOUSE=s3://lakehouse/gold/iceberg` dan
  `GARAGE_*` di `.env` terisi. Default lokal: `data/gold/_iceberg/warehouse`.

## Refresh harian

```bash
task gold-refresh
python -m batch.gold.publish --check
python -m batch.gold.publish --verify
```

`gold-refresh` = `gold-build` → `gold-publish --strict`.

- `--strict` menulis Iceberg, menjalankan parity Parquet vs Iceberg, lalu
  menulis `publish_state.json` dan `current.json`.
- Kalau parity gagal, `current.json` **tidak** berubah; serving tetap snapshot
  lama.
- `--check` membandingkan ulang tanpa menulis.
- `--verify` menampilkan jumlah baris dan snapshot per tabel.

## Maintenance mingguan

```bash
task gold-maintenance
```

Isinya:

1. `--expire --retention-days 30 --min-snapshots 2`
2. `--backup data/gold/_iceberg_backup`
3. `--verify`

Backup katalog SQLite + warehouse. Simpan 7 salinan harian/mingguan; hapus
yang lebih lama secara manual atau lewat cron.

## Jadwal

### Linux (cron)

```cron
# refresh Gold setiap hari 03.00
0 3 * * * cd /opt/karhutla && /usr/bin/env task gold-refresh >> logs/gold-refresh.log 2>&1

# maintenance setiap Minggu 04.00
0 4 * * 0 cd /opt/karhutla && /usr/bin/env task gold-maintenance >> logs/gold-maintenance.log 2>&1
```

Jika `task` tidak tersedia, pakai perintah langsung:

```cron
0 3 * * * cd /opt/karhutla && python -m batch.gold.publish --table all --mode full --strict >> logs/gold-refresh.log 2>&1
```

### Windows Task Scheduler (lokal)

Buat dua task:

1. **Gold Refresh**, harian 03.00:
   `cmd /c cd /d F:\path\karhutla-data-platform && python -m batch.gold.publish --table all --mode full --strict`
2. **Gold Maintenance**, mingguan:
   `cmd /c cd /d F:\path\karhutla-data-platform && python -m batch.gold.publish --expire --retention-days 30 --min-snapshots 2 && python -m batch.gold.publish --backup data\gold\_iceberg_backup`

### Prefect (opsional)

Jika flow `gold_daily` sudah dibuat, deployment-nya menjalankan urutan yang
sama: build → publish strict → sync marts → maintenance. Sampai flow itu ada,
cron/Task Scheduler adalah jadwal resmi.

## Kalau gagal

| Gejala | Tindakan |
|---|---|
| `ParityError` saat publish | jangan lanjut; periksa `--check`; build ulang Gold; publish lagi |
| `current.json` tidak berubah | serving tetap snapshot lama; tidak ada data setengah jadi |
| Catalog hilang | restore dari backup: `python -m batch.gold.publish --restore <dir>` lalu `--verify` |
| Snapshot menumpuk | jalankan `--expire --retention-days 30 --min-snapshots 2` |
| Warehouse Garage tidak bisa diakses | cek `GARAGE_ENDPOINT`, kredensial, region, path-style |

## Bukti

- `evidence/F-07-iceberg.md`
- `evidence/artifacts/iceberg-publish-state.json`
- `evidence/artifacts/iceberg-current.json`
- `evidence/artifacts/iceberg-check.json`

## Batasan

- Bukti F-07 memakai warehouse lokal; jalur Garage sudah diuji
  (`s3://lakehouse/gold/iceberg`) pada 21 November 2026. Warehouse lokal tetap
  default untuk demo.
- Serving (`sync_marts`) membaca Iceberg lalu menyalin ke Postgres; ML masih
  membaca Parquet sampai helper Iceberg dipakai.
