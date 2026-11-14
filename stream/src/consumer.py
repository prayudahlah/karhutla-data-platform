"""
Consumer FIRMS: firms.hotspot.raw -> Bronze JSONL (node batch).

Jalan sebagai service di node batch:

    const:
        redpanda (stream node)  ->  consumer  ->  $DATA_DIR/bronze/firms/...
                                                     $DATA_DIR/state/watermark.json

Prinsip:
    - commit offset HANYA setelah file Bronze tertulis, jadi tidak ada data hilang
    - at-least-once: kalau crash sebelum commit, pesan dibaca ulang
    - pesan rusak dikirim ke DLQ lalu offset tetap di-commit (tidak looping)
    - sink lokal sekarang; interface sink.py memudahkan pindah ke Garage/S3

Pakai:
    python stream/src/consumer.py
    python stream/src/consumer.py --once
    python stream/src/consumer.py --flush-seconds 60 --max-events 5000
"""
import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Consumer, KafkaError, TopicPartition

import event_schema
import watermark
from dlq import DeadLetterPublisher
from sink import LocalBronzeSink, part_key

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "batch"

BROKERS = os.environ.get("REDPANDA_BROKERS", "redpanda:9092")
TOPIC = os.environ.get("REDPANDA_TOPIC", "firms.hotspot.raw")
DLQ_TOPIC = os.environ.get("REDPANDA_DLQ_TOPIC", "firms.hotspot.dlq")
GROUP = os.environ.get("CONSUMER_GROUP", "bronze-firms")
FLUSH_SECONDS = float(os.environ.get("CONSUMER_FLUSH_SECONDS", "60"))
MAX_EVENTS = int(os.environ.get("CONSUMER_MAX_EVENTS", "5000"))

DATA_DIR = Path(os.environ.get("DATA_DIR") or _DEFAULT_DATA_DIR)
if not DATA_DIR.is_absolute():
    DATA_DIR = _REPO_ROOT / DATA_DIR

WATERMARK_FILE = DATA_DIR / "state" / "watermark.json"


def log(message):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {message}", flush=True)


def ingest_parts(event):
    """Ambil tanggal & jam ingestion dari event, tahan terhadap field aneh."""
    stamp = str(event.get("ingested_at") or "")
    date = stamp[:10] if len(stamp) >= 10 else "1970-01-01"
    hour = stamp[11:13] if len(stamp) >= 13 else "00"
    return date, hour


class BatchBuffer:
    """Menampung event sampai siap ditulis sebagai file per (sumber, partisi, jam)."""

    def __init__(self):
        self.groups = {}   # (source, partition, date, hour) -> [(offset, raw)]
        self.high = {}     # partition -> offset tertinggi
        self.acq_max = {}  # source -> acq_ts_utc tertinggi
        self.count = 0

    def __bool__(self):
        # True juga kalau hanya ada offset DLQ yang perlu di-commit.
        return self.count > 0 or bool(self.high)

    def add(self, msg, event, raw):
        partition = msg.partition()
        offset = msg.offset()
        date, hour = ingest_parts(event)
        key = (event["source"], partition, date, hour)
        self.groups.setdefault(key, []).append((offset, raw))
        self.high[partition] = max(self.high.get(partition, offset), offset)

        acq = str(event.get("acq_ts_utc") or "")
        if acq > self.acq_max.get(event["source"], ""):
            self.acq_max[event["source"]] = acq
        self.count += 1

    def clear(self):
        self.groups.clear()
        self.high.clear()
        self.acq_max.clear()
        self.count = 0


