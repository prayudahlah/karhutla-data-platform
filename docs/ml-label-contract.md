# Kontrak Label Temporal Phase 01

Status: kontrak kerja Phase 01. Keputusan yang sudah disetujui mengacu ke
`docs/adr/ADR-008-phase-01-label-contract.md`; bukti audit ada di
`docs/ml-phase-01-batch-1-audit.md`.

Legenda status:

| Status | Arti |
|---|---|
| APPROVED | Sudah disetujui pengguna; jangan diubah sepihak |
| PROPOSED | Rekomendasi teknis yang belum disetujui |
| PENDING EVIDENCE | Memerlukan dokumentasi/audit tambahan |
| BLOCKED | Tidak dapat dipastikan dengan data saat ini |

## 1. Invarian yang disetujui

| Aturan | Status |
|---|---|
| Temporal matching symmetric ±7 hari | APPROVED |
| Strong 0–3 hari = label 1 | APPROVED |
| Medium 4–7 hari = label 1 | APPROVED |
| Weak 8–14 hari = label 0 | APPROVED |
| Candidate >14 hari atau tanpa match = label 0 | APPROVED |
| Incomplete = `label=NULL`, `label_status='incomplete'` | APPROVED |
| Nearest scar + deterministic tie-break | APPROVED (urutan tie PROPOSED) |
| Exact-pixel spatial matching, tanpa buffer | APPROVED |
| `audit_tier_max` ordinal Strong > Medium > Weak > Candidate | APPROVED |
| Fingerprint v2 + `label_rule_version` terpisah | APPROVED (field PROPOSED) |
| ML loader minimal untuk label nullable/status | APPROVED |
| Periode eksperimen 1–30 September 2026 | APPROVED |

## 2. Semantik resmi MCD64A1

Referensi resmi:

- NASA LP DAAC, MCD64A1 v061:
  <https://www.earthdata.nasa.gov/data/catalog/lpcloud-mcd64a1-061>
- DOI: <https://doi.org/10.5067/MODIS/MCD64A1.061>
- MCD64 User Guide V6.1:
  <https://lpdaac.usgs.gov/documents/1006/MCD64_User_Guide_V61.pdf>
- MODIS L3 Monthly 500m Burned Area Product File Specification v6.0.7:
  <https://ladsweb.modaps.eosdis.nasa.gov/filespec/MODIS/61/MCD64A1>

### 2.1 Burn Date

| Nilai | Arti |
|---|---|
| 1–366 | Ordinal day of burn pada bulan produk |
| 0 | Unburned |
| -1 | Missing data |
| -2 | Water |

Sumber: File Specification MCD64A1 v6.0.7, Scientific Data Sets, Burn Date.

### 2.2 QA

QA adalah bit field 8-bit:

| Bit | Arti |
|---:|---|
| 0 | Land/water: 0 = water, 1 = land |
| 1 | Valid data: 0 = missing, 1 = valid |
| 2 | Shortened mapping period: 0 = false, 1 = true |
| 3 | Class updated during contextual relabeling: 0 = false, 1 = true |
| 4 | Unused, set 0 |
| 5–7 | Unburned special-condition code: 0 none/not applicable; 1 valid observations too sparse; 2 too few training observations; 3 apparent burn date at limits of time series; 4 persistent water contamination; 5 persistent hotspot |

Bit 5–7 hanya menjelaskan piksel yang diklasifikasikan “unburned” karena
kondisi khusus. Burned, missing, dan water cells memiliki kode 0.

Sumber: File Specification MCD64A1 v6.0.7, Scientific Data Sets, QA.

### 2.3 Uncertainty

`Burn Date Uncertainty` adalah ketidakpastian temporal tanggal terbakar dalam
satuan hari. Nilai ini tidak boleh ditafsirkan sebagai skor kualitas biner.

Sumber: File Specification MCD64A1 v6.0.7, Scientific Data Sets, Burn Date
Uncertainty.

### 2.4 First Day dan Last Day

`First Day` dan `Last Day` adalah hari pertama dan terakhir reliable change
detection pada tahun produk. `valid_range` 1–366, `_FillValue=-1`,
`water=-2`.

Keduanya relevan untuk observation coverage: jika rentang `first_day`–`last_day`
tidak mencakup `d-7` sampai `d+7`, pixel tidak boleh dipakai untuk menyimpulkan
negative pada window tersebut.

