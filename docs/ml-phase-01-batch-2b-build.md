# Phase 01 Batch 2B — Event Evidence, BBox Remediation, and Defensive Guard

Tanggal build: 21 November 2026  
Branch: `feat/machine-learning`  
Scope: Batch 2B remediation; tidak ada Phase 02, training, split redesign, feature change, atau model change.

## 1. Ringkasan

Post-build audit menemukan satu event negative `candidate_no_scar_match` yang memiliki
required observation `burned`, tetapi tidak memiliki matching Burn Scar.

Root cause: **CONFIRMED** — `dbt/models/silver/mcd64a1_burn_scar.sql` memfilter
`where in_bbox`, sedangkan `in_bbox` hanya memeriksa pixel center. Pixel kasus utama
berada 0,0013° di luar bbox timur, walaupun footprint 500 m-nya beririsan dengan bbox
dan hotspot-nya berada di dalam bbox. `mcd64a1_pixel_observation` membaca HDF langsung
tanpa filter tersebut, sehingga terjadi inkonsistensi.

Remediation yang diterapkan:

1. Definisi spasial B: **pixel footprint intersects bbox**.
2. Kolom baru `footprint_intersects_bbox`; `in_bbox` tetap berarti pixel center.
3. Published Burn Scar memakai `footprint_intersects_bbox`.
4. Defensive guard untuk burned usable observation tanpa matching Burn Scar.
5. Audit flag `burned_without_scar_candidate`; `candidate_insufficient` tidak diperluas.
6. Rebuild Burn Scar sebelum event evidence.
7. Rebuild kedua untuk membuktikan idempotensi.

Tidak ada backfill Oktober 2026. Gold lama, loader, fitur, preprocessing, split, dan
model tidak diubah.

## 2. Definisi Spasial Final

Burn Scar dimasukkan jika **footprint native pixel beririsan dengan bbox studi**:

- CRS: MODIS Sinusoidal, sphere radius `6.371.007,181 m`.
- Resolusi: `463,312717 m × 463,312717 m`.
- Grid: `ulx`, `uly`, `px`, `py`, `nx=2400`, `ny=2400`.
- Bbox: `west=95,0`, `south=-11,0`, `east=141,0`, `north=6,0`.
- Footprint dihitung dari empat sudut:
  - `x0 = ulx + px * col`
  - `x1 = x0 + px`
  - `y1 = uly - py * row`
  - `y0 = y1 - py`
- Sudut ditransformasi dengan inverse sinusoidal Batch 2A:
  - `lat = degrees(y / R)`
  - `lon = degrees(x / (R * cos(radians(lat))))`
- Intersection memakai **closed polygon–rectangle intersection**; touch boundary
  dianggap beririsan.
- Tidak ada buffer, padding, `pyproj`, datum shift, atau toleransi koordinat arbitrer.

### Kasus utama

Pixel `h31v09`, row 2026, col 2273:

| Item | Nilai |
|---|---:|
| Center longitude | 141,001300 (di luar bbox) |
| Lower-left longitude | 140,999956 |
| Upper-left longitude | 140,998433 |
| Bbox east | 141,000000 |
| Hotspot longitude | 140,999240 |

HDF:

| Layer | Nilai |
|---|---:|
| Burn Date | 264 (`2026-09-21`) |
| QA | 3 |
| Burn Date Uncertainty | 3 |
| First Day | 227 |
| Last Day | 288 |

Normalized Burn Scar menyimpan row dengan `in_bbox=false`; published sebelumnya
membuangnya. Definisi B mempertahankan row tersebut.

## 3. Perbandingan A, B, dan C

| Pendekatan | Row | Delta vs A | Status |
|---|---:|---:|---|
| A — pixel center | 59.454 | 0 | Lama; kehilangan 12 scar boundary |
| **B — footprint intersects** | **59.466** | **+12** | **Diterapkan** |
| C — footprint fully inside | 59.443 | −11 | Tidak dipakai; membuang 11 row A |

Verifikasi:

- `A but not B = 0` — seluruh 59.454 row lama dipertahankan.
- `B − A = 12` — tepat 12 row tambahan.
- Normalized total tetap 318.879 row.
- `footprint_intersects_bbox=false`: 259.413 row; tidak ada row yang sepenuhnya
  di luar bbox ikut masuk.
- Densifikasi 16 titik per edge menghasilkan 12 row tambahan yang sama.

## 4. 12 Row Tambahan

