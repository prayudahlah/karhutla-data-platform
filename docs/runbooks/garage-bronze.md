# Runbook: Open-Meteo ke Garage Bronze

Runbook ini menjalankan Garage lokal, lalu mengingest data Open-Meteo weather dan
air quality ke bucket Bronze. Tidak ada deployment atau schedule Prefect yang
dibuat.

## Prasyarat

- Docker Desktop/daemon berjalan.
- Python 3.12+ dan dependency proyek terpasang:
  `pip install -e ".[dev]"`.
- Akses internet ke `api.open-meteo.com` dan `air-quality-api.open-meteo.com`.
- Port `3900` (S3 API) bebas.

## 1. Siapkan konfigurasi Garage

Dari root repository (PowerShell):

```powershell
Copy-Item infra/garage/garage.toml.example infra/garage/garage.toml
$secret = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
(Get-Content infra/garage/garage.toml -Raw) -replace 'CHANGE_ME_WITH_64_HEX_CHARACTERS', $secret |
  Set-Content infra/garage/garage.toml -NoNewline
```

`infra/garage/garage.toml` diabaikan oleh git. Jangan commit file tersebut.

## 2. Jalankan Garage

Generate kredensial S3 lokal, lalu jalankan container dengan volume persisten:

```powershell
$accessKey = "GK" + (-join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }))
$secretKey = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })

docker run -d --name karhutla-garage `
  -p 3900:3900 -p 3901:3901 -p 3902:3902 -p 3903:3903 `
  -v "${PWD}\infra\garage\garage.toml:/etc/garage.toml:ro" `
  -v karhutla-garage-meta:/var/lib/garage/meta `
  -v karhutla-garage-data:/var/lib/garage/data `
  -e GARAGE_DEFAULT_ACCESS_KEY=$accessKey `
  -e GARAGE_DEFAULT_SECRET_KEY=$secretKey `
  -e GARAGE_DEFAULT_BUCKET=lakehouse `
  dxflrs/garage:v2.3.0 /garage server --single-node --default-bucket
```

Tag `v2.5.0` juga didukung; `v2.3.0` adalah versi minimum untuk flag
`--single-node` dan `--default-bucket`.

Cek container dan bucket:

```powershell
docker ps --filter name=karhutla-garage
docker exec karhutla-garage /garage status
docker exec karhutla-garage /garage bucket list
```

Tulis kredensial ke `.env` lokal (jangan commit):

```dotenv
GARAGE_ENDPOINT=http://127.0.0.1:3900
GARAGE_REGION=garage
GARAGE_ACCESS_KEY_ID=<accessKey>
GARAGE_SECRET_ACCESS_KEY=<secretKey>
GARAGE_BUCKET=lakehouse
GARAGE_FORCE_PATH_STYLE=true
BRONZE_PREFIX=bronze/open_meteo
OPENMETEO_CITY_CSV=resources/indonesia_cities.csv
```

Untuk menjalankan Prefect secara lokal tanpa server, jangan isi
`PREFECT_API_URL` di `.env`. Flow akan otomatis membuat temporary Prefect API
(ephemeral) jika variabel tersebut tidak diset. Jika `PREFECT_API_URL` diisi,
flow akan memakai server Prefect tersebut.

## 3. Smoke test

```powershell
python -m flows.openmeteo_ingestion --limit 2
```

Flow akan fetch dua kota (weather + air quality), upload ke Garage, melakukan
readback, dan menulis manifest. Output berisi `run_id`; simpan nilainya.

## 4. Ingestion penuh

```powershell
python -m flows.openmeteo_ingestion
```

98 kota x 2 dataset = 196 objek raw JSON. Flow berhenti dengan status failed
jika ada dataset yang gagal, tetapi manifest tetap ditulis dan berisi detail
kegagalan.

## 5. Verifikasi dan persistensi

```powershell
python -m flows.openmeteo_ingestion --verify-only <run_id>
```

Perintah ini membaca manifest, lalu membaca ulang setiap objek, membandingkan
SHA256, `run_id`, dan `record_count`.

Restart Garage untuk membuktikan data persisten:

```powershell
docker restart karhutla-garage
python -m flows.openmeteo_ingestion --verify-only <run_id>
```

Verifikasi manual dengan boto3/awscli juga bisa dilakukan:

```powershell
python -c "from common.config import Settings; from common.storage import BronzeStore; s=Settings.from_env(); st=BronzeStore(s.garage); print('\n'.join(st.list_keys(s.garage.prefix)[:10]))"
```

## 6. Struktur objek

```text
s3://lakehouse/bronze/open_meteo/
├── weather/ingest_date=YYYY-MM-DD/run_id=<run_id>/<city_slug>.json
├── air_quality/ingest_date=YYYY-MM-DD/run_id=<run_id>/<city_slug>.json
└── manifests/ingest_date=YYYY-MM-DD/run_id=<run_id>.json
```

Setiap objek dataset berisi raw response Open-Meteo di field `response`, plus
metadata `source`, `ingestion_timestamp`, `run_id`, `request_parameters`, dan
`record_count`.

## 7. Status dlt

Kompatibilitas dlt sudah diuji dengan `dlt 1.32.0` dan destination
`filesystem` + `s3fs` ke Garage:

- `bucket_url=s3://lakehouse/...`
- credentials berisi `endpoint_url`, `region_name`, dan `s3_url_style=path`
- upload, listing, dan readback JSONL berhasil.

Jalur utama Bronze tetap memakai boto3 karena tujuan fase ini adalah menyimpan
**raw response JSON utuh** dari Open-Meteo. dlt melakukan normalisasi schema dan
menulis file load package, sehingga tidak dipakai sebagai writer raw. Dependency
dlt tersedia sebagai extra opsional:

```powershell
pip install -e ".[dlt]"
```

## 8. Troubleshooting

- **SignatureDoesNotMatch / 403**: pastikan endpoint memakai `http://127.0.0.1:3900`,
  `GARAGE_REGION=garage`, dan `GARAGE_FORCE_PATH_STYLE=true`.
- **NoSuchBucket**: bucket default hanya dibuat saat container dijalankan dengan
  `--default-bucket` dan `GARAGE_DEFAULT_BUCKET`. Buat manual dengan
  `docker exec karhutla-garage /garage bucket create lakehouse`, lalu
  `garage key allow`.
- **Prefect mencoba konek ke server**: kosongkan `PREFECT_API_URL` untuk mode
  ephemeral lokal.
- **Mau reset total**: `docker rm -f karhutla-garage`,
  `docker volume rm karhutla-garage-meta karhutla-garage-data`.
