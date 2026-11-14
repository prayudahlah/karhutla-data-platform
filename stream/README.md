# Stream: NASA FIRMS -> Redpanda -> Bronze

Polling hotspot FIRMS (near-real-time) untuk wilayah Indonesia, dedup, publish ke Redpanda,
lalu consumer di node `batch` menulis Bronze (JSONL). Producer menyimpan spool lokal
sebagai WAL dan mengirim alert Telegram.

```
node stream                                    node batch
FIRMS API --> firms_stream.py --> Redpanda --> consumer.py --> data/batch/bronze/firms/...
                    \--> spool lokal (WAL)
                    \--> alert Telegram (hotspot / pipeline / dq / general)
```

## Struktur

| Path | Isi |
|---|---|
| `src/firms_stream.py` | producer: fetch, dedup, spool, publish, alert |
| `src/consumer.py` | consumer: baca topik, validasi, tulis Bronze, commit offset |
| `src/event_schema.py` | kontrak event v1 + validasi (dipakai producer & consumer) |
| `src/sink.py` | tujuan tulis Bronze (`LocalBronzeSink`) |
| `src/dlq.py` | kirim pesan rusak ke `firms.hotspot.dlq` |
| `src/watermark.py` | freshness per sumber |
| `src/replay_spool.py` | kirim ulang file spool yang belum terkirim |
| `notebooks/firms_stream_test.ipynb` | notebook uji semua aspek stream |
| `data/spool/` | WAL producer, gitignored |
| `data/state/` | state dedup producer, gitignored |

## Jalankan

Prasyarat: Docker Desktop menyala, dan `task` terpasang
(`winget install Task.Task`).

```bash
task dev                    # node stream: redpanda + console + producer (+ port ke localhost)
task up-batch               # node batch: garage + garage-webui + consumer
task ps
task logs SERVICE=producer
task logs-batch SERVICE=consumer
task down
```

Tanpa `task`:

```bash
docker compose -f compose/base.yml -f compose/vps-stream.yml -f compose/dev.yml up -d --build
docker compose -f compose/base.yml -f compose/vps-batch.yml up -d --build
```

Console: http://localhost:8080 · Garage web UI: http://localhost:3909 ·
Broker dari host: `localhost:19092`

Kedua stack memakai network yang sama (`karhutla`) tapi bisa di-`up` terpisah. Consumer
tidak punya `depends_on` ke redpanda, jadi aman kalau broker belum siap.

## Consumer

```bash
task lag                  # lag per partisi (harus 0 saat idle)
task bronze-files         # daftar objek Bronze di Garage
task bronze-lines         # jumlah objek
task consume-once         # konsumsi sisa pesan lalu keluar
task dlq                  # offset topik DLQ
```

Prinsip:

- `group.id=bronze-firms`, `enable.auto.commit=false`, `auto.offset.reset=earliest`.
- Flush tiap 60 detik (`CONSUMER_FLUSH_SECONDS`) atau 5.000 event (`CONSUMER_MAX_EVENTS`).
- **Commit offset setelah objek tertulis.** Crash sebelum commit = pesan dibaca ulang.
- Pesan gagal parse/validasi -> `firms.hotspot.dlq`, offset tetap di-commit (tidak looping).
- `SIGTERM` -> buffer di-flush dan di-commit (`stop_grace_period: 30s`).

Bronze ditulis ke **Garage** (`BRONZE_SINK=garage`, default) memakai
`common.storage.BronzeStore.put_bytes`, atau ke disk lokal (`BRONZE_SINK=local`) untuk
dev tanpa Garage. Layout sama di kedua mode:

```
s3://lakehouse/bronze/firms/source=<SUMBER>/ingest_date=<YYYY-MM-DD>/
    ingest_hour=<HH>/part-p<partisi>-<offset_awal>-<offset_akhir>.jsonl
```

Nama objek memuat rentang offset, jadi retry dengan offset yang sama menulis ke key yang
sama. `put_bytes` menolak overwrite, dan `ObjectAlreadyExistsError` diperlakukan sebagai
sukses — itu yang membuat consumer idempoten saat commit gagal. Duplikat antar-replay
tetap mungkin; dedup resmi pakai `event_id` di Silver.

| Variabel | Default | Keterangan |
|---|---|---|
| `BRONZE_SINK` | `garage` | `garage` atau `local` |
| `BRONZE_PREFIX_FIRMS` | `bronze/firms` | prefix objek di bucket |
| `GARAGE_ENDPOINT` | `http://garage:3900` (compose) | |
| `GARAGE_BUCKET` | `lakehouse` | |
| `REDPANDA_BROKERS` | `redpanda:9092` (compose) | di VM batch pakai `stream:9092` |
| `REDPANDA_TOPIC` | `firms.hotspot.raw` | |
| `REDPANDA_DLQ_TOPIC` | `firms.hotspot.dlq` | |
| `CONSUMER_GROUP` | `bronze-firms` | |
| `CONSUMER_FLUSH_SECONDS` | `60` | naikkan ke 300-900 untuk mengurangi jumlah file |
| `DATA_DIR` | `/app/data` (compose) | state watermark; juga tujuan `BRONZE_SINK=local` |

