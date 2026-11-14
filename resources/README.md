# Reference Data

## `indonesia_cities.csv`

Daftar 98 kota di Indonesia yang dipakai sebagai titik request Open-Meteo.

- Kolom: `city,province,latitude,longitude`.
- Cakupan: 93 kota otonom di luar DKI Jakarta, ditambah 5 kota administrasi DKI Jakarta.
  Kabupaten tidak termasuk pada fase Bronze ini.
- Nama dan koordinat disusun dari daftar kota publik
  `https://jadwalsholatindonesia.com/data/cities.csv` (diakses 2026-11-14), yang
  mencantumkan Wikidata QID untuk setiap kota. Koordinat 5 kota administrasi
  Jakarta ditambahkan dari titik pusat administratif yang umum dipakai.
- Koordinat adalah titik pusat kota, bukan centroid poligon batas wilayah.
  Sebelum dipakai untuk analisis spasial tingkat lanjut, verifikasi ulang
  terhadap batas administrasi resmi.

Data ini hanya daftar referensi lokasi; data mentah Open-Meteo tidak disimpan
di repository.
