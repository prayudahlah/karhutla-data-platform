"""Tujuan tulis Bronze untuk consumer.

Dua implementasi:
    LocalBronzeSink  : filesystem lokal, untuk dev tanpa Garage
    GarageBronzeSink : object storage Garage lewat common.storage.BronzeStore

Keduanya menerima key relatif yang sama, jadi pindah backend tidak mengubah
layout data:

    dataset=hotspot/source=<SOURCE>/ingest_date=<YYYY-MM-DD>/
        ingest_hour=<HH>/part-p<partition>-<offset_awal>-<offset_akhir>.jsonl

Prefix "bronze/firms" ditambahkan oleh sink-nya masing-masing: Local memakai
DATA_DIR/bronze/firms, Garage memakai BRONZE_PREFIX_FIRMS.
"""

import os
from pathlib import Path


def part_key(source, ingest_date, ingest_hour, partition, first_offset, last_offset):
    """Key relatif (tanpa prefix bronze/firms)."""
    return (
        "dataset=hotspot"
        f"/source={source}"
        f"/ingest_date={ingest_date}"
        f"/ingest_hour={ingest_hour}"
        f"/part-p{partition}-{first_offset:012d}-{last_offset:012d}.jsonl"
    )


def join_lines(lines):
    """Rangkai baris JSONL, pastikan tiap baris diakhiri newline."""
    return b"".join(line if line.endswith(b"\n") else line + b"\n" for line in lines)


class BronzeSink:
    """Kontrak minimal: tulis satu objek, return lokasinya."""

    def write(self, key, lines):
        raise NotImplementedError


class LocalBronzeSink(BronzeSink):
    """Tulis JSONL ke disk lokal secara atomik dan idempoten."""

    def __init__(self, root):
        self.root = Path(root)

    def path_for(self, key):
        return self.root / key

    def write(self, key, lines):
        dest = self.path_for(key)
        if dest.exists():
            # Offset yang sama sudah pernah ditulis (retry setelah commit gagal).
            return dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        with tmp.open("wb") as fh:
            fh.write(join_lines(lines))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
        return dest


class GarageBronzeSink(BronzeSink):
    """Tulis JSONL ke Garage lewat S3 API.

    Memakai put_bytes, bukan put_jsonl: baris dari Kafka sudah berbentuk bytes,
    jadi tidak perlu di-parse lalu di-encode ulang.
    """

    def __init__(self, store, prefix="bronze/firms"):
        self.store = store
        self.prefix = prefix.strip("/")

    def key_for(self, key):
        return f"{self.prefix}/{key}" if self.prefix else key

    def write(self, key, lines):
        full_key = self.key_for(key)
        try:
            self.store.put_bytes(
                full_key,
                join_lines(lines),
                content_type="application/x-ndjson",
                metadata={"kind": "firms-hotspot-batch"},
            )
        except Exception as exc:  # noqa: BLE001 - dipilah berdasarkan tipe
            # Impor lokal supaya mode sink=local tetap jalan tanpa boto3.
            from common.storage import ObjectAlreadyExistsError

            if isinstance(exc, ObjectAlreadyExistsError):
                # Upload sebelumnya sukses tapi commit offset gagal: bukan error.
                return full_key
            raise
        return full_key