### Tanpa Docker (spool saja)

```bash
pip install -r stream/requirements.txt
export $(grep -v '^#' stream/.env | xargs)   # setelah menyalin .env.example -> .env dan diisi
python stream/src/firms_stream.py --once --test-telegram
python stream/src/firms_stream.py --no-publish --interval 600
python stream/src/firms_stream.py --selftest-publish   # tes broker tanpa memanggil API FIRMS
```

## Topik

| Topik | Partisi | Retensi | Isi |
|---|---|---|---|
| `firms.hotspot.raw` | 3 | 7 hari | event hotspot, key = `event_id` |
| `firms.hotspot.dlq` | 1 | 14 hari | pesan gagal parse/validasi, plus header `error`, `source`, `src_partition`, `src_offset` |

`auto_create_topics_enabled=false`, jadi topik harus dibuat `redpanda-init` (sudah otomatis
di compose). Tanpa itu, topik yang belum ada akan lahir dengan 1 partisi.

### Kontrak event (schema v1)

Flat, satu objek per hotspot. Key Kafka = `event_id`.

```json
{
  "event_id": "ca7053d6...",
  "schema_version": 1,
  "source": "MODIS_NRT",
  "ingested_at": "2026-11-14T03:27:27Z",
  "latitude": -4.58141, "longitude": 120.01611,
  "brightness": 323.82, "scan": 1.3, "track": 1.13,
  "acq_date": "2026-11-14", "acq_time": 17,
  "satellite": "Terra", "instrument": "MODIS",
  "confidence": 77, "version": "6.1NRT", "bright_t31": 295.81,
  "frp": 19.86, "daynight": "D",
  "acq_ts_utc": "2026-11-14T00:17:00Z", "acq_wib": "14-11 07:17",
  "latency_min": 190.5
}
```

`event_id` = sha1 dari `latitude|longitude|acq_date|acq_time|satellite`.

## Semantik dan pengamanan data

- Producer idempoten (`enable.idempotence=true`, `acks=all`, `retries=5`).
- Delivery **at-least-once**. Duplikat bisa muncul kalau proses mati di antara publish dan
  rename spool, atau saat replay. Dedup resmi dilakukan di Silver memakai `event_id`.
- Alur file spool:
  1. batch ditulis sebagai `batch_<HHMMSS>.jsonl` (pending),
  2. publish ke Redpanda,
  3. kalau semua event terkirim, file di-rename jadi `batch_<HHMMSS>.jsonl.sent`.
- File `*.jsonl` yang tersisa artinya ada event yang belum terkirim. Kirim ulang:

```bash
task replay                                          # atau: python stream/src/replay_spool.py
python stream/src/replay_spool.py --dry-run          # lihat dulu
```

- State dedup (`firms_seen.json`) disimpan setelah spool ada di disk, jadi data tidak hilang
  kalau broker sedang mati.

## Environment

| Variabel | Default | Keterangan |
|---|---|---|
| `FIRMS_MAP_KEY` | – | wajib, https://firms.modaps.eosdis.nasa.gov/api/map_key/ |
| `REDPANDA_BROKERS` | `redpanda:9092` (compose) | di VM lain pakai `stream:9092` |
| `REDPANDA_TOPIC` | `firms.hotspot.raw` | |
| `DATA_DIR` | `data` relatif ke folder `stream/` | |
| `TELEGRAM_*` | – | lihat bagian Telegram |

Catatan: di compose, broker internal memakai `redpanda:9092`, **bukan** alias `stream`.
Kalau laptopmu punya nama Tailscale `stream`, alias itu jatuh ke MagicDNS
(`100.91.1.14`) saat container broker mati.

## Telegram (grup dengan topik)

1. Buat grup, aktifkan **Topics**, lalu buat topik: `Hotspot Alerts`, `Pipeline Alerts`,
   `Data Quality Alerts` (+ `General`).
2. Tambahkan bot ke grup dan jadikan admin.
3. Kirim satu pesan di tiap topik, lalu jalankan `python src/firms_stream.py --discover-topics`
   untuk melihat `chat_id` dan `thread_id`.
4. Isi `.env`, lalu tes dengan `python src/firms_stream.py --once --test-telegram`.

| Topik | Isi |
|---|---|
| Hotspot Alerts | hotspot baru (difilter confidence & FRP) |
| Pipeline Alerts | error beruntun, pemulihan, data basi |
| Data Quality Alerts | hasil cek kualitas data tiap batch (gagal; `--dq-verbose` untuk yang lolos) |
| General | info start dan tes |

## Catatan

- MAP_KEY: batas 5000 transaksi / 10 menit.
- Jangan commit `.env` atau folder `data/`.
- `--day-range 1` sering kosong untuk VIIRS pada pagi UTC; `docs/data-sources.md`
  menyebut lookback 2 hari, jadi `--day-range 2` lebih aman kalau butuh data terus-menerus.
- Belum ada: penulisan Bronze ke object storage (Garage/S3), metrik Prometheus,
  TLS/auth broker, dan compaction file kecil.
