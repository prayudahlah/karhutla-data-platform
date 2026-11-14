# ADR-003: Batch dan Stream Processor

## Status
Accepted

## Context

Hotspot FIRMS harus tersedia mendekati real-time, sedangkan Open-Meteo cukup
harian. Keduanya harus mendarat di Bronze yang sama agar Silver dan Gold bisa
dibangun dengan satu alat (DuckDB) tanpa dua sistem terpisah.

Batasan nyata proyek ini: tiga laptop, satu di antaranya Windows, koneksi antar
node lewat Tailscale, dan waktu pengerjaan terbatas.

## Decision

### Stream (FIRMS)

- **Redpanda** single-node di node `stream` sebagai broker. Ringan, satu binary,
  tanpa ZooKeeper, dan S3 API-nya tidak diperlukan di sini.
- **Producer** Python + `confluent-kafka`, idempoten (`enable.idempotence`,
  `acks=all`), menulis spool JSONL lokal sebagai WAL sebelum publish.
- **Consumer** Python + `confluent-kafka` di node `batch`, group
  `bronze-firms`, micro-batch per sumber/partisi/jam, dan **commit offset
  setelah objek Bronze tertulis**.
- **Delivery semantics: at-least-once.** Duplikat diselesaikan di Silver dengan
  `row_number() over (partition by event_id)`, bukan dengan exactly-once.
- **Bronze**: Garage (S3-compatible), prefix `bronze/firms`, format JSON Lines.
- **DLQ**: `firms.hotspot.dlq` untuk pesan yang gagal validasi; offset tetap
  di-commit supaya consumer tidak berputar pada pesan yang sama.

### Batch (Open-Meteo)

- **Prefect** flow yang dijalankan manual atau lewat deployment harian.
- Menulis satu objek JSON per kota per dataset ke `bronze/open_meteo`.

### Yang tidak dipilih

- **Kafka Connect S3 sink**: nol kode, tetapi aturan commit, DLQ, dan watermark
  menjadi konfigurasi, sehingga sulit dipertanggungjawabkan saat demo.
- **Spark Structured Streaming**: terlalu berat untuk laptop 16 GB dan satu
  topik kecil.
- **Exactly-once**: tidak mungkin dijamin saat sink-nya object storage. Dedup di
  Silver lebih jujur dan lebih murah.

## Consequences

- Consumer boleh me-restart kapan saja; paling buruk menghasilkan objek
  duplikat, tidak pernah kehilangan data yang sudah ter-commit.
- Key objek memuat rentang offset, sehingga retry dengan offset yang sama
  menulis ke key yang sama dan ditolak sebagai duplikat — itu yang membuat
  retry aman.
- Pesan rusak tidak menghentikan pipeline, tetapi juga tidak hilang diam-diam:
  ia masuk DLQ dan memicu alert.
- Silver **wajib** melakukan dedup sebelum data dipakai model. Ini konsekuensi
  langsung dari pilihan at-least-once.
- Consumer bisa dipindah ke node lain tanpa mengubah kode: cukup ganti
  `REDPANDA_BROKERS` dan `GARAGE_ENDPOINT`.