| Tile | Row | Col | Burn date | Periode |
|---|---:|---:|---|---|
| h31v09 | 1661 | 2393 | 2026-08-16 | 2026-08 |
| h31v09 | 1662 | 2393 | 2026-08-16 | 2026-08 |
| h31v09 | 1651 | 2396 | 2026-08-20 | 2026-08 |
| h31v09 | 1652 | 2396 | 2026-08-20 | 2026-08 |
| h31v09 | 2043 | 2267 | 2026-09-06 | 2026-09 |
| h31v09 | 2045 | 2266 | 2026-09-06 | 2026-09 |
| h31v09 | 2046 | 2266 | 2026-09-06 | 2026-09 |
| h31v09 | 2149 | 2227 | 2026-09-11 | 2026-09 |
| h31v09 | 2147 | 2228 | 2026-09-13 | 2026-09 |
| h31v09 | 1657 | 2394 | 2026-09-17 | 2026-09 |
| h31v09 | 2026 | 2273 | 2026-09-21 | 2026-09 |
| h31v09 | 1655 | 2395 | 2026-09-26 | 2026-09 |

Distribusi: 4 row Agustus, 8 row September; seluruhnya tile `h31v09`.

## 5. Implementasi

### Source

- `src/batch/silver/mcd64a1.py`
  - `pixel_footprint`, `polygon_intersects_bbox`, `footprint_intersects_bbox`;
  - `SCAR_SCHEMA` mendapat `footprint_intersects_bbox`;
  - `parse_tile` menghitung flag dari empat sudut native.
- `src/batch/silver/mcd64a1_event_evidence.py`
  - `_burned_without_scar_candidate`;
  - event incomplete jika burned usable observation tidak memiliki matching scar;
  - kolom audit `burned_without_scar_candidate`.

### dbt

- `dbt/models/staging/stg_mcd64a1_burn_scar.sql` — cast flag baru.
- `dbt/models/silver/mcd64a1_burn_scar.sql` — filter
  `where footprint_intersects_bbox`; `overwrite=true` untuk rebuild deterministik.
- `dbt/models/silver/hotspot_event_evidence_schema.yml` — dokumentasi audit flag.

`in_bbox` tidak diubah semantik. `mcd64a1_pixel_observation`,
`hotspot_scar_label`, `gold_hotspot_cell_day.sql`, Gold lama, loader, fitur,
preprocessing, split, dan model tidak diubah.

## 6. Validasi Burn Scar

| Item | Hasil |
|---|---:|
| Published rows | 59.466 |
| Unique `tile+pixel_row+pixel_col+burn_date` | 59.466 |
| Duplicate key | 0 |
| Row A lama dipertahankan | 59.454 |
| Row B tambahan | 12 |
| `source_file` null | 0 |
| Key SHA-256 | `e20c244497c3022effa0710180805ebdf827947c1c8264371cf374be133fa59e` |
| Case 2026/2273 tersedia | Ya |
| Case 1657/2394 tersedia | Ya |
| Burned observation total | 59.456 |
| Burned observation tanpa matching scar | **0** |

Tidak ada row di luar bbox footprint yang masuk. `source_file` tetap HDF provenance
Batch 2A; tidak ada content/source mismatch baru.

## 7. Defensive Guard

Guard aktif jika:

- `source_status ∈ {available, identical_duplicate}`;
- observation tersedia;
- `raw_status_usable=true`;
- `raw_pixel_status='burned'`;
- `burn_date_code ∈ 1..366`;
- tidak ada Burn Scar dengan `tile + pixel_row + pixel_col + burn_date` yang sama.

Jika aktif:

- event `incomplete`;
- `required_evidence_incomplete=true`;
- `burned_without_scar_candidate=true`;
- bukan negative `candidate_no_scar_match`;
- `candidate_insufficient` **tidak** diisi untuk kasus tanpa candidate row.

Aktual setelah filter diperbaiki: **0 event guard**. Ini diharapkan karena seluruh
burned observation kini memiliki matching scar. Jalur guard dibuktikan dengan
fixture B40 dan B42; B43 memastikan tidak ada no-scar negative dengan audit flag.

Interaksi yang dipertahankan:

- candidate valid → label normal;
- candidate invalid/insufficient → incomplete existing;
- observation missing → incomplete existing;
- source missing/conflict → incomplete existing;
- scar outside window → negative existing;
- multiple candidate → primary selection existing.

## 8. Event Evidence

| Metrik | Hasil |
|---|---:|
| Events | 483.584 |
| Unique event_id | 483.584 |
| Evidence valid | 184.087 |
| Evidence insufficient | 153.543 |
| Evidence incomplete | 145.954 |
| Positive | **50.153** |
| Negative | **133.934** |
| Incomplete | **299.497** |

Perubahan dari build sebelumnya: positive +1, negative −1, incomplete tetap.

### Primary reason — mutually exclusive

