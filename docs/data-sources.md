# Sumber Data

Status: skeleton. Angka volume dan lisensi masih TBD.

| Sumber | Jenis | Frekuensi | Fungsi | Lisensi | Status |
|---|---|---|---|---|---|
| FIRMS | Near-stream | Poll 10 menit, lookback 2 hari | Hotspot, label ML | TBD | TBD |
| Open-Meteo historis | Batch | Harian, backfill manual | Fitur training | TBD | TBD |
| Open-Meteo forecast | Batch | Harian | Fitur inference | TBD | TBD |

## Lisensi

Kode repo berlisensi MIT. Data FIRMS dan Open-Meteo mengikuti lisensi masing-masing sumber. Jangan menaruh data mentah di repo.

## Yang perlu diukur

- Jumlah baris FIRMS per bulan.
- Cakupan tanggal dan wilayah.
- Persentase hotspot yang bisa dipetakan ke grid atau kabupaten.
- Positive rate label hotspot besok.
- Jumlah request Open-Meteo dan coverage lokasi.
- Lisensi dan atribusi masing-masing sumber.
