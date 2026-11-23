# Phase 01 Batch 2A — Pixel Observation Infrastructure Build

Tanggal build: 21 November 2026  
Branch: `feat/machine-learning`  
Scope: Batch 2A saja; tidak ada event evidence, tier, label, Gold reconciliation,
fitur, split, loader, atau model yang diubah.

## 1. Ringkasan

Batch 2A membangun:

1. `mcd64a1_granule_inventory`
2. `mcd64a1_granule_status`
3. `mcd64a1_pixel_period_required`
4. `mcd64a1_pixel_observation`
5. `mcd64a1_pixel_period_reconciliation`
6. Helper isolasi `validate_window_coverage`
7. Regression tests A01–A31
8. dbt views dan schema/data tests

Data sumber HDF dibaca dari Garage Bronze. Tidak ada synthetic data.

## 2. File yang dibuat/diubah

### Source

- `src/batch/silver/mcd64a1_pixel.py`
- `src/batch/silver/mcd64a1_coverage.py`
- `tests/unit/test_batch2a_pixel_observation.py`

### dbt

- `dbt/models/silver/mcd64a1_granule_inventory.sql`
- `dbt/models/silver/mcd64a1_granule_status.sql`
- `dbt/models/silver/mcd64a1_pixel_period_required.sql`
- `dbt/models/silver/mcd64a1_pixel_observation.sql`
- `dbt/models/silver/mcd64a1_pixel_period_reconciliation.sql`
- `dbt/models/silver/mcd64a1_observation_schema.yml`
- `dbt/tests/mcd64a1_granule_inventory_unique_key.sql`
- `dbt/tests/mcd64a1_granule_status_unique_key.sql`
- `dbt/tests/mcd64a1_pixel_observation_unique_key.sql`
- `dbt/tests/mcd64a1_pixel_observation_without_required.sql`
- `dbt/tests/mcd64a1_pixel_period_required_unique_key.sql`
- `dbt/tests/mcd64a1_pixel_reconciliation_sum.sql`
- `dbt/tests/mcd64a1_pixel_reconciliation_unique_key.sql`

### Output data

Parquet normalized:

```text
data/silver/_normalized/mcd64a1/
  dataset=granule_inventory/part-00000.parquet
  dataset=granule_status/part-00000.parquet
  dataset=pixel_period_required/part-00000.parquet
  dataset=pixel_observation/part-00000.parquet
  dataset=pixel_period_reconciliation/part-00000.parquet
```

dbt views membaca parquet tersebut. Tidak ada external table baru yang
menimpa `mcd64a1_burn_scar` atau tabel Gold.

## 3. Data Contract

### 3.1 `mcd64a1_granule_inventory`

- Grain: satu baris per kandidat granule.
- Key: `product, product_version, tile, period, granule_identity`.
- Field utama: `granule_identity`, `identity_source`, `production_datetime`,
  `canonical_source_uri`, `source_file`, `file_hash`, `manifest_sha256`,
  `manifest_size_bytes`, `manifest_match`, `raster_content_hash`, `read_status`,
  `metadata_complete`, `source_run_id`, `failure_reason`.
- Identity: producer ID, fallback `sha256(canonical_source_uri|file_hash)`, atau
  tidak ada jika hash tidak tersedia.

### 3.2 `mcd64a1_granule_status`

- Grain: `tile + period`.
- Status: `available`, `identical_duplicate`, `conflict`, `missing`,
  `metadata_incomplete`, `unknown`.
- Field: `candidate_count`, `canonical_granule_identity`,
  `raster_content_hash`, `status_reason`.

### 3.3 `mcd64a1_pixel_period_required`

- Grain: `tile + pixel_row + pixel_col + period`.
- Field: `n_events`, `required_for_window`, `required_for_scar`,
  `required_reason`.

### 3.4 `mcd64a1_pixel_observation`

- Grain: `tile + pixel_row + pixel_col + period`.
- Field raster: `burn_date_code`, `burn_date`, `qa`, `qa_land`, `qa_valid`,
  `qa_shortened_period`, `qa_contextual_relabel`, `qa_special_condition`,
  `uncertainty`, `first_day`, `last_day`.
- Field turunan: `coverage_start_date`, `coverage_end_date`,
  `raw_pixel_status`, `raw_status_usable`, `observation_available`.
- Provenance: `source_granule_identity`, `source_content_hash`, `source_file`,
  `source_run_id`.

### 3.5 `mcd64a1_pixel_period_reconciliation`

- Grain: required key.
- Kategori mutually exclusive: `observed_usable`, `observed_unusable`,
  `missing_granule`, `granule_conflict`, `metadata_incomplete`,
  `source_unknown`, `extraction_error`, `other_explained`.

### 3.6 Coverage helper

`src/batch/silver/mcd64a1_coverage.py::validate_window_coverage`

- Input: `event_date`, mapping `PeriodObservation`.
- Output: window start/end, status `full/partial/unknown`, covered dates,
  missing dates, intervals.
- Tidak memakai Burn Scar, tier, label, atau Gold.
- Interval validity tidak memerlukan `raw_status_usable`; usability menjadi
  tanggung jawab Batch 2B.

## 4. Hasil Eksekusi Aktual

### 4.1 Granule inventory/status

| Item | Nilai |
|---|---:|
| HDF inventory | 34 |
| Read status ok | 34 |
| Metadata complete | 34 |
| Manifest hash/size match | 34 |
| Status available | 34 |
| Status missing | 12 |
| Status conflict | 0 |
| Status identical_duplicate | 0 |