Sumber: File Specification MCD64A1 v6.0.7, Scientific Data Sets, First Day dan
Last Day.

### 2.5 Granule metadata yang tersedia tetapi belum dipakai

File Specification mencantumkan metadata granule:

- `BurnedCells`
- `MissingCells`
- `LandCells`
- `ValidLandCells`
- `ProductStartDay`
- `ProductEndDay`

Metadata ini berguna untuk audit coverage tingkat granule, tetapi **tidak
menggantikan validitas per piksel**.

## 3. Policy QA dan Observation Coverage

**Status: PROPOSED — memerlukan persetujuan dan data tambahan.**

### 3.1 Klasifikasi status piksel

| Status usulan | Kondisi | Boleh untuk positive? | Boleh untuk negative? |
|---|---|---|---|
| `burned_valid` | Burn Date 1–366; QA bit1=1; QA bit0=1; tanggal dalam bulan produk; metadata observasi valid | Ya, jika gap ≤7 | Tidak (sudah burned) |
| `unburned_valid` | Burn Date 0; QA bit1=1; QA bit0=1; QA bit5–7=0; `first_day ≤ d-7` dan `last_day ≥ d+7` | Tidak | Ya |
| `burned_outside_window` | Burn Date valid; gap >7; QA/observasi valid | Tidak | Ya untuk window ini |
| `missing` | Burn Date -1 atau QA bit1=0 | Tidak | Tidak |
| `water` | Burn Date -2 atau QA bit0=0 | Tidak | Tidak |
| `qa_insufficient` | QA bit1=0, atau QA bit5–7 ∈ {1..5}, atau kondisi QA lain yang disetujui | Tidak | Tidak |
| `observation_insufficient` | `first_day`/`last_day` tidak mencakup `d-7..d+7` | Tidak | Tidak |
| `unknown` | Metadata tidak cukup untuk memutuskan | Tidak | Tidak |

Catatan:

- `shortened mapping period` (QA bit2) dan `class updated` (QA bit3) belum
  diputuskan apakah otomatis `qa_insufficient`; ini **PROPOSED/PENDING
  EVIDENCE**. Jangan menganggap bit2/bit3 otomatis invalid.
- `uncertainty` belum ditetapkan threshold; jangan mengubahnya menjadi filter
  tanpa approval.
- Water tidak boleh dipakai sebagai bukti negative untuk kebakaran; hotspot di
  water adalah kasus terpisah yang harus diaudit.

### 3.2 Aturan label yang diusulkan

- **Positive:** ada minimal satu event dengan `burned_valid` dan gap ≤7.
- **Negative:** semua event dievaluasi; tidak ada positive; setiap event
  memiliki status piksel valid (`unburned_valid` atau `burned_outside_window`)
  dan observation coverage mencakup `d-7..d+7`.
- **Incomplete:** ada minimal satu event dengan `missing`, `water`,
  `qa_insufficient`, `observation_insufficient`, atau `unknown`; incomplete
  memiliki prioritas atas positive/negative sesuai keputusan approved.
- **Candidate reason:** hanya diberikan pada negative event yang valid:
  `no_scar_match` bila tidak ada scar pada piksel valid;
  `scar_outside_window` bila ada scar tetapi gap >14.

### 3.3 Kesenjangan data saat ini

Status: **PENDING EVIDENCE / BLOCKER untuk negative berbasis piksel.**

`src/batch/silver/mcd64a1.py` hanya menyimpan baris dengan Burn Date >0:

- `parse_tile` menghitung `inside = (burn >= first_doy) & (burn <= last_doy)`;
- hanya `inside` yang ditulis ke `burn_scar`;
- Burn Date 0/-1/-2 tidak disimpan;
- `coverage` hanya menyimpan `pixels_burned` dan `pixels_outside_month`;
- `ValidLandCells`, `LandCells`, `MissingCells`, `ProductStartDay`, dan
  `ProductEndDay` tidak dibaca;
- `first_day`/`last_day` hanya tersedia untuk piksel terbakar.

Konsekuensinya:

1. Tidak ada bukti per piksel bahwa piksel **valid unburned**.
2. Tidak bisa membedakan “tidak ada scar karena memang tidak terbakar” dari
   “tidak ada scar karena missing/water/QA buruk”.
