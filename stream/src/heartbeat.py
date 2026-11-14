"""Heartbeat proses untuk healthcheck container.

Container bisa "Up" padahal prosesnya tidak melakukan apa-apa (mis. MAP_KEY
dicabut, broker mati, consumer macet). File heartbeat yang diperbarui tiap
siklus membuat kondisi itu terlihat oleh Docker healthcheck.

Pembacaan heartbeat di healthcheck sengaja tidak mengimpor modul ini, cukup
memeriksa mtime file, supaya tidak bergantung pada layout paket di image.
"""
import json
import os
import time
from pathlib import Path


def beat(path, **extra):
    """Tulis heartbeat secara atomik."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ping_at": time.time(), **extra}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read(path):
    """Return isi heartbeat, atau None kalau belum ada / rusak."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
