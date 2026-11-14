"""
Kirim ulang file spool yang belum terkirim ke Redpanda.

File di data/spool/firms/**.jsonl = belum semua event terkirim (pending).
Setelah sukses, file di-rename jadi *.jsonl.sent.

Pakai:
    python stream/src/replay_spool.py --dry-run   # lihat apa yang akan dikirim
    python stream/src/replay_spool.py             # kirim semua
    python stream/src/replay_spool.py --limit 5   # maksimal 5 file
"""
import argparse
import json

from firms_stream import (
    BROKERS,
    SPOOL_DIR,
    TOPIC,
    make_producer,
    mark_sent,
    publish_batch,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="hanya tampilkan, tidak mengirim")
    p.add_argument("--limit", type=int, default=0, help="maksimal file diproses (0 = semua)")
    args = p.parse_args()

    files = sorted(SPOOL_DIR.rglob("*.jsonl"))  # *.jsonl.sent tidak ikut
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"Tidak ada file pending di {SPOOL_DIR}")
        return

    total = sent = 0
    producer = None if args.dry_run else make_producer()
    for f in files:
        events = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        total += len(events)
        if args.dry_run:
            print(f"[dry-run] {f} -> {len(events)} event")
            continue

        ok, failed = publish_batch(events, producer)
        sent += len(ok)
        print(f"{f} -> {len(ok)} ok, {len(failed)} gagal")
        if not failed:
            mark_sent(f)

    if producer is not None:
        producer.flush(10)
        print(f"selesai: {sent}/{total} event terkirim ke {BROKERS}/{TOPIC}")
    else:
        print(f"selesai (dry-run): {total} event pending di {len(files)} file")


if __name__ == "__main__":
    main()
