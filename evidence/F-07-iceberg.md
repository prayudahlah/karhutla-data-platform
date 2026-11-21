# F-07 — Iceberg v2 sebagai Jalur Resmi Gold

Status: data asli, 21 November 2026. Branch `feat/gold-layer`.

## Data yang dipakai

Bukan fixture. Ini Gold hasil `dbt build --select tag:gold` dari Silver
Sep–Nov 2026:

| Tabel | Baris |
|---|---|
| `cell_daily` | 95.360 |
| `province_daily` | 1.216 |
| `burn_scar_monthly` | 34 |

## Perintah

```bash
task gold-build
python -m batch.gold.publish --table all --mode full --strict --run-id evidence-1
python -m batch.gold.publish --table all --mode full --strict --run-id evidence-2
python -m batch.gold.publish --table province_daily --mode upsert --date 2026-09-20 --strict --run-id evidence-3
python -m batch.gold.publish --check
python -m batch.gold.publish --verify
python -m batch.gold.publish --schema-evolution-demo
python -m batch.gold.publish --backup data/gold/_iceberg_evidence_backup
python -m batch.gold.publish --restore data/gold/_iceberg_evidence_backup
```

## Hasil

| Langkah | Hasil |
|---|---|
| Publish penuh pertama | 1 snapshot per tabel |
| Publish penuh kedua | 3 snapshot per tabel (`delete` + `append`) |
| Upsert `province_daily` 2026-09-20 | 7 snapshot; paritas tetap benar |
| `--check` | `ok: true` untuk ketiga tabel |
| `--verify` | 95.360 / 1.216 / 34 baris |
| Schema evolution | `id,label` → `id,label,note` |
| Backup/restore | `--verify` setelah restore sama |

### Schema evolution nyata: `island`

Setelah branch island, `python -m batch.gold.publish --table all --mode full
--strict --run-id island-2026-09` menambahkan kolom `island` ke ketiga tabel
Iceberg tanpa menulis ulang seluruh tabel. Hasil:

- `cell_daily` 95.360 baris, `province_daily` 1.216, `burn_scar_monthly` 34;
- `--check` → `ok: true` untuk ketiga tabel;
- kolom `island` ada di schema Iceberg ketiga tabel.

`current.json` setelah upsert menunjuk snapshot ketiga tabel:

```json
{
  "run_id": "evidence-3",
  "published_at": "2026-11-21T08:18:01.182790+00:00",
  "snapshots": {
    "cell_daily": 5730114291177768438,
    "province_daily": 1135712900791749098,
    "burn_scar_monthly": 8954783690607722154
  }
}
```

Paritas Parquet vs Iceberg (checksum minimum):

| Tabel | Baris | Checksum |
|---|---|---|
| `cell_daily` | 95.360 | hotspot 486.238 |
| `province_daily` | 1.216 | hotspot 486.238; scar 721.226 (jumlah kumulatif harian) |
| `burn_scar_monthly` | 34 | scar 36.916 |

## Garage

- Integration test `tests/integration/test_iceberg_garage.py` lulus 21 November
  2026 dengan `ICEBERG_WAREHOUSE=s3://lakehouse/gold/iceberg`.
- Publish Gold asli ke Garage: `cell_daily` 95.360, `province_daily` 1.216,
  `burn_scar_monthly` 34; `--check` `ok: true`; kolom `island` ikut.
- Artefak: `iceberg-garage-publish.json`, `iceberg-garage-check.json`,
  `iceberg-garage-verify.json`.

## Artefak

- `evidence/artifacts/iceberg-publish-1.json`
- `evidence/artifacts/iceberg-publish-2.json`
- `evidence/artifacts/iceberg-upsert.json`
- `evidence/artifacts/iceberg-check.json`
- `evidence/artifacts/iceberg-verify.json`
- `evidence/artifacts/iceberg-publish-state.json`
- `evidence/artifacts/iceberg-current.json`
- `evidence/artifacts/iceberg-garage-publish.json`
- `evidence/artifacts/iceberg-garage-check.json`
- `evidence/artifacts/iceberg-garage-verify.json`
- `evidence/artifacts/iceberg-schema-evolution.json`
- `evidence/artifacts/iceberg-backup.json`
- `evidence/artifacts/iceberg-restore.json`
- `evidence/artifacts/iceberg-verify-after-restore.json`
- `evidence/artifacts/iceberg-expire.json`

## Retensi

`--expire --retention-days 30 --min-snapshots 2` dijalankan pada data asli.
Karena semua snapshot dibuat hari ini, tidak ada yang lebih tua dari 30 hari,
jadi hasilnya `before = after` (3 / 7 / 3). Unit test
`test_expire_keeps_min_snapshots` membuktikan expire benar-benar mengurangi
snapshot dengan `--retention-days 0 --min-snapshots 1` dan menyisakan minimal
satu snapshot.

Perintah maintenance:

```bash
task gold-maintenance
```

## Batasan yang masih terbuka

1. Bukti utama memakai warehouse lokal
   (`data/gold/_iceberg_evidence`). Jalur Garage juga diuji
   (`s3://lakehouse/gold/iceberg`); warehouse lokal tetap default untuk demo.
2. `--expire` dan `--backup` sudah bisa dijalankan dan diuji. Urutan
   operasionalnya ada di `docs/runbooks/gold.md` (`task gold-maintenance`);
   deployment cron/Prefect belum dipasang.
3. Serving sekarang membaca Postgres yang disalin dari Iceberg (`sync_marts`);
   API memakai Postgres bila `DATABASE_DSN` diisi. ML masih membaca Parquet
   sampai helper Iceberg dipakai.

## Kesimpulan

Untuk F-07, bukti snapshot/upsert/schema evolution/backup/expire sudah berdiri
di atas data asli 95.360 baris, bukan fixture. Garage juga sudah diuji. Yang
belum ditutup adalah penjadwalan expire/backup dan migrasi ML ke Iceberg.
