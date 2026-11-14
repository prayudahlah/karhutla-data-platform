"""Metrik Prometheus untuk producer dan consumer FIRMS.

Dinyalakan lewat METRICS_PORT (default 9101 untuk producer, 9102 untuk
consumer). Set METRICS_PORT=0 untuk mematikan exporter.
"""
import os

from prometheus_client import Counter, Gauge, start_http_server

PRODUCED = Counter(
    "firms_events_produced_total",
    "Event hotspot yang berhasil dikirim ke Redpanda",
    ["source"],
)
PUBLISH_ERRORS = Counter(
    "firms_publish_errors_total",
    "Event yang gagal dikirim ke Redpanda",
)
FRESHNESS = Gauge(
    "firms_freshness_seconds",
    "Umur data terbaru (sekarang - acq_ts_utc) per sumber satelit",
    ["source"],
)

CONSUMED = Counter(
    "firms_events_consumed_total",
    "Event valid yang masuk buffer consumer",
)
BRONZE_BATCHES = Counter(
    "firms_bronze_batches_total",
    "Objek Bronze yang berhasil ditulis",
)
DLQ = Counter(
    "firms_dlq_messages_total",
    "Pesan yang dikirim ke topik DLQ",
)
CONSUMER_LAG = Gauge(
    "firms_consumer_lag",
    "Selisih offset akhir partisi dengan posisi consumer",
)


def start(default_port):
    """Nyalakan HTTP exporter. Return port, atau None kalau dimatikan."""
    raw = os.environ.get("METRICS_PORT", str(default_port))
    try:
        port = int(raw)
    except ValueError:
        print(f"[WARN] METRICS_PORT bukan angka: {raw!r}, exporter dimatikan")
        return None
    if port <= 0:
        return None
    start_http_server(port)
    return port