`reason_primary` hanya terisi untuk event incomplete; `NULL` berarti event
positive/negative.

| Primary reason | Events |
|---|---:|
| NULL | 184.087 |
| window_unknown | 146.436 |
| source_missing | 94.046 |
| raw_unburned_special | 28.930 |
| raw_missing | 19.867 |
| window_partial | 7.107 |
| raw_water | 3.111 |
| **Total** | **483.584** |

`required_evidence_incomplete` aktual = 0 karena guard aktual = 0.

### Candidate

| Item | Hasil |
|---|---:|
| Candidate rows | 93.205 (+4) |
| Unique event_id + burn_scar_key | 93.205 |
| Valid | 93.204 |
| Invalid | 0 |
| Insufficient | 1 |
| Primary | 91.298 (+3) |
| Required period rows | 694.853 (+1) |
| Unique event_id + period | 694.853 |

Satu candidate baru insufficient adalah `eb4ac762...` (scar Agustus, observasi
Agustus tidak tersedia); event tersebut tetap incomplete karena source October
missing.

### Secondary/audit — overlapping

`label_reason_secondary` bersifat overlapping, bukan mutually exclusive; satu event
dapat memiliki beberapa reason.

| Secondary combination | Events |
|---|---:|
| observation_missing,required_evidence_incomplete,window_partial | 48.298 |
| window_unknown | 46.760 |
| observation_missing,required_evidence_incomplete,window_unknown | 35.209 |
| observation_missing,raw_missing,required_evidence_incomplete,window_unknown | 4.065 |
| observation_missing,raw_unburned_special,required_evidence_incomplete,window_unknown | 3.747 |
| observation_missing,raw_water,required_evidence_incomplete,window_unknown | 1.863 |
| window_partial | 1.678 |
| observation_missing,raw_unburned_special,required_evidence_incomplete,window_partial | 863 |
| raw_unburned_special,window_unknown | 156 |
| candidate_insufficient,observation_missing,required_evidence_incomplete,window_unknown | 1 |
| **Total event dengan secondary** | **142.640** |

Audit flag `burned_without_scar_candidate` = **0** setelah filter.

## 9. Event Kasus

| Event | Tanggal | Cell | Hasil |
|---|---|---|---|
| `0400c037...` | 2026-09-23 | `-34_563` | **Positive strong**, gap 2, 1 valid candidate |
| `f59c5113...` | 2026-09-28 | `-34_563` | Incomplete `source_missing`; candidate medium gap 7 |
| `e55a2bba...` | 2026-09-29 | `-28_563` | Incomplete `source_missing`; candidate weak gap 12 |
| `eb4ac762...` | 2026-09-29 | `-28_563` | Incomplete `source_missing`; candidate insufficient |

Tiga event terakhir tetap incomplete karena required October 2026 tidak tersedia,
bukan karena guard.

## 10. Cell-Day dan Gold

| Metrik | Hasil |
|---|---:|
| Cell-day rows | 34.460 |
| Unique `cell_id+date` | 34.460 |
| Positive | 2.066 |
| Negative | 14.211 |
| Incomplete | 18.183 |
| Fingerprint null | 0 |
| Duplicate fingerprint | 0 |
| Fingerprint SHA-256 | `68412e72c2486c6ed01d090f63cba60bdb4e71d3e80b71197c72f048e5b577c0` |

Cell `-34_563`, 2026-09-23:

| Metrik | Sebelum | Sesudah |
|---|---:|---:|
| n_positive | 3 | **4** |
| n_negative | 10 | **9** |
| n_incomplete | 0 | 0 |
| n_strong | 1 | **2** |
| n_no_scar_match | 10 | **9** |
| Label | Positive | **Positive** |
| Fingerprint | `726c8c14...` | `726c8c14...` |

Fingerprint tidak berubah karena field fingerprint hanya `cell_id`, `date`, `label`,
`label_status`, `label_complete`, dan `label_reason`; counts tidak termasuk. Perubahan
counts tetap tercatat di kolom audit.

Cell reason distribution:

| Reason | Cell-day |
|---|---:|
| candidate_no_scar_match | 13.741 |
| source_missing | 7.778 |
| window_unknown | 3.983 |
| raw_unburned_special | 2.735 |
| raw_missing | 1.847 |
| primary_strong | 1.727 |
| raw_water | 1.044 |
| window_partial | 796 |
| primary_medium | 339 |
| primary_weak | 240 |
| candidate_scar_outside_window | 230 |

`gold_hotspot_cell_day_labeled`:

- 34.460 row;
- 34.460 unique `cell_id+date`;
- 0 missing `n_events`;
- row count sama dengan Gold lama;
- Gold lama tidak dibangun ulang dan tidak diubah.

