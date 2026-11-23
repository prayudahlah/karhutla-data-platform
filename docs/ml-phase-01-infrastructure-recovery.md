# Phase 01 Batch 2A — Infrastructure Recovery

Tanggal pemeriksaan: 21 November 2026  
Branch: `feat/machine-learning`  
Mode: infrastructure recovery; tidak ada source code, schema, data, pipeline,
label, loader, features, split, model, atau Git history yang diubah.

## 1. Kondisi Awal Infrastruktur

Preflight pertama:

| Item | Kondisi |
|---|---|
| Docker daemon | Tidak tersedia |
| Docker Desktop process | Tidak berjalan |
| Docker service `com.docker.service` | `Stopped` |
| Docker Compose CLI | Tersedia (`v5.0.2`) |
| Garage S3 `127.0.0.1:3900` | Koneksi gagal |
| `data/bronze` | Tidak ada |
| File `.hdf` di bawah `data/` | Tidak ada |
| Disk bebas drive `E:` | 530,41 GB |

Konfigurasi repository tersedia:

- `compose/base.yml`
- `compose/vps-batch.yml`
- `infra/garage/garage.toml`
- `docs/runbooks/garage-bronze.md`
- `task burned-fetch`, `task burned-verify`
- `flows/burned_area_ingestion.py`
- `src/ingest/burned_area/ingest.py`

Tidak ada credential/token yang ditampilkan.

## 2. Kondisi Docker dan Garage Setelah Pemeriksaan Ulang

Setelah Docker Desktop/daemon tersedia, preflight diulang:

| Item | Kondisi |
|---|---|
| Docker server | `29.2.1` |
| Docker Compose CLI | `v5.0.2` |
| Docker Desktop process | Berjalan |
| Garage S3 3900 | Terbuka |
| `karhutla-garage` | Up, healthy |
| `karhutla-garage-webui` | Up, healthy |

Container yang terlihat:

```text
karhutla-garage         Up (healthy)   0.0.0.0:3900-3903->3900-3903/tcp
karhutla-garage-webui   Up (healthy)   0.0.0.0:3909->3909/tcp
```

Container tidak dihentikan, dibuat ulang, atau dihapus.

`garage status` menunjukkan node healthy:

```text
Node b5ecaf634db1bd6f
Hostname 2d0c4852846e
Address 127.0.0.1:3901
Capacity 1006.9 GiB
DataAvail 856.7 GiB (85.1%)
Version v2.3.0
```

## 3. Status Bucket

Bucket `lakehouse` tersedia:

```text
ID                Created     Global aliases
bfcbe7663f9755f7  2026-11-16  lakehouse
```

Tidak ada bucket/object yang dibuat, diubah, atau dihapus pada langkah ini.

## 4. Hasil Ingestion Agustus 2026

Manifest yang ada:

```text
bronze/mcd64a1/manifests/ingest_date=2026-11-16/run_id=20261116T073626Z-2a7f1900.json
```

| Item | Nilai |
|---|---|
| Run ID | `20261116T073626Z-2a7f1900` |
| Month | `2026-08` |
| Status | `success` |
| Granules seen | 17 |
| Granules written | 17 |
| Granules skipped | 0 |
| Granules failed | 0 |
| Bytes written | 21.881.451 |
| Entries | 17 |
| Tiles | 17 |

Tidak ada unduhan ulang karena object sudah tersedia.

## 5. Hasil Ingestion September 2026

Manifest yang ada:

```text
bronze/mcd64a1/manifests/ingest_date=2026-11-16/run_id=20261116T053139Z-4969b706.json
```

| Item | Nilai |
|---|---|
| Run ID | `20261116T053139Z-4969b706` |
| Month | `2026-09` |
| Status | `success` |
| Granules seen | 17 |
| Granules written | 17 |
| Granules skipped | 0 |
| Granules failed | 0 |
| Bytes written | 23.023.167 |
| Entries | 17 |
| Tiles | 17 |

Tidak ada unduhan ulang karena object sudah tersedia.

## 6. Jumlah Granule per Tile dan Periode

| Periode | Jumlah tile | Jumlah HDF | Granule per tile |
|---|---:|---:|---:|
| Agustus 2026 | 17 | 17 | 1 |
| September 2026 | 17 | 17 | 1 |
| **Total** | **17** | **34** | — |

Tile:

```text
h27v08 h27v09 h27v10
h28v08 h28v09 h28v10
h29v08 h29v09 h29v10
h30v08 h30v09 h30v10
h31v08 h31v09 h31v10
h32v08 h32v09
```

Jumlah object di prefix:

- `bronze/mcd64a1/dataset=burned_area`: 34 HDF.
- `period=2026-08`: 17 HDF.
- `period=2026-09`: 17 HDF.
- `period=2026-10`: 0 HDF.

October tetap unavailable.

## 7. Hasil Pemeriksaan Lima Layer HDF

