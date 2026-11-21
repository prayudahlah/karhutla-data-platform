# ADR-007: Baseline temporal penuh (C=10) dan penutupan eksperimen spasial

## Status

Accepted, 17 November 2026. Menggantikan sebagian ADR-006 (bagian C=1 sebagai
konfigurasi kerja).

## Context

Dua jalur eksperimen sudah dijalankan:

1. **Temporal**: baseline LR pada sel-hari dengan test 19–23 September.
   Konfigurasi C=10 + VIF protected memberi PR-AUC valid 0,6820 dan test
   0,6311. Ini satu-satunya konfigurasi yang punya angka test.
2. **Spatial holdout**: empat fold (Kalimantan, Sumatra, Papua, Maluku).
   Model penuh hanya mencapai PR-AUC rata-rata 0,491, di bawah baseline
   `n_hotspot` (0,552) dan varian tanpa lokasi (0,539).

ADR-006 memilih C=1 sebagai konfigurasi kerja karena koefisien provinsi lebih
stabil (SD 0,2525 vs 0,4237), tetapi C=1 belum punya angka test dan PR-AUC
valid-nya sedikit lebih rendah (0,6801 vs 0,6820).

Arah kerja berikutnya adalah menuning jalur temporal. Untuk itu dibutuhkan satu
baseline yang jelas dan punya bukti test.

## Decision

1. **Baseline dikunci ke model temporal penuh C=10**, fitur `t3`, VIF
   protected, ambang 0,4513. Berkas: `experiments/lr-baseline.yaml`,
   hash `c59bce3ae074ac4b...`.
2. **C=1 dipindah ke `experiments/lr-c1-stability.yaml`** dan dicatat sebagai
   varian stabilitas, bukan baseline.
3. **Eksperimen spasial ditutup.** Semua keluarga `lr-spatial-*` ditandai
   `sealed: true` dan `closed_at: 2026-11-17`. Hasilnya tetap disimpan sebagai
   bukti generalisasi spasial, bukan dasar tuning.
4. **Tuning berikutnya hanya memakai valid.** Test 19–23 September berstatus
   `seen` dengan `test_looks: 2` dan tidak dipakai memilih konfigurasi.
5. Konfigurasi hasil tuning **tidak boleh mengklaim 0,6311**. Angka test baru
   memerlukan jendela baru (Oktober 2026 setelah scar rilis, atau data
   tambahan).

## Alternatives

- **Tetap memakai C=1.** Ditolak: tidak punya angka test, dan keunggulan
  stabilitas tidak sepadan dengan kehilangan bukti evaluasi untuk laporan.
- **Memakai varian spasial tanpa lokasi (0,539) sebagai baseline.** Ditolak:
  angka itu berasal dari protokol spasial yang berbeda dan tidak punya padanan
  temporal.
- **Membuka ulang test September untuk tuning.** Ditolak: akan menjadi look
  ketiga dan menghapus makna angka test.

## Consequences

- Koefisien provinsi kembali lebih goyah (SD 0,4237). Ini harus disebut saat
  menafsirkan koefisien.
- Semua tuning dibandingkan dengan C=10 pada valid, memakai bootstrap
  berpasangan di valid.
- Belum ada angka test untuk konfigurasi hasil tuning sampai jendela baru
  tersedia.
- Eksperimen spasial tidak boleh dijalankan ulang tanpa keputusan baru; empat
  fold konfirmasi sudah terpakai.