## 11. Tests and Checks

| Check | Hasil |
|---|---|
| B01–B48 | **48/48 passed** |
| Full unit tests | **409 collected; all passed** |
| dbt tests | **114 passed** |
| Batch 2B dbt selected build | **29 passed** (23 tests + 6 views) |
| Burn Scar dbt build | **7 passed** |
| Ruff | **All checks passed** |

B41, B45, B46 berada di `tests/unit/test_silver_mcd64a1.py`; B40, B42, B43, B44 di
`tests/unit/test_batch2b_event_evidence.py`; B47 adalah
`dbt/tests/mcd64a1_burn_scar_unique_pixel.sql`; B48 dibuktikan dengan rebuild kedua.

## 12. Idempotensi

Rebuild kedua dilakukan penuh:

1. normalize Burn Scar Agustus–September;
2. rebuild published Burn Scar;
3. rebuild event evidence;
4. rebuild view reason/Gold labeled.

Hasil:

| Objek | Sebelum | Sesudah | Status |
|---|---:|---:|---|
| Burn Scar rows | 59.466 | 59.466 | Sama |
| Burn Scar key SHA-256 | `e20c2444...` | `e20c2444...` | Sama |
| Event rows | 483.584 | 483.584 | Sama |
| Event key SHA-256 | `2348ca99...` | `2348ca99...` | Sama |
| Cell rows | 34.460 | 34.460 | Sama |
| Cell key SHA-256 | `f4cd5113...` | `f4cd5113...` | Sama |
| Cell fingerprint SHA-256 | `68412e72...` | `68412e72...` | Sama |

## 13. Limitasi

1. **Oktober 2026 tidak tersedia.** 94.046 event source_missing; tiga event kasus
   tetap incomplete.
2. **Guard aktual 0.** Ini bukan kegagalan guard; seluruh burned observation sudah
   mendapat matching scar. Guard diuji dengan fixture.
3. **Satu candidate baru insufficient.** `eb4ac762...`; event tetap incomplete.
4. **Sembilan scar tambahan belum dipakai event saat ini.** Tetap disimpan untuk
   konsistensi cakupan.
5. **Raw observation unusable dan coverage null** tetap menjadi penyebab incomplete
   lain.
6. **`task burned-verify` defect** (`BurnedAreaSettings.garage`) tetap di luar scope.
7. Tidak ada training, evaluasi model, Phase 02, atau backfill Oktober.

## 14. Acceptance Criteria

| Kriteria | Status |
|---|---|
| Published Burn Scar 59.466 | PASS |
| Seluruh 59.454 row lama dipertahankan | PASS |
| Tepat 12 row tambahan | PASS |
| Tidak ada duplicate `burn_scar_key` | PASS |
| Pixel 2026/2273 dan 1657/2394 tersedia | PASS |
| Pixel fully outside bbox dikeluarkan | PASS |
| Closed boundary intersection | PASS |
| Tidak ada burned observation tanpa matching scar | PASS |
| Event `0400...` positive strong | PASS |
| Tiga event Oktober tetap incomplete | PASS |
| Candidate valid lama tidak berubah | PASS |
| Tidak ada duplicate event/candidate | PASS |
| Cell `-34_563` tetap positive | PASS |
| `gold_hotspot_cell_day_labeled` 34.460 row, grain unik | PASS |
| Fingerprint deterministik | PASS |
| Provenance konsisten | PASS |
| B01–B48 | PASS |
| Unit tests | PASS |
| dbt tests | PASS |
| Ruff | PASS |
| Rebuild kedua identik | PASS |
| Gold lama/loader/fitur/split/model tidak berubah | PASS |
| Tidak ada backfill Oktober | PASS |

## 15. Git and Scope

Semua perubahan Batch 2B masih uncommitted/untracked. Tidak ada commit atau push
dalam sesi ini. Tidak ada perubahan pada `mcd64a1_pixel_observation`,
`hotspot_scar_label`, `gold_hotspot_cell_day.sql`, Gold lama, loader, fitur,
preprocessing, split, model, atau konfigurasi Phase 02.

## 16. Final Verdict

**PASS WITH LIMITATIONS**

Remediation bbox filter dan defensive guard memenuhi seluruh acceptance criteria
kritis. Burn Scar naik dari 59.454 menjadi 59.466 row, 12 row boundary masuk, 59.454
row lama dipertahankan, dan tidak ada burned observation tanpa matching scar. Event
`0400c037...` menjadi positive strong; cell `-34_563` tetap positive. Tiga event
Oktober tetap incomplete karena limitasi source, bukan karena regresi.

**Berhenti setelah Batch 2B. Phase 02, training, dan model evaluation tidak dimulai.**