12 status missing adalah tile-period Oktober yang dibutuhkan untuk window
akhir September; tidak ada HDF Oktober.

### 4.2 Required pixel-period

| Metrik | Nilai |
|---|---:|
| Required keys | 358.808 |
| Required untuk window ±7 | 326.519 |
| Required flag scar | 59.454 |
| Required only window | 299.354 |
| Required only scar | 32.289 |
| Required window+scar | 27.165 |
| Agustus | 74.928 |
| September | 228.386 |
| Oktober | 55.494 |

### 4.3 Pixel observation

| Metrik | Nilai |
|---|---:|
| Observation berhasil diekstrak | 303.314 |
| Agustus | 74.928 |
| September | 228.386 |
| Oktober | 0 |
| Raw usable | 281.716 |
| Raw unusable | 21.598 |
| Unique observation key | Ya |

Distribusi raw status:

| Raw status | Count |
|---|---:|
| unburned | 222.260 |
| burned | 59.456 |
| unburned_special | 9.222 |
| missing | 8.935 |
| water | 3.441 |
| qa_insufficient | 0 |
| unknown | 0 |

QA metadata:

- `qa_shortened_period` true: 359
- `qa_contextual_relabel` true: 3.699
- `qa_special_condition > 0`: 9.222
- `coverage_start_date`/`coverage_end_date` null: 12.376 (First/Last fill atau
  interval tidak valid)

### 4.4 Reconciliation

| Kategori | Count |
|---|---:|
| observed_usable | 281.716 |
| observed_unusable | 21.598 |
| missing_granule | 55.494 |
| granule_conflict | 0 |
| metadata_incomplete | 0 |
| source_unknown | 0 |
| extraction_error | 0 |
| other_explained | 0 |
| **Total** | **358.808** |

`required = sum(kategori)` terpenuhi. `unexpected_observation = 0`.
Tidak ada duplicate required/observation key.

## 5. Validasi

### Pytest

```text
31 passed  tests/unit/test_batch2a_pixel_observation.py
362 passed tests/unit
```

Test A01–A31 mencakup identity, status granule, raw status, QA flags, special
codes, coverage lintas bulan/tahun/kabisat, reconciliation, provenance,
October missing, dan idempotency helper.

### dbt

```text
dbt run --select 5 model Batch 2A  -> PASS=5
dbt test --select 5 model Batch 2A -> PASS=24
```

### Ruff

```text
ruff check . -> All checks passed
```

## 6. Known Limitations

1. **Oktober tidak tersedia.** 55.494 required key berstatus `missing_granule`;
   tidak ada observation palsu.
2. **21.598 observation unusable.** Ini adalah missing/water/unburned_special,
   bukan missing granule; event-level handling ada di Batch 2B.
3. **Tidak ada conflict/duplicate granule aktual.** Kode dan unit test
   mencakup conflict/identical duplicate, tetapi data 34 HDF saat ini tidak
   memicunya.
4. **12.376 observation memiliki coverage interval null.** First/Last fill atau
   interval tidak valid; helper window coverage akan menandai partial/unknown
   pada Batch 2B.
5. **HDF berada di Garage, bukan filesystem lokal.** Extraction membaca dari
   `BronzeStore`; tidak ada salinan HDF di `data/`.
6. **Defect `task burned-verify` tidak diperbaiki.** Di luar scope; verifikasi
   manual SHA-256 sudah dilakukan pada Batch infrastruktur.
7. Batch 2B (event evidence, nearest scar, tier, label, Gold reconciliation)
   belum dimulai.

## 7. Acceptance Criteria

| Kriteria | Status | Bukti |
|---|---|---|
| Provenance HDF lengkap | PASS | inventory 34, source_file/hash/run |
| Required key unik | PASS | dbt test + pytest A09 |
| Observation key unik | PASS | dbt test + pytest A10 |
| Reconciliation seimbang | PASS | 358.808 = 358.808 |
| Conflict granule terdeteksi | PASS secara implementasi/test | A06; data aktual tidak punya conflict |
| Missing granule tanpa fake raster | PASS | 55.494 missing, 0 observation October |
| Idempotency | PASS | rerun menghasilkan count sama; unique key |
| Regression tests kritis | PASS | 31 pytest + 24 dbt |
| Dependency cycle | PASS | views membaca normalized; mapping existing |
| Komponen terlarang tidak berubah | PASS | tidak ada perubahan burn_scar/Gold/loader/features/split/model |

## 8. Git Diff Summary

Source/data artifacts baru:

- `src/batch/silver/mcd64a1_pixel.py`
- `src/batch/silver/mcd64a1_coverage.py`
- `tests/unit/test_batch2a_pixel_observation.py`
- 5 dbt model views
- 1 dbt schema file
- 7 dbt singular tests
- `docs/ml-phase-01-batch-2a-build.md`

Tidak ada perubahan pada:

- `mcd64a1_burn_scar.sql`
- `hotspot_scar_label.sql`
- `gold_hotspot_cell_day.sql`
- `src/ml/*`
- `experiments/*`
- fitur, preprocessing, split, model

## 9. Final Verdict

**PASS WITH LIMITATIONS**

Batch 2A menghasilkan pixel observation infrastructure yang lengkap untuk
Agustus–September 2026, dengan reconciliation seimbang dan provenance HDF.
Limitasi utama adalah Oktober tidak tersedia sehingga 55.494 required
pixel-period tetap missing, serta 21.598 observation unusable yang harus
ditangani oleh event-level evidence Batch 2B.

**Batch 2B belum dimulai.**
