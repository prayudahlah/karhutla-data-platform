# Serving dan Dashboard Gold

Status: **API read-only dan mart Postgres jalan**. API membaca Postgres yang
disalin dari Iceberg; dashboard HTML menyusul, Metabase opsional. Panel prediksi
menunggu ML.

## Alur

```text
dbt build --select tag:gold
        │
        └── Parquet staging
                 │
                 └── gold-publish --strict ── Iceberg canonical + current.json
                          │
                          ├── sync_marts ── Postgres (gold_*) ── FastAPI ── HTML portal
                          └── ML membaca cell_daily dari Iceberg
```

`sync_marts` membaca snapshot Iceberg aktif (`current.json`), bukan Parquet.
FastAPI membaca Postgres bila `DATABASE_DSN` diisi; tanpa DSN, ia memakai
Parquet untuk tes lokal.

## Perintah

| Perintah | Fungsi |
|---|---|
| `task gold-refresh` | build Gold + publish Iceberg strict |
| `task serving-dev` | jalankan API di `http://127.0.0.1:8000` |
| `task serving-sync` | salin 3 mart dari Iceberg ke Postgres (butuh `DATABASE_DSN`) |
| `task up-core` | nyalakan Prefect, Postgres, API, Metabase (opsional) |

Contoh lokal:

```bash
task gold-refresh
task serving-dev
# buka http://127.0.0.1:8000/docs
```

Tanpa `DATABASE_DSN`, API memakai Parquet Gold lokal. Untuk jalur Postgres,
jalankan `serving-sync` dan set `DATABASE_DSN` (lihat bawah).

Dengan Compose:

```bash
task up-core
docker compose -f compose/base.yml -f compose/vps-core.yml exec api \
  python -m serving.sync_marts
```

`DATABASE_DSN` untuk host:

```text
dbname=karhutla user=karhutla password=karhutla host=127.0.0.1 port=5432
```

## Endpoint

| # | Endpoint | Isi |
|---|---|---|
| 1 | `GET /health` | jumlah baris, `freshness_at`, snapshot Iceberg + `stale` |
| 2 | `GET /meta/provinces` | daftar provinsi |
| 3 | `GET /hotspots/daily` | hotspot per tier per provinsi per hari |
| 4 | `GET /hotspots/summary` | total tier + FRP untuk rentang tanggal |
| 5 | `GET /frp/daily` | FRP harian |
| 6 | `GET /burn-scar/monthly` | luas terbakar bulanan per provinsi |
| 7 | `GET /burn-scar/cumulative` | scar kumulatif harian |
| 8 | `GET /weather/daily` | cuaca harian + `weather_complete` |
| 9 | `GET /air-quality/daily` | PM2.5 harian |
| 10 | `GET /cells/hotspots` | peta sel 0,25° untuk satu tanggal |
| - | `GET /predictions/daily` | **503** sampai model ML tersedia |

Semua endpoint menerima `province`, `start`, `end`, dan `limit` bila relevan.
Tanggal salah atau `limit` di luar 1..1000 mengembalikan **400** (bukan 422).
OpenAPI otomatis di `/openapi.json`.

## Panel dashboard yang sudah bisa dibuat

| Panel | Sumber | Kolom |
|---|---|---|
| Peta hotspot | `cell_daily` | `cell_lat`, `cell_lon`, `hotspot_count`, tier |
| Tren hotspot | `province_daily` | `hotspot_count`, `hotspot_kuat/sedang/lemah/kandidat` |
| FRP | `province_daily` | `frp_sum`, `frp_mean`, `frp_max` |
| Luas terbakar bulanan | `burn_scar_monthly` | `scar_pixels`, `scar_area_km2` |
| Scar kumulatif | `province_daily` | `scar_pixels_cum`, `scar_area_km2_cum` |
| Cuaca | `province_daily` | `temp_max`, `rh_min`, `precip_sum`, `wind_speed_max`, `vpd_max` |
| Kualitas udara | `province_daily` | `pm25_mean`, `pm25_max` |
| Freshness | `province_daily` | `max(freshness_at)` |
| Prediksi | `risk_prediction_daily` | menunggu ML |

### Dashboard HTML

Dashboard akan berupa portal HTML dari pemilik UI, bukan Metabase.

1. File HTML ditaruh di `src/serving/portal/` dan disajikan FastAPI
   (`/portal`).
2. Portal memanggil endpoint API (`/hotspots/...`, `/burn-scar/...`, `/frp/...`,
   `/weather/...`, `/air-quality/...`, `/cells/hotspots`, `/health`).
3. Metrik minimum: tren hotspot per tier, FRP, luas terbakar bulanan, scar
   kumulatif.
4. Filter: pulau/provinsi dan rentang tanggal.
5. Freshness: dari `/health` (`freshness_at` + `iceberg.stale`).
6. Panel prediksi: placeholder "menunggu model ML" sampai
   `risk_prediction_daily` terisi.

Metabase tetap opsional; service-nya ada di compose, tetapi bukan dashboard
utama.

## Batasan

- `cell_daily.label_risk` adalah label historis D..D+2 untuk latihan model,
  bukan prediksi. Jangan dipakai sebagai "risiko sekarang" di dashboard.
- Cuaca hanya 38 titik (satu kota per provinsi), jadi berlaku tingkat provinsi.
- Sebagian hari punya `weather_complete = false` bila jam teramati < 20.
- API membaca Postgres bila `DATABASE_DSN` diisi; Parquet hanya fallback lokal
  dan tes.
- `risk_prediction_daily` dan panel prediksi diserahkan ke pemilik ML.