3. `label_complete` tile/bulan hanya membuktikan granule tersedia, bukan
   validitas piksel.
4. Negative saat ini adalah **negative berbasis ketersediaan granule**, belum
   negative berbasis validitas piksel.

Rekomendasi implementasi (PROPOSED, Batch 2/3):

- Opsi A (disarankan): tambah tabel/status per piksel hotspot. Saat normalisasi
  500 m, baca Burn Date/QA/Uncertainty/First Day/Last Day untuk setiap piksel
  hotspot yang benar-benar dipakai; simpan status piksel per `tile`,
  `pixel_row`, `pixel_col`, `period`. Ini cukup untuk audit negative tanpa
  menyimpan seluruh raster.
- Opsi B: simpan seluruh piksel land di bbox. Mahal dan tidak proporsional.
- Opsi C: hanya metadata granule (`ValidLandCells`). Tidak cukup untuk
  kesimpulan per piksel; hanya untuk audit coverage.

Tanpa Opsi A (atau setara), Batch 2 tidak boleh mengklaim negative sudah
memenuhi keputusan QA/coverage.

### 3.3.1 Cakupan spasial Burn Scar

Sejak remediation Batch 2B, Burn Scar memakai definisi **pixel footprint
intersects bbox**, bukan pixel center:

- CRS: MODIS Sinusoidal, sphere radius `6.371.007,181 m`.
- Resolusi native: `463,312717 m`.
- Footprint dihitung dari empat sudut pixel pada grid tile (`ulx`, `uly`,
  `px`, `py`, `nx`, `ny`).
- Sudut ditransformasi dengan inverse sinusoidal yang sama dengan Batch 2A.
- Intersection memakai closed polygon–rectangle intersection; touch boundary
  dianggap beririsan.
- Tidak ada buffer, padding, atau toleransi koordinat arbitrer.
- Kolom audit `in_bbox` tetap berarti pixel center; filter publik memakai
  `footprint_intersects_bbox`.

### 3.4 Batas bulan dan tahun

Window `d-7..d+7` dapat melintasi bulan dan tahun. Pemeriksaan granule harus
memakai bulan kalender dari setiap batas:

- `d-7` dapat berada di bulan sebelumnya (contoh 3 September → Agustus).
- `d+7` dapat berada di bulan berikutnya (contoh 28 September → Oktober).
- 1 Januari dan 31 Desember harus diuji secara eksplisit.

`first_day`/`last_day` adalah day-of-year pada tahun produk, bukan tanggal
absolut. Untuk window yang melintasi tahun, coverage harus memakai granule dari
kedua tahun dan membandingkan tanggal kalender; jangan membandingkan DOY 350
dengan DOY 5 seolah-olah berurutan.

`gold_hotspot_cell_day.sql` sudah membentuk `needed_periods` dari
`strftime(date ± 7, '%Y-%m')`; ini benar secara konsep, tetapi belum diuji untuk
batas tahun dan belum memasukkan validitas piksel.

## 4. Kontrak event-level Silver

Tabel: `hotspot_scar_label` (satu baris per `event_id`).

Status: **PROPOSED untuk field baru; APPROVED untuk satu baris per event.**

Field yang sudah ada:

`event_id`, `date`, `tile`, `pixel_row`, `pixel_col`, `burn_date`,
`gap_days`, `tier`.

Field tambahan yang diusulkan:

| Field | Arti | Status |
|---|---|---|
| `cell_id` | cell 0,25° hasil floor(lat/0.25), floor(lon/0.25) | PROPOSED |
| `burn_scar_key` | `tile|pixel_row|pixel_col|burn_date` | PROPOSED |
| `candidate_reason` | `no_scar_match` / `scar_outside_window`; NULL untuk non-candidate | PROPOSED |
| `burned_without_scar_candidate` | audit flag; burned usable observation tanpa matching scar | BUILD 2B |
| `n_candidate_scars` | jumlah scar pada piksel yang dipertimbangkan | PROPOSED |
| `match_rank` | ranking kandidat; 1 = scar terpilih | PROPOSED |
| `tie_count` | jumlah kandidat dengan gap absolut minimum yang sama | PROPOSED |
| `qa` | QA piksel/scar terpilih | PROPOSED |
| `uncertainty` | uncertainty scar terpilih | PROPOSED |
| `first_day`, `last_day` | reliable change window scar/piksel | PROPOSED |
| `source_file` | metadata sumber; bukan identitas utama | PROPOSED |

