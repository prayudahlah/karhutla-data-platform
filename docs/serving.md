# Serving dan Dashboard Gold

Status: **API read-only, mart Postgres, dan dashboard HTML jalan**. API membaca
Postgres yang disalin dari Iceberg; dashboard tersedia di `/dashboard` dan
memanggil API serving. Metabase tetap opsional. Panel prediksi menunggu ML.

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

`DATABASE_SCHEMA` default `public`. `sync_marts` membuat schema bila belum ada;
API membaca `gold_*` dari schema itu. Ini dipakai tes integrasi Postgres dengan
schema sementara.

## Endpoint

| # | Endpoint | Isi |
|---|---|---|
| 1 | `GET /health` | jumlah baris, `freshness_at`, snapshot Iceberg + `stale` |
| 2 | `GET /meta/provinces` | daftar provinsi |
| 3 | `GET /hotspots/daily` | hotspot per tier per provinsi per hari |
| 4 | `GET /hotspots/daily/total` | total harian seluruh provinsi untuk grafik dashboard |
| 5 | `GET /hotspots/summary` | total tier + FRP untuk rentang tanggal |
| 6 | `GET /frp/daily` | FRP harian |
| 7 | `GET /burn-scar/monthly` | luas terbakar bulanan per provinsi |
| 8 | `GET /burn-scar/cumulative` | scar kumulatif harian |
| 9 | `GET /weather/daily` | cuaca harian + `weather_complete` |
| 10 | `GET /air-quality/daily` | PM2.5 harian |
| 11 | `GET /cells/hotspots` | peta sel 0,25° untuk satu tanggal |
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

Dashboard adalah halaman FastAPI di `/dashboard`, bukan Metabase. Template
`src/serving/templates/dashboard.html` memakai `base.html` (nav dan footer
portal), lalu `src/serving/static/dashboard.css` dan `dashboard.js`.

1. Dashboard memanggil API yang sama:
   `/hotspots/summary`, `/hotspots/daily/total`, `/burn-scar/monthly`,
   `/cells/hotspots`, `/meta/provinces`, dan `/health`.
2. KPI berbeda per tab:
   - **Sebaran & dampak**: total hotspot, hotspot kuat, FRP total, luas
     terbakar, sel aktif.
   - **Tren & prediksi**: puncak harian, rata-rata harian, hari terdata,
     puncak Σ FRP, kesiapan model.
3. Peta: sel hotspot pada tanggal akhir filter, diwarnai menurut tier dan
   diskalakan menurut `hotspot_count`; filter provinsi ikut diteruskan.
4. Dua tab: **Sebaran & dampak** (peta, donut tier, treemap provinsi, top 5)
   dan **Tren & prediksi** (hotspot per tier, FRP, kalender harian, horizon
   prediksi, checklist kesiapan).
5. Grafik: tren hotspot mingguan per tier, tren FRP harian, kalender
   intensitas harian, treemap provinsi, top 5 provinsi, dan komposisi tier.
6. Kanvas dashboard memakai lebar sampai 1560 px dengan padding samping,
   lebih lebar dari portal tetapi tetap menyisakan ruang di monitor desktop.
7. Filter bar: provinsi dan rentang tanggal. Filter pulau belum tersedia
   sampai kolom `island` di-merge dan `serving-sync` dijalankan.
8. Freshness: `/health` (`latest_date`, `iceberg.stale`, `age_hours`).
9. Panel prediksi: placeholder "menunggu model ML" sampai
   `risk_prediction_daily` terisi.

Data scar saat ini hanya tersedia untuk September 2026; dashboard mengambil
bulan yang tersedia di dalam rentang filter. Metabase tetap opsional;
service-nya ada di compose, tetapi bukan dashboard utama.

## Verifikasi

```bash
pytest -m "not integration"
# butuh Postgres; memakai schema sementara
DATABASE_DSN="dbname=... host=..." pytest tests/integration/test_serving_postgres.py -m integration
```

