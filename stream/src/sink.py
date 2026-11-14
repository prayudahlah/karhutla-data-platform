"""Tujuan tulis Bronze untuk consumer.

Saat ini hanya filesystem lokal di node batch. Interface-nya sengaja sempit
(satu method `write`) supaya nanti bisa ditukar ke BronzeStore Garage
(`put_bytes`) tanpa mengubah consumer.

Layout key (Hive, siap dibaca DuckDB dengan hive_partitioning=true):

    bronze/firms/source=<SOURCE>/ingest_date=<YYYY-MM-DD>/
        ingest_hour=<HH>/part-p<partition>-<offset_awal>-<offset_akhir>.jsonl
"""
import os
from pathlib import Path


def part_key(source, ingest_date, ingest_hour, partition, first_offset, last_offset):
    return (
        f"bronze/firms/source={source}"
        f"/ingest_date={ingest_date}"
        f"/ingest_hour={ingest_hour}"
        f"/part-p{partition}-{first_offset:012d}-{last_offset:012d}.jsonl"
    )


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
            for line in lines:
                fh.write(line if line.endswith(b"\n") else line + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
        return dest
