# ADR-008: Kontrak label temporal Phase 01

## Status

Accepted sebagian, 21 November 2026. Keputusan metodologis 1–6 dan 8–15
disetujui pengguna; arah keputusan 7 (QA/observation coverage konservatif) juga
disetujui, tetapi aturan rinci dan beberapa nama field masih berstatus
**PROPOSED** atau **PENDING EVIDENCE**. Lihat tabel status di bawah.

Dokumen ini adalah decision record Phase 01. Kontrak teknis lengkap ada di
`docs/ml-label-contract.md`; bukti audit dan status Batch 1 ada di
`docs/ml-phase-01-batch-1-audit.md`.

## Context

Phase 01 memperbaiki keandalan label `hotspot_cell_day` sebelum eksperimen ML.
Audit Batch 0 menemukan:

- temporal matching sudah symmetric ±7 hari;
- `label` Gold masih 0/1 untuk baris incomplete;
- `label_complete` tersedia, tetapi bukan status eksplisit;
- `kandidat` mencampur “tidak ada scar” dan “scar di luar window”;
- `audit_tier_max` memakai `max(tier)` leksikografis, bukan ordinal;
- `mcd64a1_burn_scar` hanya menyimpan piksel terbakar, sehingga validitas
  piksel unburned/missing/water tidak dapat dibuktikan dari Silver saat ini;
- October 2026 belum tersedia, sehingga 24–30 September belum lengkap.

## Decision

1. **Temporal matching tetap symmetric ±7 hari.** Tidak ada perubahan one-way.
2. **Strong 0–3 hari = label 1.**
3. **Medium 4–7 hari = label 1.**
4. **Weak 8–14 hari = label 0.**
5. **Candidate >14 hari atau tidak ada kecocokan = label 0.**
6. **Incomplete:** `label = NULL` dan `label_status = 'incomplete'`; incomplete
   tidak boleh masuk training/evaluasi sebagai negative.
7. **QA/observation coverage MCD64A1:** pendekatan konservatif. Aturan
   operasional rinci ada di `docs/ml-label-contract.md` dan berstatus
   **PROPOSED** sampai disetujui. Data Silver saat ini belum menyimpan status
   piksel unburned, missing, water, dan QA untuk piksel non-terbakar.
8. **Candidate reason:** `no_scar_match` dan `scar_outside_window`; keduanya
   tetap tier kandidat dan label 0. `no_scar_match` hanya boleh dipakai bila
   piksel benar-benar tervalidasi tidak terbakar; jika coverage/QA tidak
   memadai, statusnya incomplete, bukan candidate.
9. **Nearest scar:** tetap aturan utama; tie-break deterministik memakai
   absolute gap, lalu `burn_date`, lalu identitas scar. Metadata kandidat, rank,
   dan tie disimpan.
10. **Spatial matching:** exact pixel (`tile`, `pixel_row`, `pixel_col`); tanpa
    buffer.
11. **`audit_tier_max`:** ordinal Strong > Medium > Weak > Candidate.
12. **Fingerprint:** fingerprint v2 mencakup output labeling yang relevan;
    `label_rule_version` disimpan terpisah. Field final masih **PROPOSED**.
13. **October 2026:** boleh dipakai untuk melengkapi 24–30 September hanya jika
    tersedia dan memenuhi coverage policy. Per 21 November 2026, October belum
    tersedia di CMR dan repository lokal.
14. **ML loader:** perubahan minimal untuk label nullable dan `label_status`;
    fitur, preprocessing, split, dan model tidak berubah.
15. **Strict acceptance:** semua kriteria kritis Phase 01 wajib lulus sebelum
    fase ditutup. Periode eksperimen tetap 1–30 September 2026; backfill October
    tidak memperluas periode.

## Status keputusan

| Keputusan | Status | Catatan |
|---|---|---|
| Symmetric ±7 | APPROVED | Implementasi saat ini sudah sesuai |
| Strong/medium = 1 | APPROVED | Implementasi saat ini sudah sesuai |
| Weak/candidate = 0 | APPROVED | Implementasi saat ini sudah sesuai |
| Incomplete NULL + status | APPROVED | Perlu implementasi Batch 4 |
| QA/coverage konservatif | APPROVED arah; PROPOSED rinci | Perlu approval policy dan data piksel |
| Candidate reason | APPROVED konsep; PROPOSED nama field | Perlu implementasi Batch 2/3 |
| Nearest + tie-break | APPROVED konsep; PROPOSED urutan tie | Perlu approval urutan |
| Exact pixel | APPROVED | Implementasi saat ini sudah sesuai |
| `audit_tier_max` ordinal | APPROVED | Perlu implementasi Batch 3 |
| Fingerprint v2 + rule version | APPROVED konsep; PROPOSED field/nilai | Perlu approval |
| October conditional | APPROVED konsep; BLOCKED data | CMR tidak memiliki granule October |
| Loader minimal | APPROVED | Perlu implementasi Batch 4 |
| Strict acceptance | APPROVED | Semua kriteria kritis wajib lulus |
| Periode 1–30 Sep | APPROVED | Tidak diperluas |

## Consequences

- Label Gold akan berubah secara breaking: incomplete menjadi NULL dan memiliki
  status eksplisit.
- Artefak model lama tidak boleh dianggap merepresentasikan label baru.
- Batch 2 belum dapat memfinalkan label negatif berbasis QA piksel sampai
  policy QA/coverage dan sumber data status piksel disetujui.
- October tidak tersedia; 24–30 September harus tetap incomplete sampai data
  yang memenuhi policy tersedia.
- Tie-break deterministik mengurangi ambiguitas eksekusi, tetapi tidak
  menghilangkan ambiguitas ilmiah; `tie_count` harus tetap dicatat.

## Alternatives

- **Memakai label 0 untuk incomplete.** Ditolak: melanggar keputusan approved
  dan berisiko false negative.
- **Memakai tile/bulan sebagai bukti negative piksel.** Ditolak untuk label
  final: tile/bulan hanya membuktikan granule tersedia, bukan validitas piksel.
- **Menambahkan spatial buffer.** Ditolak: spatial matching tetap exact pixel.
- **Menggunakan October tanpa audit coverage.** Ditolak: tidak boleh menganggap
  satu file cukup.

## Links

- `docs/ml-label-contract.md`
- `docs/ml-phase-01-batch-1-audit.md`
- `docs/data-contracts/README.md`