### 4.1 Tie-break deterministik

Field yang tersedia:

- `gap_days` (absolute).
- `burn_date`.
- `tile`, `pixel_row`, `pixel_col` (identitas piksel).
- `source_file` (di `mcd64a1_burn_scar`, belum di label).

Urutan usulan:

1. `abs(gap_days)` ascending.
2. `burn_date` ascending.
3. `burn_scar_key` ascending (praktis sama dengan burn_date pada piksel yang
   sama).
4. `source_file` hanya untuk audit, bukan tie-break utama.

Alasan:

- `burn_date` deterministik dan unik per piksel pada `mcd64a1_burn_scar`
  (tes unique pixel/date).
- `source_file` memuat production timestamp; bisa berubah saat reprocessing,
  jadi tidak stabil sebagai identitas.
- Urutan ini tidak bergantung pada urutan fisik data.

Status: **PROPOSED — butuh persetujuan urutan.**

### 4.2 Arti metadata kandidat

- `n_candidate_scars`: jumlah scar pada piksel yang masuk join sebelum
  pemilihan (semua tanggal scar pada piksel tersebut).
- `match_rank`: 1 untuk scar terpilih; 2..n untuk alternatif bila disimpan.
- `tie_count`: jumlah scar dengan `abs(gap_days)` minimum yang sama; nilai >1
  menandakan ambiguitas ilmiah yang harus dilaporkan.
- `burn_scar_key`: identitas stabil hasil komposit; bukan nama file.

Tie-break deterministik tidak menghilangkan ambiguitas; ia hanya membuat
pemilihan dapat direproduksi.

## 5. Candidate reason

Status: **PROPOSED — nama field dan agregasi butuh persetujuan.**

### 5.1 Event-level

`candidate_reason` hanya diisi untuk event dengan `tier='kandidat'` dan label
0 yang **dapat dievaluasi**:

| Nilai | Kondisi |
|---|---|
| `no_scar_match` | Tidak ada scar pada piksel, dan piksel valid unburned/coverage cukup |
| `scar_outside_window` | Ada scar pada piksel, tetapi tidak ada yang ≤7 hari; nearest gap >14 |

Jika coverage/QA tidak memadai, event harus menjadi **incomplete**, bukan
`candidate_reason`; jangan memakai `no_scar_match`.

Event `lemah` (8–14 hari) bukan candidate; ia tetap tier weak, label 0, dan
`candidate_reason` NULL.

Defensive guard: jika required observation berstatus `burned` dan usable,
source tersedia, `burn_date_code` valid, tetapi tidak ada Burn Scar dengan
`tile + pixel_row + pixel_col + burn_date` yang sama, event harus menjadi
**incomplete**. Primary reason adalah `required_evidence_incomplete`.
Penyebab spesifik dicatat pada audit flag `burned_without_scar_candidate`.
`candidate_insufficient` tidak diperluas untuk kasus tanpa candidate row;
flag itu tetap berarti ada candidate row yang insufficient.

### 5.2 Cell-day-level

Gunakan dua kolom count terpisah, bukan satu alasan tunggal:

- `audit_n_candidate_no_scar`
- `audit_n_candidate_outside_window`

Jika satu cell-day memiliki keduanya, isi keduanya. Jangan memaksakan satu
alasan.

## 6. Lineage Burn Scar

Status: **PROPOSED; arah lineage disetujui, tabel final belum.**

Rekomendasi:

- Simpan lineage utama di `hotspot_scar_label` (satu baris per event) dengan
  `cell_id`, `burn_scar_key`, `match_rank`, `tie_count`, `n_candidate_scars`,
  dan metadata scar.
- `burn_scar_key` = `tile|pixel_row|pixel_col|burn_date`.
- Jangan memakai `source_file` sebagai identitas; simpan hanya sebagai metadata.
- Gold cell-day dapat diaudit dengan join `hotspot_scar_label` pada
  `cell_id,date`.
- Jika audit membutuhkan seluruh alternatif, buat tabel kandidat terpisah
  (`event_id`, `burn_scar_key`, `gap_days`, `match_rank`) di fase berikutnya;
  jangan membebani tabel label utama.

Keunikan saat ini: `hotspot_scar_label` 483.584 baris, unik per `event_id`;
`mcd64a1_burn_scar` 59.454 baris, unik per tile/pixel/date.

