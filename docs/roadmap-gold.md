# Roadmap: Gold

Status per 21 November 2026. Basis: `dev` setelah Silver selesai.

## Yang sudah jalan

| Tabel | Grain | Baris | Uji |
|---|---|---|---|
| `cell_daily` | `cell_id` × `date` | 95.360 | 13 uji + 1 singular |
| `province_daily` | `province` × `date` | 1.216 | 6 uji + 2 singular |
| `burn_scar_monthly` | `burn_month` × `province` | 34 | 5 uji + 3 singular |

Total `dbt build --select tag:gold`: **57 lulus, 0 gagal**, ±7 detik.

Rekonsiliasi yang diuji otomatis:

- hotspot: 486.238 baris; tier kuat 45.869, sedang 17.969, lemah 11.531,
  kandidat 410.869
- label: 6.377 positif dari 95.360 sel-hari (6,69%); 89.400 baris
  `label_complete`
- scar: 36.916 piksel = 7.922,17 km², tersebar di 34 provinsi
- dua build berturut-turut menghasilkan isi identik (0 baris berbeda)
- Iceberg v2: 3 tabel, ≥3 snapshot per tabel, upsert 1 partisi,
  schema evolution, backup/restore katalog (`task gold-publish`)

## Perintah

| Perintah | Fungsi |
|---|---|
| `task gold-build` | bersihkan tabel Gold dbt, `dbt build --select tag:gold`, lalu hasilkan katalog |
| `task gold-test` | jalankan uji model Gold saja |
| `task gold-catalog` | hasilkan `catalog.json` + `lineage.json` di `data/gold/_catalog/` |
| `task gold-publish` | publish Iceberg canonical + parity + pointer |
| `task gold-refresh` | `gold-build` lalu `gold-publish` |
| `task gold-maintenance` | expire snapshot + backup katalog + verify |
| `task gold-check` | lint, unit test, lalu build Gold |

Katalog memuat 4 tabel Gold (3 `implemented`, `risk_prediction_daily` masih
`planned`) dengan owner, klasifikasi, retensi, grain, dan schema. Lineage berisi
13 node dan 13 edge Bronze → Silver → Gold.

`risk_prediction_daily` hanya disiapkan foldernya; isinya menunggu inference ML.

## Keputusan desain

| Hal | Keputusan |
|---|---|
| Grid | 0,25°, 70 × 186 sel, batas dikunci di `dbt/macros/grid_cell.sql` |
| `cell_id` | `rrrr_cccc`, indeks baris/kolom, bukan koordinat |
| Provinsi | centroid provinsi terdekat dari `resources/indonesia_provinces.csv` |
| Semesta sel | sel yang pernah punya hotspot (2.980), laut otomatis keluar |
| Label | tier `kuat`/`sedang` pada D..D+2; `lemah`/`kandidat` bukan positif |
| Fitur model | jendela D-7..D-1, dihitung di `src/ml/features.py` (belum ada) |
| Partisi | `date=` untuk harian, `burn_month=` untuk scar bulanan |
| Format Gold | Iceberg v2 canonical; Parquet staging dbt; Postgres serving cache |
| Determinisme | agregat uang/float memakai `decimal(18,3)` agar tidak berubah antar run |

## Batasan yang harus ditulis di laporan

1. Cuaca hanya 38 titik (satu kota per provinsi), jadi fitur cuaca berlaku
   tingkat provinsi, bukan per sel.
2. Sebagian hari punya < 24 jam; ditandai `weather_complete = false`.
3. Provinsi dari Voronoi centroid bisa salah di perbatasan; `distance_km`
   disimpan untuk audit.
4. Semesta sel hanya sel yang pernah ada hotspot, jadi sel daratan yang tidak
   pernah terbakar tidak menjadi contoh negatif.
5. Scar di `cell_daily` hanya dari sel dalam semesta (36.803 dari 36.916
   piksel); rekonsiliasi penuh memakai `burn_scar_monthly` dan
   `province_daily`.

## Berikutnya (di luar ML)

Kontrak Gold (3 tabel `implemented`), `catalog.json`/`lineage.json`, dan
Iceberg v2 (ADR-002) sudah ada. Yang belum:

1. Serving: Postgres + `sync_marts.py` + FastAPI 10 endpoint.
2. Dashboard Metabase + info freshness; panel prediksi menunggu ML.

ML (`F-11`, `F-12`) ditunda atas permintaan pemilik project.