## Batasan

- `cell_daily.label_risk` adalah label historis D..D+2 untuk latihan model,
  bukan prediksi. Jangan dipakai sebagai "risiko sekarang" di dashboard.
- Cuaca hanya 38 titik (satu kota per provinsi), jadi berlaku tingkat provinsi.
- Sebagian hari punya `weather_complete = false` bila jam teramati < 20.
- API membaca Postgres bila `DATABASE_DSN` diisi; Parquet hanya fallback lokal
  dan tes.
- `risk_prediction_daily` dan panel prediksi diserahkan ke pemilik ML.

## Portal statis

Halaman HTML tanpa database, membaca `catalog.json` dan `lineage.json` dari
`GOLD_CATALOG_ROOT` (bawaan `data/gold/_catalog`).

| Rute | Isi |
|---|---|
| `/` | ringkasan tabel dan lineage |
| `/catalog` | daftar tabel Gold, owner, retensi, sumber |
| `/catalog/<nama>` | detail satu tabel dan skemanya |
| `/lineage` | node per layer dan daftar edge |

Kalau katalog belum ada, halaman tetap 200 dan menampilkan perintah yang harus
dijalankan, bukan error.

```bash
task gold-catalog      # hasilkan catalog.json dan lineage.json
task serving-dev       # buka http://127.0.0.1:8000
```

## Compose ringan

`compose/vps-core.yml` memberi profil `full` pada Prefect, Postgres, dan
Metabase. Tanpa profil itu, hanya API yang naik.

| Perintah | Yang naik |
|---|---|
| `task up-ui` | API dan portal saja |
| `task up-core` | core lengkap, termasuk Postgres dan Metabase |
| `task up-sso` | API, Caddy, Authelia, dan Grafana |

## Uji SSO lokal

Authelia 4.39 menolak skema http, jadi uji lokal memakai HTTPS dengan CA
internal Caddy (`local_certs`). Domain uji memakai `nip.io` agar tidak perlu
mengubah `/etc/hosts`.

1. Isi `.env`: `BASE_DOMAIN=127.0.0.1.nip.io`, `SCHEME=https`,
   `AUTH_URL=https://auth.127.0.0.1.nip.io`,
   `AUTHELIA_SESSION_SECRET=<acak minimal 32 karakter>`.
2. `task up-sso`.
3. Buka `https://app.127.0.0.1.nip.io` dan terima peringatan sertifikat
   internal sekali, atau pakai `curl -k` untuk uji.

Akun demo ada di `infra/authelia/users.yml` (viewer dan admin; kata sandi
`<nama>-demo`).

Yang diharapkan:

| Uji | Hasil |
|---|---|
| Buka portal tanpa login | redirect ke `auth.localhost` |
| Login viewer, buka portal | 200 |
| Viewer buka `/admin` | 403 |
| Grafana setelah login portal | langsung masuk, tanpa login kedua |
| Metabase | tidak termasuk compose ringan, dan OSS tidak menerima header SSO |

`/admin` sengaja belum punya halaman; rutenya disediakan untuk menguji 403.

## Demo layanan kosong

`task up-demo` menyalakan SSO plus Grafana, Metabase, dan Prefect. Postgres tidak
ikut karena Metabase memakai H2 dan Prefect memakai SQLite.

| Host | viewer | admin | Catatan |
|---|---|---|---|
| `app.*` | 200 | 200 | portal |
| `grafana.*` | 200 | 200 | masuk otomatis lewat `auth.proxy` |
| `metabase.*` | 200 | 200 | masih minta login sendiri, OSS tidak menerima header |
| `prefect.*` | 403 | 200 | hanya admin, karena bisa menjalankan job |

Start pertama Metabase memakan waktu beberapa menit karena harus menyiapkan H2.
Batasan memorinya 1500 MB, dan pada mesin ini terpakai sekitar 900 MB saat
inisialisasi.

`task down-demo` menghentikan layanan demo tanpa menghapus volume.
