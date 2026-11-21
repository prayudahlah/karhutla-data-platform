# Serving dan Dashboard Gold

Status: **API read-only dan mart Postgres jalan**; dashboard Metabase disiapkan
sebagai service, panelnya dibuat manual di UI. Panel prediksi menunggu ML.

## Alur

```text
dbt build --select tag:gold
        │
        ├── data/gold/published/{cell_daily,province_daily,burn_scar_monthly}
        │        │
        │        └── FastAPI (DuckDB read-only) ── 10 endpoint + OpenAPI
        │
        └── serving.sync_marts ── Postgres (gold_*) ── Metabase
```

API membaca Parquet Gold langsung lewat DuckDB, jadi bisa jalan tanpa Postgres.
Postgres adalah salinan mart untuk Metabase dan konsumen SQL lain.

## Perintah

| Perintah | Fungsi |
|---|---|
| `task gold-build` | bangun Gold + katalog |
| `task serving-dev` | jalankan API di `http://127.0.0.1:8000` |
| `task serving-sync` | salin 3 mart ke Postgres (butuh `DATABASE_DSN`) |
| `task up-core` | nyalakan Prefect, Postgres, API, Metabase |

Contoh lokal:

```bash
task gold-build
task serving-dev
# buka http://127.0.0.1:8000/docs
```

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
| 1 | `GET /health` | jumlah baris, tanggal terbaru, `freshness_at` |
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

### Metabase

1. Buka `http://localhost:3000`, selesaikan setup awal.
2. Tambah database Postgres: host `postgres`, port `5432`, database/user/password
   dari `POSTGRES_*` di `.env`.
3. Buat pertanyaan dari tabel `gold_province_daily`, `gold_burn_scar_monthly`,
   dan `gold_cell_daily`.
4. Tambah filter `province` dan rentang `date`; tampilkan kartu freshness dari
   `max(freshness_at)`.
5. Panel prediksi: placeholder "menunggu model ML" sampai
   `risk_prediction_daily` terisi.

## Batasan

- `cell_daily.label_risk` adalah label historis D..D+2 untuk latihan model,
  bukan prediksi. Jangan dipakai sebagai "risiko sekarang" di dashboard.
- Cuaca hanya 38 titik (satu kota per provinsi), jadi berlaku tingkat provinsi.
- Sebagian hari punya `weather_complete = false` bila jam teramati < 20.
- API memakai DuckDB read-only; untuk data besar, arahkan konsumen ke Postgres.
- `risk_prediction_daily` dan panel prediksi diserahkan ke pemilik ML.
