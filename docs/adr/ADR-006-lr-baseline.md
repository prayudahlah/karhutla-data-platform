# ADR-006: Baseline Logistic Regression dan Pembekuan Test

## Status

Accepted, 16 November 2026. Sebagian digantikan ADR-007 (17 November 2026):
C=1 tidak lagi menjadi konfigurasi kerja.

## Context

Baseline Logistic Regression untuk klasifikasi biner kebakaran per sel 0,25°
sudah dilatih dan dievaluasi. Dua masalah muncul:

1. Kebijakan seleksi VIF berubah setelah metrik test terlihat, dari tanpa
   proteksi (PR-AUC test 0,5979) menjadi melindungi `n_hotspot` (0,6311).
2. Grid `C` mendatar: C=1 memberi PR-AUC valid 0,6801, C=10 memberi 0,6820.
   Selisih 0,0019 tidak cukup untuk memilih model yang kurang teregulasi.

Tanpa aturan pembekuan, setiap eksperimen berikutnya berisiko menambah "look"
ke jendela test yang sama sehingga angka test kehilangan makna.

## Decision

1. **Kebijakan VIF dibekukan:** batas 10, `n_hotspot` dilindungi, pasangan
   kolinear yang dibuang. 29 fitur final.
2. **Konfigurasi kerja memakai C=1.** Dipilih di valid memakai aturan
   tie-break: selisih PR-AUC valid ≥ −0,002 dan simpangan baku koefisien
   provinsi lebih kecil (0,2525 vs 0,4237 pada bootstrap 200 blok tanggal).
3. **C=10 dipertahankan sebagai bukti test September** (PR-AUC 0,6311) dengan
   berkas konfigurasi terpisah. Angka itu tidak dipindahkan ke C=1.
4. **Test 19–23 September 2026 ditandai `seen`** dengan `test_looks: 2`.
   Eksperimen selanjutnya wajib memakai `--no-test`.
5. **Setiap run merujuk konfigurasi beku** lewat `--freeze-config`; hash isi
   berkas dicatat di `metrics.json`, MLflow, dan `experiments/registry.yaml`.

## Alternatives

- **Mempertahankan C=10 sebagai konfigurasi kerja.** Ditolak: keunggulan
  PR-AUC valid hanya 0,0019, sementara koefisien provinsi 40% lebih goyah.
- **Mengulang test untuk C=1.** Ditolak: itu look ketiga ke jendela yang sama
  dan membuat angka test tidak bermakna.
- **Membuang fitur provinsi.** Ditolak untuk sekarang: prior spasial sah, dan
  pengaruhnya perlu diuji lewat holdout provinsi, bukan dengan menghapus fitur
  diam-diam.

## Consequences

- Laporan memuat dua angka: 0,5979 (kebijakan VIF awal) dan 0,6311 (kebijakan
  final C=10), dengan penjelasan kapan keputusan diambil.
- C=1 belum punya angka test. Evaluasi bersih menunggu Oktober 2026 atau
  holdout provinsi.
- CLI menolak mengevaluasi test yang sudah seen tanpa `--allow-seen-test`.
- Stabilitas tanda provinsi C=1 sedikit lebih rendah (0,946 vs 0,966) karena
  koefisien menyusut; ini dicatat sebagai caveat, bukan alasan membatalkan
  keputusan.