Seluruh **34 HDF** berhasil dibaca memakai `src/batch/silver/mcd64a1.py::read_tile_bytes()`:

| Layer | Status |
|---|---|
| Burn Date | Terbaca |
| QA | Terbaca |
| Burn Date Uncertainty | Terbaca |
| First Day | Terbaca |
| Last Day | Terbaca |

Validasi:

- 34/34 HDF memiliki lima layer.
- Semua layer berbentuk `(2400, 2400)`.
- Tidak ada layer kosong.
- Burn Date range: -2 sampai 0 (tile tanpa burn) atau -2 sampai 243/273 (tile dengan burn).
- QA range: 0–131 atau 0–163.
- Metadata granule 34/34 lengkap: `BurnedCells`, `MissingCells`, `LandCells`, `ValidLandCells`, `ProductStartDay`, `ProductEndDay`, `year`, `tile`.
- `tile` pada metadata cocok dengan path.

Tidak ada extraction ke Silver.

## 8. File Hash dan Provenance

Manifest menyimpan `granule_id`, `month`, `tile`, `key`, `size_bytes`, dan `sha256`.

Verifikasi manual read-only:

| Manifest | Entries | SHA-256 match | Size match | Failures |
|---|---:|---:|---:|---:|
| Agustus `20261116T073626Z-2a7f1900` | 17 | 17/17 | 17/17 | 0 |
| September `20261116T053139Z-4969b706` | 17 | 17/17 | 17/17 | 0 |
| **Total** | **34** | **34/34** | **34/34** | **0** |

Provenance HDF:

```text
s3://lakehouse/bronze/mcd64a1/dataset=burned_area/period=YYYY-MM/tile=hXXvYY/<filename>.hdf
```

Manifest path:

```text
s3://lakehouse/bronze/mcd64a1/manifests/ingest_date=2026-11-16/run_id=<run_id>.json
```

## 9. Daftar Kegagalan atau Blocker

### Defect ditemukan

`task burned-verify -- <run_id>` gagal untuk kedua run ID:

```text
ERROR: AttributeError: 'BurnedAreaSettings' object has no attribute 'garage'
```

Lokasi: `flows/burned_area_ingestion.py::verify()` memanggil
`BronzeStore(settings.garage)` padahal `settings` adalah `BurnedAreaSettings`.
Perbaikan membutuhkan perubahan source code di luar lingkup pemulihan
infrastruktur. Source code **tidak diubah**.

Verifikasi manifest tetap diselesaikan secara manual read-only dengan
`BronzeStore`, SHA-256, dan `size_bytes`; hasilnya 34/34 cocok.

### Catatan

- HDF tersedia di Garage, bukan sebagai file lokal di `data/`.
- `data/bronze` tetap tidak ada; extraction Batch 2A harus membaca dari Garage
  memakai `BronzeStore`.
- `scripts/bootstrap.sh` dan `scripts/restore.sh` masih `TODO`, tetapi tidak
  menghalangi recovery ini.
- October tetap unavailable; jangan mengambilnya.
- Tidak ada synthetic data.

## 10. Status Kesiapan Batch 2A

| Gate | Status |
|---|---|
| Docker daemon | Lulus |
| Garage healthy | Lulus |
| Port 3900 | Lulus |
| Bucket `lakehouse` | Lulus |
| HDF Agustus | Lulus (17/17) |
| HDF September | Lulus (17/17) |
| Manifest | Lulus (2 manifest, 34/34 entri) |
| SHA-256/size | Lulus (34/34) |
| Lima layer HDF | Lulus (34/34) |
| Metadata granule | Lulus (34/34) |
| `task burned-verify` | **Gagal karena defect source** |
| October | Tidak tersedia (sesuai audit) |

**Status: PARTIALLY READY.**

Infrastruktur dan data HDF siap untuk Batch 2A. Namun `task burned-verify`
mengalami defect source code yang harus disetujui/diperbaiki terpisah sebelum
command verifikasi resmi dapat digunakan. Manual verification sudah membuktikan
34/34 HDF dan manifest konsisten.

## Tindakan Lanjutan

1. Pengguna meninjau defect `verify()` di `flows/burned_area_ingestion.py`.
2. Jika disetujui, perbaiki pemanggilan store agar memakai `Settings.from_env()`
   atau `Settings` yang memiliki `.garage`.
3. Setelah perbaikan, jalankan ulang:
   ```bash
   task burned-verify -- 20261116T073626Z-2a7f1900
   task burned-verify -- 20261116T053139Z-4969b706
   ```
4. Jangan menjalankan extraction Batch 2A dalam sesi ini.
5. October tetap unavailable.

Jika pengguna menerima verifikasi manual sebagai bukti, data/infrastruktur sudah
siap untuk Batch 2A; defect CLI tetap harus dicatat sebagai pekerjaan perbaikan
terpisah.
