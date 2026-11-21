# Log eksperimen ML

Catatan keputusan eksperimen, supaya konfigurasi tidak berubah mengikuti hasil
test. Sumber angka: `experiments/registry.yaml`, `data/gold/models/*/metrics.json`,
dan MLflow `karhutla-hotspot-risk`.

## Aturan

- `C`, ambang, seleksi fitur, dan perbandingan konfigurasi diputuskan di valid.
- Jendela test 19–23 September 2026 sudah dievaluasi dan berstatus **seen**.
- Test yang sudah seen tidak dipakai memilih konfigurasi berikutnya.
- Satu konfigurasi beku = satu berkas di `experiments/` dengan hash isi berkas.
- Angka dapat bergeser sekitar 0,0003 antar rebuild karena urutan baris parquet
  memengaruhi penjumlahan floating-point. Jangan menafsirkan selisih sekecil
  itu sebagai perbedaan model.

## Riwayat

| Waktu | Run | Konfigurasi | PR-AUC valid | PR-AUC test | Status |
|---|---|---|---:|---:|---|
| Tahap 6 awal | `lr-nhotspot` | hanya `n_hotspot` | 0,4847 | 0,4179 | baseline pembanding |
| Tahap 6 awal | `lr-t3` (VIF tanpa proteksi) | C=10 | 0,6634 | 0,5979 | digantikan |
| Tahap 6 akhir | `lr-t3` (VIF protected) | C=10 | 0,6820 | 0,6311 | bukti test September |
| Tahap 1 | `lr-c1` | C=1, VIF protected | 0,6801 | tidak dievaluasi | konfigurasi kerja |

### Mengapa run VIF tanpa proteksi digantikan

Run pertama membuang `n_hotspot` karena VIF 13,1 (kolinear dengan `n_night`,
`n_satellite`). Kebijakan diubah menjadi "lindungi `n_hotspot`, buang pasangan
kolinearnya" dengan alasan interpretabilitas dan operasional.

Perlu dicatat jujur: perubahan kebijakan itu dilakukan **setelah** metrik test
run pertama terlihat (0,5979). Karena itu angka 0,6311 tidak sepenuhnya
out-of-sample untuk keputusan tersebut. Kedua angka dilaporkan.

Artefak MLflow run pertama sudah dihapus saat pembersihan; angkanya tetap
tercatat di sini dan di `docs/ml-lr-t3-audit` (arsip plan).

## Keputusan C=1

### Aturan yang dipakai

| Kondisi | Keputusan |
|---|---|
| ΔPR-AUC valid ≥ −0,002 dan simpangan baku koefisien lebih kecil | C=1 dipakai |
| ΔPR-AUC valid < −0,005 | C=10 dipertahankan |
| di antaranya | C=10 dipertahankan |

### Hasil

| Metrik | C=10 | C=1 | Selisih |
|---|---:|---:|---:|
| PR-AUC valid | 0,6820 | 0,6801 | −0,0019 |
| ROC-AUC valid | 0,8978 | 0,8964 | −0,0014 |
| Brier valid | 0,0850 | 0,0865 | +0,0015 |
| F1 valid | 0,6180 | 0,6175 | −0,0005 |
| SD koefisien provinsi (bootstrap 200 blok tanggal) | 0,4237 | **0,2525** | −40% |
| SD koefisien `n_hotspot` | 0,0726 | **0,0709** | −2% |
| Stabilitas tanda provinsi | 0,966 | 0,946 | −0,020 |

**Keputusan: C=1 menjadi konfigurasi kerja** karena selisih PR-AUC valid masih
di dalam toleransi dan simpangan baku koefisien provinsi jauh lebih kecil.

> Catatan 17 November 2026: keputusan ini dibalik. Baseline kembali ke C=10
> karena satu-satunya konfigurasi yang punya bukti test. Lihat bagian
> "Keputusan 17 November 2026" di bawah.

Caveat yang harus ikut ditulis: stabilitas tanda provinsi C=1 sedikit lebih
rendah (0,946 vs 0,966) karena koefisien menyusut ke nol. Yang membaik adalah
besarnya goyangan, bukan arah tanda untuk koefisien yang sudah kecil.

