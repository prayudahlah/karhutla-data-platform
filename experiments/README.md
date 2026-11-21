# Eksperimen ML

Folder ini membekukan konfigurasi eksperimen supaya keputusan tidak terus
berubah mengikuti hasil test.

## Aturan

1. **Valid adalah tempat memutuskan.** `C`, ambang, seleksi fitur, dan
   perbandingan konfigurasi memakai valid atau cross-validation di dalam
   train+valid.
2. **Test dikunci per keluarga.** Satu jendela test hanya dievaluasi sekali.
   Setelah itu statusnya `seen` dan tidak boleh dipakai memilih konfigurasi.
3. **Eksperimen baru tidak menyentuh test.** Jalankan dengan `--no-test`.
4. **Konfigurasi beku punya hash.** Run wajib merujuk `lr-baseline.yaml` lewat
   `--freeze-config`; hash isi berkas dicatat di `metrics.json` dan MLflow.
5. **Setiap run dicatat.** `src/ml/train.py` menambah entri ke `registry.yaml`
   saat `--registry` dipakai (default: berkas ini).
6. **Alasan wajib.** Evaluasi test yang sudah `seen` hanya boleh dengan
   `--allow-seen-test "<alasan>"`, dan alasannya masuk registry.

## Berkas

| Berkas | Isi |
|---|---|
| `lr-baseline.yaml` | baseline temporal C=10, bukti test 0,6311 |
| `lr-c1-stability.yaml` | varian stabilitas C=1, tanpa metrik test |
| `lgbm-baseline.yaml` | LightGBM 29 fitur, pembanding unggul |
| `registry.yaml` | riwayat run, status test, penghitung `test_looks` |

## Perintah

```bash
# eksperimen baru: tanpa test
task ml-train -- --features t3 --c 10 --no-test \
  --freeze-config experiments/lr-baseline.yaml --out data/gold/models/lr-eksperimen

# varian stabilitas C=1: tanpa test
task ml-train -- --features t3 --c 1 --no-test \
  --freeze-config experiments/lr-c1-stability.yaml --out data/gold/models/lr-c1

# laporan final: test sudah seen, wajib alasan
task ml-train -- --features t3 --c 10 --freeze-config experiments/lr-baseline.yaml \
  --allow-seen-test "laporan final" --out data/gold/models/lr-t3
```