## 7. Kontrak Gold cell-day

Status: **APPROVED untuk semantik; PROPOSED untuk field baru.**

| Kolom | Nilai | Aturan |
|---|---|---|
| `label` | 1 / 0 / NULL | 1 positive; 0 negative; NULL incomplete |
| `label_status` | `positive` / `negative` / `incomplete` | status utama |
| `label_complete` | TRUE / FALSE | derived: TRUE bila status positive/negative, FALSE bila incomplete |
| `audit_n_confirmed` | count | jumlah event kuat/sedang |
| `audit_n_weak` | count | jumlah event lemah |
| `audit_n_candidate_no_scar` | count | candidate valid tanpa scar |
| `audit_n_candidate_outside_window` | count | candidate valid dengan scar >14 |
| `audit_tier_max` | ordinal | Strong > Medium > Weak > Candidate |

Aturan konsistensi:

- `label_status='incomplete'` ⇔ `label IS NULL` ⇔ `label_complete=FALSE`.
- `label_status='positive'` ⇔ `label=1` dan `label_complete=TRUE`.
- `label_status='negative'` ⇔ `label=0` dan `label_complete=TRUE`.
- `label_complete` dipertahankan sebagai derived boolean untuk audit dan
  kompatibilitas; bukan sumber kebenaran independen.
- Incomplete memiliki prioritas: cell-day dengan minimal satu event yang tidak
  dapat dievaluasi menjadi incomplete, meskipun ada event positive.

## 8. Fingerprint dan label rule version

Status: **APPROVED konsep; PROPOSED field/nilai.**

### 8.1 Fingerprint v2

Usulan field core:

- `cell_id`
- `date`
- `label`
- `label_status`
- `label_complete`

Aturan:

- Urutkan berdasarkan `cell_id`, lalu `date`.
- Representasi NULL konsisten (misalnya token `<NULL>`), bukan string kosong
  yang ambigu.
- Jangan masukkan `generated_at`, timestamp eksekusi, atau metadata runtime.
- Hash SHA-256 dari serialisasi deterministik.
- Berubah jika label/status/complete berubah.

Metadata audit seperti candidate counts dan `audit_tier_max` **tidak masuk
fingerprint core**; bila diperlukan, buat `audit_fingerprint` terpisah. Ini
mencegah fingerprint target berubah hanya karena audit metadata berubah.

### 8.2 Label rule version

Usulan nilai: `temporal-label-v1` — **PROPOSED, belum final.**

Komponen yang dicakup:

- symmetric ±7;
- tier strong/medium/weak/candidate;
- weak/candidate = 0;
- candidate reason;
- QA/observation coverage policy;
- tie-break;
- cell-day aggregation;
- label status;
- fingerprint scheme.

`label_rule_version` disimpan terpisah dari fingerprint, misalnya di manifest
dataset dan metadata run, bukan di setiap baris Gold.

## 9. ML loader contract

Status: **APPROVED untuk perilaku; implementasi Batch 4.**

| Status | `label` | Training/evaluation |
|---|---|---|
| positive | 1 | diterima |
| negative | 0 | diterima |
| incomplete | NULL | tidak boleh masuk; bukan 0 |

Aturan:

- `require_complete=True` membuang incomplete sebelum target dibuat.
- Target training selalu 0/1; tidak boleh NULL.
- `require_complete=False` hanya untuk audit; tidak boleh diam-diam
  mengembalikan NULL ke proses training. Perilaku harus eksplisit dan diuji.
- Jangan mengubah fitur, preprocessing, split, atau model.

## 10. Keputusan yang masih terbuka

| Hal | Status |
|---|---|
| Threshold/interpretasi QA bit2/bit3 dan `uncertainty` | PROPOSED/PENDING EVIDENCE |
| Sumber data status piksel unburned/missing/water | PENDING EVIDENCE / BLOCKER |
| Nama final field candidate/lineage/fingerprint | PROPOSED |
| Urutan tie-break final | PROPOSED |
| Nilai `label_rule_version` | PROPOSED |
| Apakah `label_complete` dipertahankan | PROPOSED (disarankan ya) |
| Apakah tabel kandidat alternatif diperlukan | PROPOSED |
| October 2026 | BLOCKED (tidak tersedia per 21 Nov 2026) |
