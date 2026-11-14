"""
Consumer FIRMS: firms.hotspot.raw -> Bronze (Garage atau disk lokal).

Jalan sebagai service di node batch:

    const:
        redpanda (stream node)  ->  consumer  ->  s3://lakehouse/bronze/firms/...
                                                     $DATA_DIR/state/watermark.json

Prinsip:
    - commit offset HANYA setelah objek Bronze tertulis, jadi tidak ada data hilang
    - at-least-once: kalau crash sebelum commit, pesan dibaca ulang
    - pesan rusak dikirim ke DLQ lalu offset tetap di-commit (tidak looping)
    - BRONZE_SINK=garage (default) memakai Garage, BRONZE_SINK=local memakai disk

Pakai:
    python stream/src/consumer.py
    python stream/src/consumer.py --once
    BRONZE_SINK=local python stream/src/consumer.py
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import event_schema
import heartbeat
import metrics
import notify
import watermark
from confluent_kafka import Consumer, KafkaError, TopicPartition
from dlq import DeadLetterPublisher
from sink import GarageBronzeSink, LocalBronzeSink, part_key

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "batch"

BROKERS = os.environ.get("REDPANDA_BROKERS", "redpanda:9092")
TOPIC = os.environ.get("REDPANDA_TOPIC", "firms.hotspot.raw")
DLQ_TOPIC = os.environ.get("REDPANDA_DLQ_TOPIC", "firms.hotspot.dlq")
GROUP = os.environ.get("CONSUMER_GROUP", "bronze-firms")
FLUSH_SECONDS = float(os.environ.get("CONSUMER_FLUSH_SECONDS", "60"))
MAX_EVENTS = int(os.environ.get("CONSUMER_MAX_EVENTS", "5000"))
BRONZE_SINK = os.environ.get("BRONZE_SINK", "garage").strip().lower()
BRONZE_PREFIX_FIRMS = os.environ.get("BRONZE_PREFIX_FIRMS", "bronze/firms").strip("/")

DATA_DIR = Path(os.environ.get("DATA_DIR") or _DEFAULT_DATA_DIR)
if not DATA_DIR.is_absolute():
    DATA_DIR = _REPO_ROOT / DATA_DIR

WATERMARK_FILE = DATA_DIR / "state" / "watermark.json"
HEARTBEAT_FILE = DATA_DIR / "state/consumer_heartbeat.json"

DLQ_ALERT_INTERVAL = float(os.environ.get("DLQ_ALERT_INTERVAL_SECONDS", "1800"))
_dlq_state = {"last_alert": 0.0, "pending": 0}


def note_dlq(count=1):
    """Catat pesan DLQ; kirim satu alert per interval supaya tidak spam."""
    metrics.DLQ.inc(count)
    _dlq_state["pending"] += count
    now = time.time()
    if now - _dlq_state["last_alert"] < DLQ_ALERT_INTERVAL:
        return
    _dlq_state["last_alert"] = now
    pending = _dlq_state["pending"]
    _dlq_state["pending"] = 0
    notify.tg_send(
        f"⚠️ Consumer FIRMS menolak {pending} pesan dalam "
        f"{int(DLQ_ALERT_INTERVAL // 60)} menit terakhir.\n"
        f"Cek topik {DLQ_TOPIC}: kemungkinan skema event berubah.\n"
        f"Bronze mungkin berhenti bertambah meski lag tetap 0.",
        "pipeline",
    )


def update_lag(consumer):
    """Set gauge lag total dari partisi yang sedang dipegang consumer."""
    try:
        total = 0
        for tp in consumer.assignment():
            _low, high = consumer.get_watermark_offsets(tp, timeout=1.0, cached=False)
            position = consumer.position([tp])[0].offset
            if position >= 0 and high >= 0:
                total += max(0, high - position)
        metrics.CONSUMER_LAG.set(total)
        return total
    except Exception:  # noqa: BLE001 - metrik tidak boleh mematikan consumer
        return None


def build_sink():
    """Pilih backend Bronze dari BRONZE_SINK."""
    if BRONZE_SINK == "local":
        return LocalBronzeSink(DATA_DIR / "bronze" / "firms")
    if BRONZE_SINK != "garage":
        raise SystemExit(f"BRONZE_SINK harus 'garage' atau 'local', bukan {BRONZE_SINK!r}")

    # Impor lokal supaya mode local tidak memerlukan boto3.
    from common.config import GarageSettings
    from common.storage import BronzeStore

    store = BronzeStore(GarageSettings.from_env())
    return GarageBronzeSink(store, BRONZE_PREFIX_FIRMS)


def log(message):
    print(f"[{datetime.now(UTC):%H:%M:%S}] {message}", flush=True)


def ingest_parts(event):
    """Ambil tanggal & jam ingestion dari event, tahan terhadap field aneh."""
    stamp = str(event.get("ingested_at") or "")
    date = stamp[:10] if len(stamp) >= 10 else "1970-01-01"
    hour = stamp[11:13] if len(stamp) >= 13 else "00"
    return date, hour


class BatchBuffer:
    """Menampung event sampai siap ditulis sebagai file per (sumber, partisi, jam)."""

    def __init__(self):
        self.groups = {}  # (source, partition, date, hour) -> [(offset, raw)]
        self.high = {}  # partition -> offset tertinggi
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
        location = key
        for attempt in range(1, retries + 1):
            try:
                location = sink.write(key, lines)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 - dicatat, lalu dicoba lagi
                last_error = exc
                log(f"[WARN] tulis {key} gagal ({attempt}/{retries}): {type(exc).__name__}: {exc}")
                time.sleep(2 * attempt)
        if last_error is not None:
            raise RuntimeError(f"gagal menulis Bronze {key}: {last_error}") from last_error

        written += len(items)
        log(f"  + {location} ({len(items)} event)")

    for source, acq in buffer.acq_max.items():
        watermark.update(WATERMARK_FILE, source, acq)

    offsets = [
        TopicPartition(TOPIC, partition, offset + 1)
        for partition, offset in sorted(buffer.high.items())
    ]
    consumer.commit(offsets=offsets, asynchronous=False)
    metrics.BRONZE_BATCHES.inc(len(buffer.groups))
    lag = update_lag(consumer)
    heartbeat.beat(HEARTBEAT_FILE, written=written, lag=lag)
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
    return Consumer(
        {
            "bootstrap.servers": BROKERS,
            "group.id": GROUP,
            "client.id": "firms-consumer",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "max.poll.records": 500,
            "max.poll.interval.ms": 300000,
            "session.timeout.ms": 30000,
            "enable.partition.eof": True,
        }
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="konsumsi sampai kosong lalu keluar")
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=10.0,
        help="dengan --once: keluar setelah sekian detik tanpa pesan",
    )
    parser.add_argument(
        "--flush-seconds",
        type=float,
        default=FLUSH_SECONDS,
        help="interval flush buffer (default dari CONSUMER_FLUSH_SECONDS)",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=MAX_EVENTS,
        help="flush lebih awal kalau buffer mencapai jumlah ini",
    )
    args = parser.parse_args()

    sink = build_sink()
    dlq = DeadLetterPublisher(BROKERS, DLQ_TOPIC)
    consumer = build_consumer()
    consumer.subscribe([TOPIC])
    port = metrics.start(9102)
    if port:
        log(f"metrik Prometheus di :{port}/metrics")

    stop = {"flag": False}

    def request_stop(signum, _frame):
        log(f"terima signal {signum}, menyelesaikan buffer...")
        stop["flag"] = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    buffer = BatchBuffer()
    last_flush = time.time()
    last_message = time.time()
    last_beat = time.time()
    in_dlq = 0

    log(f"mulai: {BROKERS} / {TOPIC} -> sink={BRONZE_SINK} (group={GROUP})")
    try:
        while not stop["flag"]:
            msg = consumer.poll(1.0)
            now = time.time()

            if msg is None:
                if buffer and (now - last_flush) >= args.flush_seconds:
                    flush_buffer(consumer, sink, buffer)
                    last_flush = now
                # Heartbeat tetap dikirim saat topik idle, supaya healthcheck
                # tidak menganggap consumer mati hanya karena tidak ada data.
                if now - last_beat >= 30:
                    heartbeat.beat(HEARTBEAT_FILE, lag=update_lag(consumer))
                    last_beat = now
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
                note_dlq()
                # Pesan rusak tidak boleh menahan commit: catat offsetnya.
                buffer.high[msg.partition()] = max(
                    buffer.high.get(msg.partition(), msg.offset()), msg.offset()
                )
            else:
                metrics.CONSUMED.inc()

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
