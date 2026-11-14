"""Baca/tulis state dedup dan pruning, tanpa ketergantungan pandas.

Dipisah dari firms_stream.py supaya bisa diuji unit di CI, yang tidak memasang
pandas. Semua penulisan bersifat atomik: file lama tidak pernah setengah jadi.
"""
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def load_set(path):
    """Return (values, error). `error` berisi pesan kalau file ada tapi rusak."""
    path = Path(path)
    if not path.exists():
        return set(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return set(), f"{type(exc).__name__}: {exc}"
    if not isinstance(data, list):
        return set(), f"tipe data {type(data).__name__}, seharusnya list"
    return set(data), None


def save_set(path, values):
    """Tulis set sebagai JSON array secara atomik."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(sorted(values)), encoding="utf-8")
    os.replace(tmp, path)
    return path


def backup(path):
    """Pindahkan file rusak ke <nama>.corrupt. Return path baru atau None."""
    path = Path(path)
    target = path.with_name(path.name + ".corrupt")
    try:
        path.replace(target)
    except OSError:
        return None
    return target


def prune_by_date(values, days, field=2, now=None):
    """Buang entri yang tanggalnya (bagian ke-`field`) lebih tua dari window.

    Key FIRMS berbentuk lat|lon|YYYY-MM-DD|HHMM|satelit, jadi `field=2`.
    Entri yang tidak sesuai format ikut dibuang.
    """
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    kept = set()
    for value in values:
        parts = str(value).split("|")
        if len(parts) > field and parts[field] >= cutoff:
            kept.add(value)
    return kept


def prune_spool_files(root, days, suffix=".jsonl.sent", now=None):
    """Hapus file spool yang sudah terkirim dan lebih tua dari `days`."""
    root = Path(root)
    if not root.exists():
        return 0
    cutoff = (now or time.time()) - days * 86400
    removed = 0
    for path in root.rglob(f"*{suffix}"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
