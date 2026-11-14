"""Watermark freshness per sumber: max(acq_ts_utc) yang pernah masuk Bronze."""

import json
import os
from pathlib import Path


def load(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # File rusak jangan sampai menghentikan consumer; mulai dari kosong.
        return {}


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)  # atomik: file lama tidak pernah setengah tertulis


def update(path, source, acq_ts_utc):
    """Simpan watermark terbaru untuk sumber. Return nilai terbaru."""
    data = load(path)
    current = data.get(source, "")
    if acq_ts_utc and acq_ts_utc > current:
        data[source] = acq_ts_utc
        save(path, data)
        return acq_ts_utc
    return current
