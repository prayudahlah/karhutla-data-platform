# F-02: Open-Meteo Bronze Ingestion

Tanggal verifikasi: 2026-11-14
Environment: Windows, Python 3.13.7, Docker 29.7.2, Garage `dxflrs/garage:v2.3.0`

## Konfigurasi

| Item | Nilai |
|---|---|
| Endpoint Garage | `http://127.0.0.1:3900` |
| Region | `garage` |
| Bucket | `lakehouse` |
| Prefix | `bronze/open_meteo` |
| Sumber kota | `resources/indonesia_cities.csv` (98 kota) |
| Weather | `https://api.open-meteo.com/v1/forecast` |
| Air quality | `https://air-quality-api.open-meteo.com/v1/air-quality` |
| Timezone | `Asia/Jakarta` |
| Forecast days | 3 (72 hourly records per kota per dataset) |

Tidak ada credential di source code atau repository. Credential hanya ada di
`.env` lokal yang diabaikan git.

## Hasil run nyata

### Smoke test 2 kota

```text
run_id=20261114T034816Z-5d21667a
status=success
cities_requested=2
cities_succeeded=2
objects_written=4
records_written=288
```

### Full run 98 kota

```text
run_id=20261114T034919Z-ecedb67b
status=success
cities_requested=98
cities_succeeded=98
cities_failed=0
objects_written=196
records_written=14112
```

Manifest:

```text
s3://lakehouse/bronze/open_meteo/manifests/ingest_date=2026-11-14/run_id=20261114T034919Z-ecedb67b.json
```

### Contoh objek dan checksum

Weather:

```text
key=  bronze/open_meteo/weather/ingest_date=2026-11-14/run_id=20261114T034919Z-ecedb67b/kota_banda_aceh_aceh.json
sha256=fdfaf71543205098d5af091077679cff53cfcd35cd25b8b9c160d881e638bd7f
record_count=72
variables=temperature_2m, relative_humidity_2m, precipitation, wind_speed_10m,
          wind_direction_10m, soil_moisture_0_to_7cm, vapour_pressure_deficit,
          et0_fao_evapotranspiration
```

Air quality:

```text
key=  bronze/open_meteo/air_quality/ingest_date=2026-11-14/run_id=20261114T034919Z-ecedb67b/kota_banda_aceh_aceh.json
sha256=412d583ddbd76e18c9611ea7a648c86888afb0b4e2de5c3f2d6cfcc09c472412
record_count=72
variables=pm2_5, pm10, carbon_monoxide, nitrogen_dioxide, sulphur_dioxide,
          ozone, aerosol_optical_depth
```

Metadata yang tersimpan pada objek weather:

```json
{
  "source": "open-meteo",
  "dataset": "weather",
  "ingestion_timestamp": "2026-11-14T03:49:36Z",
  "run_id": "20261114T034919Z-ecedb67b",
  "record_count": 72
}
```

Raw response Open-Meteo tersimpan utuh di field `response`.

## Readback dan persistensi

Readback sebelum restart:

```text
objects_expected=196
objects_verified=196
records_verified=14112
ok=True
failures=0
```

Setelah `docker restart karhutla-garage`:

```text
objects_expected=196
objects_verified=196
records_verified=14112
ok=True
failures=0
```

Listing bucket setelah run penuh dan smoke test:

```text
total_objects=202
weather=100
air_quality=100
manifests=2
```

Angka 202 terdiri dari 196 objek full run, 4 objek smoke test, dan 2 manifest.

## dlt compatibility

`dlt 1.32.0` dengan destination `filesystem` + `s3fs` berhasil menulis, listing,
dan readback JSONL ke `s3://lakehouse/bronze/_dlt_test` menggunakan:

```python
credentials = {
    "aws_access_key_id": ...,
    "aws_secret_access_key": ...,
    "region_name": "garage",
    "endpoint_url": "http://127.0.0.1:3900",
    "s3_url_style": "path",
}
```

Objek uji dlt kemudian dihapus. Jalur raw Bronze tetap memakai boto3 agar raw
response JSON tidak dinormalisasi.

## Test

```text
ruff check .                 -> All checks passed
pytest -q                    -> 24 passed
pytest -q -m integration     -> 1 passed (Garage live)
```

## Perintah reproduksi

```powershell
pip install -e ".[dev]"
# jalankan Garage sesuai docs/runbooks/garage-bronze.md
python -m flows.openmeteo_ingestion --limit 2
python -m flows.openmeteo_ingestion
python -m flows.openmeteo_ingestion --verify-only <run_id>
```
