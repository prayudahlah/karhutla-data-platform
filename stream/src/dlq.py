"""Kirim pesan yang gagal diproses ke topik DLQ."""

from datetime import UTC, datetime

from confluent_kafka import Producer


class DeadLetterPublisher:
    """Publisher kecil khusus DLQ. Tidak perlu transaksional."""

    def __init__(self, brokers, topic, client_id="firms-dlq"):
        self.topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": brokers,
                "client.id": client_id,
                "acks": "all",
                "retries": 3,
                "linger.ms": 20,
            }
        )

    def publish(self, raw, error, source="", partition=None, offset=None):
        headers = {
            "error": (error or "")[:500],
            "source": source or "",
            "failed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if partition is not None:
            headers["src_partition"] = str(partition)
        if offset is not None:
            headers["src_offset"] = str(offset)

        self._producer.produce(self.topic, value=raw, headers=headers)
        self._producer.poll(0)

    def flush(self, timeout=10):
        return self._producer.flush(timeout)
