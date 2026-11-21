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

## Artefak

- `evidence/artifacts/iceberg-publish-1.json`
- `evidence/artifacts/iceberg-publish-2.json`
- `evidence/artifacts/iceberg-upsert.json`
- `evidence/artifacts/iceberg-check.json`
- `evidence/artifacts/iceberg-verify.json`
- `evidence/artifacts/iceberg-publish-state.json`
- `evidence/artifacts/iceberg-current.json`
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

1. Warehouse yang dipakai bukti ini adalah **lokal**
   (`data/gold/_iceberg_evidence`). Jalur Garage `s3://` belum diuji; kontrak
   dan ADR harus menyebut ini sampai integration test Garage ada.
2. `--expire` dan `--backup` sudah bisa dijalankan dan diuji, tetapi belum
   dijadwalkan lewat Prefect/cron. `task gold-maintenance` adalah urutan
   operasionalnya; penjadwalan menyusul.
3. Serving (`sync_marts`) dan ML masih membaca Parquet. Migrasi ke Iceberg
   menyusul di branch serving/ML; sampai itu selesai, Iceberg baru canonical
   untuk Gold, belum untuk konsumen.

## Kesimpulan

Untuk F-07, bukti snapshot/upsert/schema evolution/backup/expire sudah berdiri
di atas data asli 95.360 baris, bukan fixture. Yang belum ditutup adalah
Garage, penjadwalan expire/backup, dan migrasi konsumen.
