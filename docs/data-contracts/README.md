# Data Contracts

Satu file YAML per dataset. Kontrak final ada di direktori ini dan divalidasi
oleh `tests/unit/test_data_contracts.py`.

## Field wajib

- `name`
- `owner`
- `layer`
- `status`
- `location`
- `grain`
- `schema`
- `freshness`
- `retention`
- `classification`
- `quality_rules`
- `consumers`

Field tambahan yang dipakai bila relevan: `normalized_grain`, `deduplication`,
`source`, `source_models`, `normalized_schema`, `supporting_tables`,
`partition_note`, dan `tier_rules`.

## Status kontrak

| Status | Arti |
|---|---|
| `draft` | masih dibahas, belum boleh dipakai konsumen |
| `implemented` | sudah ada di kode dan tes |
| `deprecated` | dipertahankan sementara, sudah ada pengganti |

Semua kontrak Silver saat ini berstatus `implemented`.

## Matriks kontrak

| Dataset | Pemilik | Grain final | Kunci unik | Prefix final | Partisi |
|---|---|---|---|---|---|
| `firms_hotspot` | Yuda | satu baris per `event_id` | `event_id` | `silver/firms/dataset=hotspot` | `date=` |
| `open_meteo_weather` | Aulia | provinsi × kota × jam | `province, city, ts_utc` | `silver/open_meteo/dataset=weather` | `date=` UTC |
| `open_meteo_air_quality` | Aulia | provinsi × kota × jam | `province, city, ts_utc` | `silver/open_meteo/dataset=air_quality` | `date=` UTC |
| `mcd64a1_burn_scar` | Yuda | piksel terbakar × tile | `tile, burn_date, pixel_row, pixel_col` | `silver/mcd64a1/dataset=burn_scar` | `burn_date=` |
| `hotspot_scar_label` | Yuda | satu baris per `event_id` | `event_id` | `silver/firms/dataset=hotspot_label` | `date=` |

## Tata letak Silver

Silver memakai dua lapisan:

```text
silver/_normalized/<sumber>/dataset=<dataset>/date=YYYY-MM-DD/part-00000.parquet
silver/<sumber>/dataset=<dataset>/<partisi>/<berkas>.parquet
```

`_normalized` hanya berisi hasil normalisasi format. Dedup dan aturan kualitas
dijalankan dbt sebelum data ditulis ke tabel Silver final. Laporan DQ disimpan
di `silver/_dq/...`, baris ditolak di `silver/_quarantine/...`, dan manifest di
`silver/manifests/run_id=<run_id>.json`.

### Aturan partisi

- Default Silver: `date=YYYY-MM-DD`, memakai waktu data, bukan waktu ingest.
- Open-Meteo memakai tanggal UTC dari `ts_utc`.
- FIRMS dan `hotspot_scar_label` memakai `acq_date`.
- `mcd64a1_burn_scar` adalah pengecualian yang disengaja: tabel final memakai
  `burn_date=YYYY-MM-DD` karena `burn_date` adalah kunci join hotspot.
- `mcd64a1_tiles` tidak dipartisi; hasilnya satu berkas
  `silver/mcd64a1/dataset=tiles/tiles.parquet`.

### Dedup dan duplikat

- Bronze bersifat at-least-once; duplikat sah dan tidak boleh dibuang diam-diam.
- Dedup dilakukan di SQL/dbt, bukan di normalizer.
- FIRMS memilih `ingested_at` terbaru, lalu `source_file` terbesar.
- Open-Meteo memilih `ingestion_timestamp` terbaru, lalu `run_id` terbesar.
- `hotspot_scar_label` memilih scar dengan `gap_days` terkecil; hotspot tanpa
  scar tetap dipertahankan dengan `tier = kandidat`.

### Zona waktu dan unit

- Simpan `ts_utc`; pertahankan `ts_local` bila sumber menyediakannya.
- Open-Meteo memakai `utc_offset_seconds` dari respons API.
- Unit Open-Meteo disimpan di `units_json`; jangan mengasumsikan unit sama antar
  variabel.

### DQ dan karantina

- Setiap dataset menulis laporan DQ di
  `silver/_dq/<sumber>/dataset=<dataset>/run_id=<run_id>.json`.
- Baris yang ditolak masuk `silver/_quarantine/...` beserta alasan.
- Jumlah baris Bronze harus cocok dengan hasil normalisasi; selisihnya
  dijelaskan di laporan DQ.

## Perubahan kontrak

1. Ubah YAML dan tes dbt yang relevan dalam PR yang sama.
2. Jalankan validator kontrak dan `dbt build`.
3. Perbarui `docs/roadmap-silver.md` dan `evidence/README.md` bila menyentuh
   requirement F-xx.