def flush_buffer(consumer, sink, buffer, retries=3):
    """Tulis semua grup ke Bronze, lalu commit offset. Gagal tulis = tidak commit."""
    if not buffer:
        return 0

    written = 0
    for (source, partition, date, hour), items in sorted(buffer.groups.items()):
        items.sort(key=lambda item: item[0])
        first_offset, last_offset = items[0][0], items[-1][0]
        key = part_key(source, date, hour, partition, first_offset, last_offset)
        lines = [raw for _, raw in items]

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                sink.write(key, lines)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - dicatat, lalu dicoba lagi
                last_error = exc
                log(f"[WARN] tulis {key} gagal ({attempt}/{retries}): {type(exc).__name__}: {exc}")
                time.sleep(2 * attempt)
        if last_error is not None:
            raise RuntimeError(f"gagal menulis Bronze {key}: {last_error}") from last_error

        written += len(items)
        log(f"  + {key} ({len(items)} event)")

    for source, acq in buffer.acq_max.items():
        watermark.update(WATERMARK_FILE, source, acq)

    offsets = [
        TopicPartition(TOPIC, partition, offset + 1)
        for partition, offset in sorted(buffer.high.items())
    ]
    consumer.commit(offsets=offsets, asynchronous=False)
    log(f"commit {len(offsets)} partisi | {written} event tertulis")
    buffer.clear()
    return written


def handle_message(msg, sink, buffer, dlq):
    """Validasi satu pesan. Return True kalau masuk buffer, False kalau ke DLQ."""
    raw = msg.value()
    if raw is None:
        dlq.publish(b"", "payload kosong", partition=msg.partition(), offset=msg.offset())
        return False

    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        dlq.publish(raw, f"JSON tidak valid: {exc}", partition=msg.partition(), offset=msg.offset())
        return False

    problems = event_schema.validate_event(event)
    if problems:
        dlq.publish(
            raw,
            "; ".join(problems),
            source=str(event.get("source", "")) if isinstance(event, dict) else "",
            partition=msg.partition(),
            offset=msg.offset(),
        )
        return False

    buffer.add(msg, event, raw)
    return True


def build_consumer():
    return Consumer({
        "bootstrap.servers": BROKERS,
        "group.id": GROUP,
        "client.id": "firms-consumer",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "max.poll.records": 500,
        "max.poll.interval.ms": 300000,
        "session.timeout.ms": 30000,
        "enable.partition.eof": True,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="konsumsi sampai kosong lalu keluar")
    parser.add_argument("--idle-seconds", type=float, default=10.0,
                        help="dengan --once: keluar setelah sekian detik tanpa pesan")
    parser.add_argument("--flush-seconds", type=float, default=FLUSH_SECONDS,
                        help="interval flush buffer (default dari CONSUMER_FLUSH_SECONDS)")
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS,
                        help="flush lebih awal kalau buffer mencapai jumlah ini")
    args = parser.parse_args()

    sink = LocalBronzeSink(DATA_DIR)
    dlq = DeadLetterPublisher(BROKERS, DLQ_TOPIC)
    consumer = build_consumer()
    consumer.subscribe([TOPIC])

    stop = {"flag": False}

    def request_stop(signum, _frame):
        log(f"terima signal {signum}, menyelesaikan buffer...")
        stop["flag"] = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    buffer = BatchBuffer()
    last_flush = time.time()
    last_message = time.time()
    in_dlq = 0

    log(f"mulai: {BROKERS} / {TOPIC} -> {DATA_DIR} (group={GROUP})")

    try:
        while not stop["flag"]:
            msg = consumer.poll(1.0)
            now = time.time()

            if msg is None:
                if buffer and (now - last_flush) >= args.flush_seconds:
                    flush_buffer(consumer, sink, buffer)
                    last_flush = now
                if args.once and buffer and (now - last_message) >= 1.0:
                    flush_buffer(consumer, sink, buffer)
                    last_flush = now
                if args.once and not buffer and (now - last_message) >= args.idle_seconds:
                    log("tidak ada pesan baru, keluar (--once)")
                    break
                continue

            last_message = now

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log(f"[WARN] kafka error: {msg.error()}")
                continue

            if not handle_message(msg, sink, buffer, dlq):
                in_dlq += 1
                # Pesan rusak tidak boleh menahan commit: catat offsetnya.
                buffer.high[msg.partition()] = max(
                    buffer.high.get(msg.partition(), msg.offset()), msg.offset()
                )

            if buffer.count >= args.max_events or (time.time() - last_flush) >= args.flush_seconds:
                flush_buffer(consumer, sink, buffer)
                last_flush = time.time()

        if buffer:
            flush_buffer(consumer, sink, buffer)
    finally:
        dlq.flush()
        consumer.close()
        log(f"selesai (DLQ: {in_dlq} pesan)")


if __name__ == "__main__":
    sys.exit(main())
