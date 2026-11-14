"""Kontrak event FIRMS v1, dipakai bersama producer dan consumer.

Satu sumber kebenaran untuk: versi skema, key dedup, event_id, dan field wajib.
Jangan duplikasi aturan ini di tempat lain.
"""

import hashlib

SCHEMA_VERSION = 1

# Field yang wajib ada di setiap event. frp boleh null (dq mengukur itu),
# tapi identitas dan waktu tidak boleh.
REQUIRED_FIELDS = (
    "event_id",
    "schema_version",
    "source",
    "latitude",
    "longitude",
    "acq_date",
    "acq_time",
    "satellite",
    "acq_ts_utc",
    "ingested_at",
)

NUMERIC_FIELDS = ("latitude", "longitude")


def make_key(row):
    """Dedup key antar polling: satu hotspot = satu key."""
    return (
        f"{row['latitude']}|{row['longitude']}|{row['acq_date']}|"
        f"{int(row['acq_time']):04d}|{row.get('satellite', '')}"
    )


def event_id_from_key(key):
    return hashlib.sha1(key.encode()).hexdigest()


def validate_event(event):
    """Return daftar masalah. List kosong = event valid."""
    if not isinstance(event, dict):
        return ["event bukan objek JSON"]

    problems = []

    missing = [f for f in REQUIRED_FIELDS if event.get(f) is None]
    if missing:
        problems.append("field wajib kosong: " + ", ".join(missing))

    if event.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version {event.get('schema_version')!r} bukan {SCHEMA_VERSION}")

    for field in NUMERIC_FIELDS:
        value = event.get(field)
        if value is not None and not isinstance(value, (int, float)):
            problems.append(f"{field} bukan angka: {value!r}")

    return problems
