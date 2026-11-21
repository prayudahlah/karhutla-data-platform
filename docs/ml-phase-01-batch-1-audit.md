# Phase 01 Batch 1 — Audit dan Exit Gate

Tanggal audit: 21 November 2026  
Branch: `feat/machine-learning`  
HEAD baseline: `dd1488f` (`versi 2`)  
Mode: documentation dan evidence build; tidak ada perubahan pipeline/data.

## 1. Dokumen yang dibuat

| Dokumen | Isi |
|---|---|
| `docs/adr/ADR-008-phase-01-label-contract.md` | Decision record Phase 01 |
| `docs/ml-label-contract.md` | Kontrak QA/coverage, Silver, Gold, lineage, fingerprint, loader |
| `docs/ml-phase-01-batch-1-audit.md` | Laporan audit ini |
| `docs/data-contracts/README.md` | Tautan silang ke kontrak label Phase 01 |

## 2. Bukti dokumentasi resmi

Referensi yang dipakai:

1. NASA LP DAAC, MCD64A1 v061:
   <https://www.earthdata.nasa.gov/data/catalog/lpcloud-mcd64a1-061>
2. DOI produk: <https://doi.org/10.5067/MODIS/MCD64A1.061>
3. MCD64 User Guide V6.1:
   <https://lpdaac.usgs.gov/documents/1006/MCD64_User_Guide_V61.pdf>
4. File Specification MCD64A1 v6.0.7:
   <https://ladsweb.modaps.eosdis.nasa.gov/filespec/MODIS/61/MCD64A1>

Fakta yang diambil dari File Specification:

- Burn Date: 1–366 = ordinal burn day; 0 = unburned; -1 = missing; -2 = water.
- QA bit 0 = land/water; bit 1 = valid/missing; bit 2 = shortened mapping
  period; bit 3 = class updated; bit 5–7 = special-condition code untuk
  unburned.
- Burn Date Uncertainty = temporal uncertainty dalam hari.
- First Day / Last Day = reliable change detection window, valid 1–366,
  fill -1, water -2.
- Granule metadata mencakup `BurnedCells`, `MissingCells`, `LandCells`,
  `ValidLandCells`, `ProductStartDay`, `ProductEndDay`.

## 3. Kondisi implementasi saat ini

### 3.1 MCD64A1 Silver

`src/batch/silver/mcd64a1.py` hanya menyimpan piksel dengan Burn Date >0:

- `parse_tile` membentuk `inside = (burn >= first_doy) & (burn <= last_doy)`;
- hanya baris `inside` yang menjadi `burn_scar`;
- Burn Date 0, -1, dan -2 tidak disimpan;
- `coverage` hanya menyimpan `pixels_burned` dan `pixels_outside_month`;
- metadata granule `ValidLandCells`, `LandCells`, `MissingCells`,
  `ProductStartDay`, `ProductEndDay` tidak dibaca;
- `first_day`/`last_day` hanya tersedia untuk piksel terbakar.

Implikasi: Silver saat ini **tidak dapat membuktikan** bahwa suatu piksel valid
unburned, missing, water, atau QA-insufficient. Ini adalah gap utama terhadap
keputusan QA/coverage konservatif.

### 3.2 Data aktual

| Dataset | Nilai |
|---|---|
| `hotspot_scar_label` | 483.584 event; unik per `event_id` |
| Tier | kuat 47.045; sedang 19.789; lemah 14.201; kandidat 402.549 |
| Gap null | 392.289 event |
| `mcd64a1_burn_scar` | 59.454 baris; 10 tile; 1 Agu–30 Sep 2026 |
| `mcd64a1_coverage` | 34 baris = 17 tile × Agustus/September |
| QA pada `burn_scar` | QA 3 = 56.763; QA 11 = 2.678; QA 7 = 13 |
| QA pada confirmed | QA 3 = 65.349; QA 11 = 1.477; QA 7 = 8 |
| Uncertainty confirmed | median 4; p90 13; p99 23; maks 45 |
| First/Last width confirmed | median 56; p90 67; p99 72 hari |
| Gold total | 34.460 baris; 2.963 sel; 30 tanggal |
| Gold complete | 26.682 baris; positive 3.782; negative 22.900 |
| Gold incomplete | 7.778 baris; 701 sementara label 1; 7.077 label 0 |

Decode QA yang teramati: semua nilai memiliki bit0=1 (land) dan bit1=1 (valid);
QA 3 tanpa bit tambahan; QA 7 menandai shortened mapping period; QA 11 menandai
class updated during contextual relabeling. Tidak ada special-condition bits
5–7 pada baris `burn_scar` (burned cells memang memiliki kode 0). Ini **bukan**
bukti bahwa piksel unburned valid; piksel unburned tidak disimpan.

### 3.3 Rekonsiliasi mekanisme

Rekonstruksi ulang dari Silver + coverage dibandingkan dengan Gold:

- `label`: 0 mismatch;
- `label_complete`: 0 mismatch;
- `n_hotspot`: 0 mismatch;
- `n_hotspot = audit_n_confirmed + audit_n_weak + audit_n_candidate`: 0
  mismatch pada baris complete.

