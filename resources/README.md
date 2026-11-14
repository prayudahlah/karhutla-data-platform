# Reference Data

## `indonesia_provinces.csv` (default)

Satu titik per provinsi: **38 baris**, koordinat ibu kota provinsi. Dipakai
sebagai titik request Open-Meteo saat `OPENMETEO_LOCATION_LEVEL=province`
(nilai default).

- Kolom: `city,province,latitude,longitude` — `city` berisi nama ibu kota.
- Termasuk lima provinsi yang tidak punya kota: Sulawesi Barat, Papua Barat,
  Papua Selatan, Papua Tengah, Papua Pegunungan.
- Koordinat adalah pusat ibu kota, bukan centroid poligon provinsi.

## `indonesia_cities.csv`

Daftar 98 kota di Indonesia, dipakai bila `OPENMETEO_LOCATION_LEVEL=city`.

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