### Konsekuensi

- Angka test 0,6311 tetap milik C=10 (`experiments/lr-baseline.yaml`).
- C=1 belum punya angka test. Evaluasi hanya boleh dari jendela baru: Oktober
  2026 setelah scar tersedia, atau holdout provinsi.
- Test 19–23 September kini tercatat `test_looks: 2` dan tidak boleh dipakai
  memilih konfigurasi lagi.

## Spatial holdout (Tahap 2)

Tujuan: menguji model beku C=1 pada wilayah yang tidak pernah dilihat. Empat
fold konfirmasi: Kalimantan, Sumatra, Papua, Maluku. Jawa dan Bali/Nusa
Tenggara tidak dipakai karena hanya 1 dan 4 positif pada jendela test.

Protokol per fold: train di semua wilayah lain tanggal 1–7 Sep, valid di
wilayah lain 11–15 Sep untuk ambang, test hanya di wilayah holdout 19–23 Sep.
`C` tetap 1 (model beku); hanya ambang dihitung ulang.

### Hasil agregat 4 fold

| Varian | PR-AUC (mean ± SD) | ROC-AUC | F1 | Brier |
|---|---:|---:|---:|---:|
| Penuh (`t3`, dengan lokasi) | 0,491 ± 0,209 | 0,786 | 0,457 | 0,136 |
| Tanpa lokasi | 0,539 ± 0,211 | 0,807 | 0,535 | 0,168 |
| Baseline `n_hotspot` saja | **0,552 ± 0,225** | **0,849** | **0,543** | **0,127** |

### Hasil per fold (varian penuh)

| Wilayah | PR-AUC | ROC-AUC | Precision | Recall | F1 | Brier |
|---|---:|---:|---:|---:|---:|---:|
| Kalimantan | 0,373 | 0,710 | 0,456 | 0,442 | 0,449 | 0,152 |
| Sumatra | 0,725 | 0,859 | 0,915 | 0,303 | 0,455 | 0,126 |
| Papua | 0,266 | 0,738 | 0,264 | 0,662 | 0,377 | 0,147 |
| Maluku | 0,599 | 0,837 | 0,514 | 0,585 | 0,547 | 0,119 |

### Temuan

1. **Generalisasi spasial jauh lebih lemah dari temporal.** Rata-rata PR-AUC
   0,491 dibanding 0,6311 pada test temporal. Variasinya besar: 0,266 (Papua)
   sampai 0,725 (Sumatra).
2. **Model penuh tidak mengalahkan baseline satu fitur.** `n_hotspot` saja
   memberi 0,552, lebih tinggi dari model 29 fitur. Artinya fitur tambahan
   belum memberi nilai di wilayah baru.
3. **Fitur lokasi memperburuk generalisasi.** Tanpa `province`, `center_lat`,
   `center_lon`, dan `province_distance_km`, PR-AUC naik dari 0,491 ke 0,539;
   di Maluku naik dari 0,599 ke 0,739 dan di Papua dari 0,266 ke 0,338.
4. **Kalibrasi memburuk.** Brier varian tanpa lokasi 0,168, lebih buruk dari
   model penuh 0,136 dan baseline 0,127.

### Konsekuensi untuk laporan

- Klaim harus dibatasi: model bekerja untuk **wilayah yang sudah dikenal**,
  belum terbukti untuk wilayah baru.
- Kalau tujuan berikutnya generalisasi spasial, arah perbaikan adalah
  mengurangi ketergantungan pada lokasi dan menambah fitur lingkungan yang
  berlaku lintas wilayah, bukan menambah fitur lokasi.
- LightGBM (Tahap 4) harus diuji dengan protokol spatial holdout yang sama,
  bukan hanya pada test temporal.
- Setiap fold dievaluasi satu kali per keluarga. Varian tanpa lokasi dan
  baseline `n_hotspot` adalah diagnostik terencana dan memakai baris test yang
  sama; ini dicatat di registry.

## Keputusan 17 November 2026 — kembali ke baseline temporal

Setelah spatial holdout selesai, jalur kerja difokuskan ke model temporal.