Mekanisme inti konsisten; gap ada pada status/QA/lineage, bukan pada agregasi
dasar.

## 4. Temuan QA dan observation coverage

| Temuan | Status |
|---|---|
| Burn Date 0/-1/-2 tidak disimpan di Silver | BLOCKER untuk negative berbasis piksel |
| QA untuk piksel unburned tidak tersedia | BLOCKER untuk negative berbasis piksel |
| `first_day`/`last_day` hanya untuk piksel terbakar | BLOCKER untuk observation coverage per piksel |
| `coverage` tile/bulan hanya membuktikan granule tersedia | PROPOSED: tidak cukup untuk negative final |
| QA bit2/bit3 dan uncertainty belum dipetakan ke policy | PENDING EVIDENCE |
| Water/missing/QA invalid tidak dibedakan dari unburned | BLOCKER untuk label negative |
| Batas bulan/tahun belum diuji | PENDING EVIDENCE |

Policy operasional yang diusulkan ada di `docs/ml-label-contract.md` §3,
status **PROPOSED**. Tanpa data status piksel, policy tersebut belum dapat
diimplementasikan.

## 5. Deterministic tie-break

Field yang tersedia:

- `gap_days` absolute;
- `burn_date`;
- `tile`, `pixel_row`, `pixel_col`;
- `source_file` di `mcd64a1_burn_scar`, tetapi belum di label.

Usulan final:

1. `abs(gap_days)` ascending.
2. `burn_date` ascending.
3. `burn_scar_key` ascending.

`source_file` tidak dijadikan tie-break utama karena memuat production
timestamp dan dapat berubah saat reprocessing. Ia disimpan sebagai metadata.

Baseline: 35 event memiliki tie gap terdekat; 516 event confirmed memiliki dua
scar dalam ±7. Tie-break membuat pemilihan reproducible, tetapi `tie_count`
harus tetap dilaporkan sebagai ambiguitas ilmiah.

Status: **PROPOSED — butuh persetujuan urutan.**

## 6. Candidate reason dan lineage

Candidate saat ini mencampur:

- 392.289 event tanpa scar;
- 10.260 event dengan scar >14 hari.

Kontrak usulan:

- event-level `candidate_reason` = `no_scar_match` atau
  `scar_outside_window`;
- cell-day-level dua count terpisah:
  `audit_n_candidate_no_scar` dan `audit_n_candidate_outside_window`;
- `no_scar_match` hanya sah jika piksel valid unburned; jika coverage/QA tidak
  memadai, statusnya incomplete.

Lineage usulan:

- `burn_scar_key = tile|pixel_row|pixel_col|burn_date`;
- `hotspot_scar_label` menyimpan `cell_id`, key, `match_rank`, `tie_count`,
  `n_candidate_scars`, QA/uncertainty/first/last, dan `source_file` sebagai
  metadata;
- Gold diaudit dengan join `hotspot_scar_label` pada `cell_id,date`;
- tabel kandidat alternatif bersifat opsional di fase berikutnya.

Status: **PROPOSED.**

## 7. Fingerprint dan label rule version

Usulan fingerprint v2:

- field core: `cell_id`, `date`, `label`, `label_status`, `label_complete`;
- urut berdasarkan `cell_id`, `date`;
- NULL direpresentasikan konsisten;
- tanpa `generated_at`/timestamp runtime;
- SHA-256;
- candidate counts/audit tier tidak masuk core; bila perlu, buat
  `audit_fingerprint` terpisah.

`label_rule_version` disimpan terpisah; usulan nama `temporal-label-v1` masih
**PROPOSED**. Komponen versi: ±7, tier, weak/candidate, candidate reason,
QA/coverage policy, tie-break, agregasi cell-day, status, fingerprint scheme.

## 8. Hasil pemeriksaan October 2026

### 8.1 Local repository

- Tidak ada direktori/berkas dengan tanggal 2026-10 di `data/`.
- `mcd64a1_coverage` hanya memiliki period `2026-08` dan `2026-09`.
- `mcd64a1_burn_scar` berakhir 2026-09-30.
- Tidak ada granule October di Bronze/Silver lokal.

### 8.2 CMR metadata

Query read-only CMR untuk collection `C2565786756-LPCLOUD` dengan temporal
2026-10-01 sampai 2026-10-31:

```text
https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id=C2565786756-LPCLOUD&temporal=2026-10-01T00:00:00Z,2026-10-31T23:59:59Z&page_size=100
```

Hasil: `entry: []` (tidak ada granule) pada 2026-11-21. Query September
mengembalikan granule, sehingga koleksi dan query bekerja.

### 8.3 Kebutuhan tile

Hotspot 24–30 September membutuhkan 12 tile:

`h27v08`, `h28v08`, `h28v09`, `h29v08`, `h29v09`, `h29v10`, `h30v08`,
`h30v09`, `h30v10`, `h31v08`, `h31v09`, `h32v09`.

Window ±7 untuk 24–30 September membutuhkan September dan October. September
tersedia; October tidak.

