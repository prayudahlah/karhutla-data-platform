# Data Contracts

Satu file YAML per dataset. Field minimal:

- `name`
- `owner`
- `layer`
- `location`
- `grain`
- `schema`
- `freshness`
- `retention`
- `classification`
- `quality_rules`
- `consumers`

Kerangka kontrak Silver ada di `docs/data-contracts/*.yml`; isi `schema` dan
`quality_rules` final di PR masing-masing dataset.

## Tata letak Silver

Silver mengikuti bentuk Bronze agar DuckDB bisa membaca partisi tanpa logika
khusus per dataset:

```text
silver/_normalized/<sumber>/dataset=<dataset>/date=YYYY-MM-DD/part-00000.parquet
silver/<sumber>/dataset=<dataset>/date=YYYY-MM-DD/part-00000.parquet
```

`_normalized` hanya berisi hasil normalisasi format. Dedup dan aturan kualitas
dijalankan dbt sebelum data ditulis ke tabel Silver final. Laporan DQ disimpan
di `silver/_dq/...`, baris ditolak di `silver/_quarantine/...`, dan manifest di
`silver/manifests/run_id=<run_id>.json`.

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
`dataset=`.

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
| `firms.hotspot` | stream | kontinu, polling 10 menit | producer + consumer |
| `open_meteo.weather` | batch | harian | Prefect |
| `open_meteo.air_quality` | batch | harian | Prefect |
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