| Hal | Keputusan |
|---|---|
| Baseline | **C=10**, fitur `t3`, VIF protected, ambang 0,4513 |
| Bukti test | PR-AUC 0,6311 (test 19–23 Sep, status `seen`, 2 look) |
| C=1 | dipindah ke `experiments/lr-c1-stability.yaml` sebagai varian stabilitas |
| Eksperimen spasial | semua family `lr-spatial-*` ditutup (`sealed: true`, 17 Nov 2026) |
| Tuning berikutnya | hanya memakai valid; test tidak dipakai lagi |

Alasan:

1. C=10 punya PR-AUC valid tertinggi (0,6820) dan satu-satunya angka test.
2. C=1 lebih stabil, tetapi tanpa angka test sehingga menyulitkan pelaporan.
3. Spatial holdout menunjukkan model penuh belum generalisasi; jalur itu
   ditutup sebagai bukti, bukan dijadikan dasar tuning.

Konsekuensi: tuning tidak boleh mengklaim 0,6311. Angka test baru menunggu
jendela baru. Per 17 November 2026, MCD64A1 Oktober belum dirilis, jadi belum
ada jendela temporal baru.

## Tuning 1 — fitur riwayat (ditolak)

Hipotesis: kebakaran bertahan beberapa hari, sehingga lag kepadatan deteksi
menambah sinyal yang tidak bisa ditangkap LR.

Perubahan: `n_hotspot` lag 1–3, rolling 3 hari, jarak ke deteksi sebelumnya,
`precip_sum` rolling 3 hari, dan `soil_moisture_mean` rolling 7 hari. Grid
tanggal dibuat padat per sel supaya hari tanpa deteksi dihitung 0.

Hasil di valid (baseline C=10 PR-AUC 0,6827):

| Varian | PR-AUC | Delta | CI 95% | Hari membaik | Brier |
|---|---:|---:|---|---:|---:|
| Imputasi + indikator `has_history` | 0,6816 | −0,0011 | [−0,0048; 0,0031] | 2 dari 5 | 0,0917 |
| Train hanya hari dengan riwayat | 0,6677 | −0,0150 | [−0,0286; −0,0037] | 1 dari 5 | 0,0945 |

Keputusan: **ditolak**. Tidak ada varian yang memenuhi kriteria (ΔPR-AUC
≥ +0,010, CI bawah > 0, ≥3 hari membaik). Baseline tidak diubah.

Pelajaran:

- 23 tanggal terlalu pendek. Varian yang menuntut riwayat hanya menyisakan 4
  hari training, dan performanya jatuh.
- Lag kepadatan kolinear dengan `n_hotspot`; VIF membuang `n_hotspot_roll3`,
  dan lag 1–3 menambah noise tanpa informasi baru.
- Untuk menguji hipotesis ini dengan adil, perlu data Agustus sebagai riwayat
  dan tambahan hari training. Tanpa itu, eksperimen ini tidak bisa
  disimpulkan sebagai "riwayat tidak berguna", hanya "tidak berguna pada data
  23 hari".

Artefak: `data/gold/models/tuning-01-history/comparison.json`. Kode fitur
riwayat tetap ada (grup `t3h`) untuk diuji ulang saat data lebih panjang.

## Tuning 2 — region grouping (ditolak)

Hipotesis: 38 dummy provinsi terlalu granular dan membuat koefisien goyah,
sehingga 7 wilayah bisa lebih stabil tanpa kehilangan banyak sinyal.

Perubahan: `province` diganti `region` (7 wilayah, 6 dummy). Fitur lain sama.

Hasil di valid:

| Model | Fitur | PR-AUC | ROC-AUC | Brier | F1 |
|---|---:|---:|---:|---:|---:|
| Baseline (province) | 29 | **0,6827** | 0,8980 | **0,0849** | 0,6167 |
| Region grouping | 29 | 0,6094 | 0,8783 | 0,1273 | 0,5524 |

Delta PR-AUC −0,0732, CI 95% [−0,1130; −0,0311], hanya 1 dari 5 tanggal
membaik. Brier memburuk 0,0424.

Keputusan: **ditolak**. Baseline tidak diubah.

Pelajaran:

- Prior provinsi membawa sinyal besar pada protokol temporal. Menghapusnya
  menurunkan PR-AUC tujuh poin.
- Ini menjelaskan hasil spatial holdout: model memang bergantung pada identitas
  provinsi, bukan hanya pada fitur lingkungan.
- Trade-off-nya jelas: provinsi menaikkan performa temporal, tetapi
  memperburuk generalisasi ke wilayah baru.
- Untuk laporan, jangan memilih region grouping hanya karena koefisien lebih
  stabil; biayanya terlalu besar.

Artefak: `data/gold/models/tuning-02-region/comparison.json`.

## LightGBM sebagai pembanding — unggul

LightGBM dilatih pada baris dan split yang sama. Dua varian: 29 fitur (sama
dengan LR) dan 39 fitur (tanpa seleksi VIF). Tanpa scaling, tanpa log1p, tanpa
imputasi, `province` kategorikal native.

### Valid

| Model | Fitur | PR-AUC | ROC-AUC | Brier | F1 | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| LR baseline | 29 | 0,6827 | 0,8980 | 0,0849 | 0,6167 | — | — |
| LightGBM | 29 | **0,7675** | **0,9339** | **0,0721** | **0,6801** | 0,6376 | 0,7286 |
| LightGBM | 39 | 0,7645 | 0,9331 | 0,0721 | 0,6774 | 0,6603 | 0,6955 |

Perbandingan utama (29 fitur): delta PR-AUC +0,0848, CI 95% [0,0642; 0,1100],
membaik di 5 dari 5 tanggal valid. Brier juga lebih baik (0,0721 vs 0,0849).

Hyperparameter terpilih: `num_leaves=31`, `min_child_samples=50`,
`feature_fraction=0,8`, early stop di iterasi 300.

### Test (perbandingan pengembangan, jendela sudah seen)

| Model | PR-AUC | ROC-AUC | Brier | F1 | Precision@100 |
|---|---:|---:|---:|---:|---:|
| LR baseline | 0,6311 | 0,9041 | 0,0865 | 0,5707 | 0,632 |
| LightGBM 29 | **0,7156** | **0,9263** | **0,0672** | **0,6301** | **0,700** |
| LightGBM 39 | 0,7099 | 0,9260 | 0,0686 | 0,6312 | 0,694 |

Delta test LightGBM 29 vs LR: +0,0845 PR-AUC, +0,0222 ROC-AUC.

### Interpretasi

- LightGBM menang konsisten: valid, test pengembangan, dan Brier. Ini bukan
  artefak satu metrik.
- 39 fitur tidak lebih baik dari 29; artinya fitur yang dibuang VIF tidak
  membawa informasi tambahan untuk pohon.
- Feature importance tetap didominasi `n_hotspot`, `center_lat`, `province`,
  `province_distance_km`, dan `center_lon`. Jadi model masih memakai prior
  lokasi; keunggulannya bukan bukti generalisasi spasial.
- Baseline formal tetap LR sampai ada jendela test baru. LightGBM adalah
  kandidat baseline berikutnya, bukan pengganti yang langsung diklaim.

Artefak: `data/gold/models/lgbm-t3/` dan `lgbm-t3all/`, plus
`comparison.json` di masing-masing folder. Konfigurasi beku:
`experiments/lgbm-baseline.yaml`.

## Berkas konfigurasi

| Berkas | Isi |
|---|---|
| `experiments/lr-baseline.yaml` | C=10, baseline temporal, bukti test 0,6311 |
| `experiments/lr-c1-stability.yaml` | C=1, varian stabilitas, tanpa metrik test |
| `experiments/registry.yaml` | riwayat run, status test, keputusan |

## Reproduksi

```bash
# baseline temporal (test sudah seen, wajib alasan)
task ml-train -- --features t3 --c 10 \
  --freeze-config experiments/lr-baseline.yaml \
  --allow-seen-test "laporan final" --out data/gold/models/lr-t3

# varian stabilitas (tanpa test)
task ml-train -- --features t3 --c 1 --no-test \
  --freeze-config experiments/lr-c1-stability.yaml --out data/gold/models/lr-c1
```