### 8.4 Kesimpulan

**NOT AVAILABLE** untuk October 2026 berdasarkan bukti repository dan CMR pada
21 November 2026.

Konsekuensi:

- 24–30 September tetap `incomplete`; `label=NULL`, tidak boleh menjadi 0.
- Jangan melakukan backfill atau menganggap satu file cukup.
- Jika October tersedia kemudian, perlu seluruh 12 tile dan validasi coverage/QA
  sebelum dipakai.

## 9. Keputusan yang sudah APPROVED

1. Temporal matching symmetric ±7.
2. Strong/medium = positive.
3. Weak/candidate = negative.
4. Incomplete = NULL + `label_status='incomplete'`.
5. Nearest scar + deterministic tie-break (urutan tie masih PROPOSED).
6. Exact-pixel, tanpa buffer.
7. `audit_tier_max` ordinal.
8. Fingerprint v2 + rule version terpisah.
9. October conditional.
10. ML loader minimal nullable/status.
11. Periode eksperimen 1–30 September 2026.

## 10. Keputusan yang masih PROPOSED/PENDING/BLOCKED

| Hal | Status |
|---|---|
| QA bit2/bit3 dan threshold uncertainty | PROPOSED/PENDING EVIDENCE |
| Sumber status piksel unburned/missing/water | PENDING EVIDENCE / BLOCKER |
| Nama field candidate/lineage/fingerprint | PROPOSED |
| Urutan tie-break final | PROPOSED |
| Nilai `label_rule_version` | PROPOSED |
| Apakah `label_complete` dipertahankan | PROPOSED (disarankan ya) |
| Tabel kandidat alternatif | PROPOSED |
| October 2026 | BLOCKED (tidak tersedia) |

## 11. Exit gate Batch 1

| Kriteria | Status | Bukti |
|---|---|---|
| QA MCD64A1 punya referensi resmi | PASS | File Specification + product page |
| Aturan validitas/coverage operasional | PASS sebagai PROPOSED | `ml-label-contract.md` §3 |
| Perbedaan unburned/missing/water/QA/coverage | PASS | Tabel status piksel |
| Kebutuhan granule ±7 lintas bulan/tahun | PASS | §3.4; data 24–30 Sep butuh October |
| Tie-break deterministik + bukti field | PASS sebagai PROPOSED | §5 |
| Candidate reason event/cell | PASS sebagai PROPOSED | §6 |
| Lineage konseptual | PASS sebagai PROPOSED | §6 |
| Fingerprint/rule version | PASS sebagai PROPOSED | §7 |
| October berdasarkan bukti aktual | PASS | CMR `entry: []`; local absen |
| Kontrak Gold/loader nullable | PASS sebagai PROPOSED | `ml-label-contract.md` §7–9 |
| Tidak ada perubahan kode/data | PASS | Hanya dokumen baru |
| Status usulan tercatat | PASS | Tabel status |
| Batch 2 readiness eksplisit | PASS | Lihat §12 |

## 12. Batch 2 readiness

**NOT READY untuk Batch 2 penuh.**

Alasan:

1. Policy QA/observation coverage masih PROPOSED dan belum disetujui.
2. Data Silver saat ini tidak menyimpan status piksel unburned/missing/water/QA;
   negative berbasis piksel belum dapat diimplementasikan.
3. Urutan tie-break, nama field, fingerprint, dan nilai rule version masih
   PROPOSED.
4. October tidak tersedia; 24–30 September tetap incomplete (bukan blocker untuk
   1–23 September, tetapi blocker untuk penerimaan periode penuh).
5. `label_rule_version` dan `label_status` belum diimplementasikan; itu memang
   Batch 2–4.

Batch 2 boleh dimulai **hanya** setelah pengguna menyetujui:

- policy QA/coverage dan opsi sumber data status piksel (Opsi A disarankan);
- urutan tie-break;
- nama field candidate/lineage/fingerprint;
- keputusan mempertahankan `label_complete`;
- apakah Batch 2 dimulai sebagai field additive Silver tanpa mengubah label Gold
  (disarankan) atau langsung menyertakan perluasan coverage/QA.

## 13. Risiko dan keterbatasan

- QA MCD64A1 tidak dapat ditafsirkan hanya dari frekuensi nilai; policy harus
  mengikuti dokumentasi resmi.
- Negative saat ini masih berbasis granule, bukan validitas piksel.
- `source_file` tidak stabil sebagai identitas lintas reprocessing.
- October tidak tersedia; jangan memaksa label 24–30 September.
- Perubahan label nanti bersifat breaking; artefak model lama tidak boleh
  dipakai untuk label baru.
- Rebuild akan menimpa output Gold; snapshot/versioning diperlukan di Batch 5.

## 14. Validasi

Batch 1 hanya membuat dokumen; tidak ada kode produksi/data yang berubah.
Baseline test Batch 0 tetap berlaku: 331 unit test passed; 1 integration test
gagal karena Garage tidak aktif; `ruff` passed. Tidak ada test suite yang
dijalankan ulang pada Batch 1 karena tidak ada perubahan kode.