4. Beri tahu konsumen jika ada kolom yang dihapus, diganti nama, atau diubah
   tipenya.

## Verifikasi

```bash
python -m pytest -q tests/unit/test_data_contracts.py
python -m ruff check .
python -m pytest -q
dbt build --project-dir dbt --profiles-dir dbt
```

Untuk memeriksa alur data lengkap:

```bash
python -m batch.silver.sync pull
dbt build --project-dir dbt --profiles-dir dbt
python -m batch.silver.sync push
```

## Tata letak Bronze

Semua sumber memakai bentuk yang sama supaya bisa dibaca DuckDB dengan
`hive_partitioning=true` tanpa penyesuaian per sumber.

```text
bronze/<sumber>/dataset=<dataset>/<kunci waktu>/...
```

Aturannya:

1. Akar memakai nama sumber, sama persis dengan nilai `source` di data:
   `firms`, `open_meteo`, `mcd64a1`.
2. Segmen kedua selalu `dataset=<nama>`. Satu sumber boleh punya lebih dari
   satu dataset.
3. Hanya ada dua nama kunci waktu: `ingest_date=YYYY-MM-DD` untuk kapan data
   diambil, dan `period=YYYY-MM` untuk periode yang diwakili datanya. Jangan
   memakai sinonim seperti `month=`, `date=`, atau `tahun=`.
4. Segmen setelahnya bebas selama stabil. Mengunduh data yang sama dua kali
   tidak boleh menghasilkan nama objek yang berbeda, kecuali memang snapshot
   baru (`run_id=`).

Pengecualian: manifest disimpan di `bronze/<sumber>/manifests/`, bukan di dalam
`dataset=`. Data Open-Meteo lama masih dapat memakai layout
`bronze/open_meteo/<dataset>/...`; normalizer mendukung kedua layout.

| Sumber | Contoh kunci |
|---|---|
| FIRMS | `bronze/firms/dataset=hotspot/ingest_date=2026-11-14/ingest_hour=07/part-p0-000000000001-000000000120.jsonl` |
| Open-Meteo | `bronze/open_meteo/dataset=weather/ingest_date=2026-11-14/run_id=<run_id>/01_banda_aceh_aceh.json` |
| MCD64A1 | `bronze/mcd64a1/dataset=burned_area/period=2026-09/tile=h28v09/MCD64A1.A2026244.h28v09.061.2026314124402.hdf` |

## Duplikat di Bronze

Bronze bersifat **at-least-once**. Event yang sama boleh muncul lebih dari
sekali karena dua sebab:

- replay spool setelah broker tidak tersedia, yang mengirim ulang event ke
  topik dengan offset baru;
- consumer berhenti setelah menulis objek tetapi sebelum commit offset.

Karena itu:

- Bronze tidak menjamin keunikan baris.
- Setiap event FIRMS membawa `event_id`, yaitu sha1 dari
  `lat|lon|acq_date|acq_time|satelit`.
- Silver wajib unik per `event_id` dan memilih baris dengan `ingested_at`
  terbaru.

Satu hotspot yang terlihat oleh dua satelit berbeda menghasilkan dua
`event_id` berbeda. Itu memang dua pengamatan, jadi keduanya dipertahankan.

## Kepemilikan dan kesegaran

| Dataset | Sumber | Irama | Pemilik job |
|---|---|---|---|
| `firms.hotspot` | stream + backfill | kontinu, polling 10 menit | producer + consumer |
| `open_meteo.weather` | batch + backfill | harian | Prefect |
| `open_meteo.air_quality` | batch + backfill | harian | Prefect |
| `mcd64a1.burned_area` | batch | bulanan | Prefect |

## Dua sumber tulis untuk FIRMS

Dataset `firms.hotspot` diisi dua jalur, dan keduanya memakai partisi yang
berbeda sesuai sifat datanya:

| Jalur | Partisi | Contoh |
|---|---|---|
| Stream (harian) | waktu ambil | `source=N20/ingest_date=2026-11-14/ingest_hour=07/` |
| Backfill (historis) | periode data | `source=N20/period=2026-09/part-backfill-...jsonl` |

Backfill memakai `period=` supaya menjalankan ulang bulan yang sama
menghasilkan kunci yang sama, sehingga idempoten. Kalau memakai `ingest_date=`,
setiap kali dijalankan ulang akan lahir salinan baru di partisi berbeda.

Keduanya dibaca oleh normalizer Silver yang sama, karena pola akhiran berkasnya
tetap `*.jsonl`.
