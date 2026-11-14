"""
Stream NASA FIRMS -> Redpanda + spool lokal sebagai WAL.

Alur satu polling:
    fetch FIRMS -> dedup (state) -> tulis spool JSONL -> publish ke Redpanda -> alert Telegram

Spool lokal adalah jaring pengaman. Selama file masih bernama *.jsonl (belum *.sent),
isinya belum tentu semua terkirim ke broker; kirim ulang dengan:
    python stream/src/replay_spool.py

Topik Telegram:
    hotspot  : hotspot baru
    pipeline : error, pemulihan, data basi
    dq       : hasil cek data quality
    general  : info umum (start, tes)

Setup env:
    FIRMS_MAP_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (id grup, diawali -100)
    TELEGRAM_TOPIC_HOTSPOT, TELEGRAM_TOPIC_PIPELINE, TELEGRAM_TOPIC_DQ, TELEGRAM_TOPIC_GENERAL
    (isi dengan message_thread_id tiap topik; kosong = kirim ke General)
    REDPANDA_BROKERS (default stream:9092), REDPANDA_TOPIC (default firms.hotspot.raw)

Pakai:
    python stream/src/firms_stream.py --discover-topics       # cari thread id tiap topik
    python stream/src/firms_stream.py --once --test-telegram  # tes kirim ke semua topik
    python stream/src/firms_stream.py --selftest-publish      # tes broker tanpa API FIRMS
    python stream/src/firms_stream.py --interval 600 --min-frp 10 --min-conf high
"""

import argparse
import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests
from event_schema import SCHEMA_VERSION, event_id_from_key, make_key

try:  # baca file .env otomatis (stream/.env) jika python-dotenv terpasang
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
INDONESIA_BBOX = "95,-11,141,6"  # west,south,east,north

# DATA_DIR relatif dihitung dari folder stream/, bukan dari cwd,
# supaya aman dijalankan sebagai service dengan working directory lain.
_STREAM_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _STREAM_DIR / "data"
DATA_DIR = Path(os.environ.get("DATA_DIR") or _DEFAULT_DATA_DIR)
if not DATA_DIR.is_absolute():
    DATA_DIR = _STREAM_DIR / DATA_DIR

SPOOL_DIR = DATA_DIR / "spool/firms"
STATE_FILE = DATA_DIR / "state/firms_seen.json"

BROKERS = os.environ.get("REDPANDA_BROKERS", "stream:9092")
TOPIC = os.environ.get("REDPANDA_TOPIC", "firms.hotspot.raw")

TOPIC_ENV = {
    "hotspot": "TELEGRAM_TOPIC_HOTSPOT",
    "pipeline": "TELEGRAM_TOPIC_PIPELINE",
    "dq": "TELEGRAM_TOPIC_DQ",
    "general": "TELEGRAM_TOPIC_GENERAL",
}


# ---------------------------------------------------------------- Telegram
def tg_send(text, topic="general"):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"[TG:{topic}] token/chat_id belum di-set, pesan dilewati:\n{text}")
        return False
    payload = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    thread = os.environ.get(TOPIC_ENV.get(topic, ""), "").strip()
    if thread:
        payload["message_thread_id"] = int(thread)
    for attempt in range(1, 4):  # retry 3x: koneksi ke Telegram kadang lambat/putus
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=(10, 40)
            )
            if r.status_code == 200:
                return True
            if r.status_code == 429:  # kena rate limit, tunggu sesuai saran Telegram
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 3)) + 1)
                continue
            print(f"[TG:{topic}] gagal kirim: {r.status_code} {r.text[:200]}")
            return False  # error permanen (token salah, thread tidak ada, dll): tidak perlu retry
        except Exception as e:
            print(f"[TG:{topic}] percobaan {attempt}/3 gagal: {type(e).__name__}")
            time.sleep(2 * attempt)
    return False


def tg_discover_topics():
    """Cetak chat_id dan message_thread_id dari pesan terbaru yang diterima bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set dulu TELEGRAM_BOT_TOKEN")
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    rows = {}
    for u in r.get("result", []):
        m = u.get("message") or u.get("channel_post") or {}
        chat = m.get("chat", {})
        tid = m.get("message_thread_id", 0)  # 0 = General
        name = (m.get("forum_topic_created") or {}).get("name")
        key = (chat.get("id"), tid)
        snippet = name or (m.get("text") or "")[:40]
        rows.setdefault(key, (chat.get("title"), snippet))
        if name:
            rows[key] = (chat.get("title"), f"[topik] {name}")
    if not rows:
        print("Belum ada pesan. Kirim satu pesan di tiap topik (mention bot), lalu jalankan ulang.")
        return
    print(f"{'chat_id':>16} | {'thread_id':>9} | grup / contoh pesan")
    for (cid, tid), (title, snip) in sorted(rows.items()):
        print(f"{cid:>16} | {tid:>9} | {title} / {snip}")
    print("\nthread_id 0 = General (kosongkan variabelnya). Isi thread_id ke TELEGRAM_TOPIC_*.")


# ---------------------------------------------------------------- FIRMS
def fetch(map_key, source, bbox, day_range, timeout=60):
    url = f"{BASE_URL}/{map_key}/{source}/{bbox}/{day_range}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    if "latitude" not in resp.text[:300]:
        raise ValueError(f"Respons bukan CSV valid: {resp.text[:200]!r}")
    return pd.read_csv(io.StringIO(resp.text))


def load_seen():
    return set(json.loads(STATE_FILE.read_text())) if STATE_FILE.exists() else set()


def save_seen(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def add_latency(df, now):
    t = df["acq_time"].astype(int).astype(str).str.zfill(4)
    acq = pd.to_datetime(df["acq_date"].astype(str) + " " + t, format="%Y-%m-%d %H%M", utc=True)
    df["acq_ts_utc"] = acq.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["acq_wib"] = acq.dt.tz_convert("Asia/Jakarta").dt.strftime("%d-%m %H:%M")
    df["latency_min"] = ((now - acq).dt.total_seconds() / 60).round(1)
    return df


def add_event_id(df):
    """event_id = sha1 dari dedup key, stabil lintas restart dan lintas mesin."""
    df["event_id"] = df["_key"].map(event_id_from_key)
    return df


def write_spool(df, source, now):
    """Tulis batch ke disk sebagai WAL. File *.jsonl = belum semua terkirim."""
    part = SPOOL_DIR / f"source={source}" / f"ingest_date={now.strftime('%Y-%m-%d')}"
    part.mkdir(parents=True, exist_ok=True)
    out = part / f"batch_{now.strftime('%H%M%S')}.jsonl"
    df.drop(columns=["_key"], errors="ignore").to_json(out, orient="records", lines=True)
    return out


def mark_sent(path):
    path.replace(path.with_suffix(".jsonl.sent"))


# ---------------------------------------------------------------- Redpanda
def make_producer():
    from confluent_kafka import Producer

    return Producer(
        {
            "bootstrap.servers": BROKERS,
            "client.id": "firms-producer",
            "enable.idempotence": True,  # otomatis acks=all, retries>0, tanpa duplikat karena retry
            "acks": "all",
            "retries": 5,
            "linger.ms": 50,
            "compression.type": "gzip",
            "message.timeout.ms": 30000,
        }
    )


def to_events(df):
    """DataFrame -> list event sesuai kontrak v1 (flat, satu objek per hotspot)."""
    clean = df.drop(columns=["_key"], errors="ignore")
    return json.loads(clean.to_json(orient="records"))


def publish_batch(events, producer):
    """Kirim semua event ke topik. Return (set id sukses, set id gagal)."""
    ok = set()

    def on_delivery(err, msg):
        key = msg.key().decode() if msg.key() else ""
        if err is None:
            ok.add(key)
        else:
            print(f"[WARN] kirim {key[:12]} gagal: {err}")

    for ev in events:
        producer.produce(
            TOPIC,
            key=ev["event_id"].encode(),
            value=json.dumps(ev, ensure_ascii=False).encode(),
            headers={"schema_version": str(SCHEMA_VERSION), "source": ev["source"]},
            on_delivery=on_delivery,
        )
        producer.poll(0)  # jalankan callback, jaga queue tidak penuh

    pending = producer.flush(30)
    if pending:
        print(f"[WARN] {pending} event belum terkirim setelah flush 30 detik")
    return ok, {e["event_id"] for e in events} - ok


# ---------------------------------------------------------------- Data quality
def quality_checks(new):
    """Return list (nama_cek, persen_lolos, ambang_min)."""
    n = len(new)

    def pct(series):
        return float(series.mean()) * 100

    return [
        ("Latitude dalam rentang Indonesia (-11..6)", pct(new["latitude"].between(-11, 6)), 100.0),
        (
            "Longitude dalam rentang Indonesia (95..141)",
            pct(new["longitude"].between(95, 141)),
            100.0,
        ),
        ("FRP tidak null", pct(new["frp"].notna()), 99.0),
        ("FRP >= 0", pct(new["frp"].fillna(0) >= 0), 100.0),
        ("Confidence tidak null", pct(new["confidence"].notna()), 99.0),
        ("Latensi >= 0 (waktu valid)", pct(new["latency_min"] >= 0), 100.0),
    ], n


def send_dq_report(new, source, verbose):
    checks, n = quality_checks(new)
    failed = [c for c in checks if c[1] < c[2]]
    if failed:
        lines = [f"❌ DATA QUALITY GAGAL ({source})", f"{n} baris baru diperiksa", ""]
        for name, p, thr in failed:
            lines.append(f"• {name}: {p:.1f}% (min {thr:.0f}%)")
        tg_send("\n".join(lines), "dq")
    elif verbose:
        tg_send(
            f"✅ Data Quality OK ({source}): {len(checks)}/{len(checks)} cek lolos, "
            f"{n} baris diperiksa.",
            "dq",
        )


# ---------------------------------------------------------------- Filter alert
def conf_mask(df, min_conf):
    """VIIRS: l/n/h. MODIS: angka 0-100. min_conf: low | nominal | high."""
    c = df["confidence"].astype(str).str.lower()
    letter_rank = {"l": 1, "n": 2, "h": 3}
    want_letter = {"low": 1, "nominal": 2, "high": 3}[min_conf]
    want_num = {"low": 0, "nominal": 30, "high": 80}[min_conf]
    is_letter = c.isin(letter_rank.keys())
    ok_letter = c.map(letter_rank).fillna(0) >= want_letter
    num = pd.to_numeric(c, errors="coerce").fillna(-1)
    return (is_letter & ok_letter) | (~is_letter & (num >= want_num))


def build_alert(new, source, args, total_new):
    sel = new[conf_mask(new, args.min_conf) & (new["frp"].fillna(0) >= args.min_frp)]
    if sel.empty:
        return None
    sel = sel.sort_values("frp", ascending=False)
    lines = [
        f"🔥 HOTSPOT BARU ({source})",
        f"{len(sel)} titik lolos filter (dari {total_new} baru) "
        f"| conf>={args.min_conf}, FRP>={args.min_frp}",
        "",
    ]
    for _, r in sel.head(args.top).iterrows():
        lines.append(
            f"• {r['acq_wib']} WIB | FRP {r['frp']} MW | conf {r['confidence']}\n"
            f"  {r['latitude']:.3f}, {r['longitude']:.3f}\n"
            f"  https://www.google.com/maps?q={r['latitude']},{r['longitude']}"
        )
    if len(sel) > args.top:
        lines.append(f"\n...dan {len(sel) - args.top} titik lain (lihat topik firms.hotspot.raw).")
    lines.append(f"\nLatensi median: {sel['latency_min'].median()} menit")
    return "\n".join(lines)


# ---------------------------------------------------------------- Polling
def poll_once(map_key, args, seen, first_run, source):
    now = pd.Timestamp.now(tz="UTC")
    df = fetch(map_key, source, args.bbox, args.day_range)
    total = len(df)
    if total == 0:
        print(f"[{now:%H:%M:%S}] 0 baris dari API")
        return 0

    df["_key"] = df.apply(make_key, axis=1)
    new = df[~df["_key"].isin(seen)].copy()
    print(f"[{now:%H:%M:%S}] API: {total} baris | baru: {len(new)}")
    if new.empty:
        return 0

    new = add_latency(new, now)
    new["ingested_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new["source"] = source
    new["schema_version"] = SCHEMA_VERSION
    new = add_event_id(new)

    path = write_spool(new, source, now)
    seen.update(new["_key"])
    save_seen(seen)  # state disimpan setelah spool ada di disk
    print(f"    -> spool {path} | latensi median {new['latency_min'].median()} menit")

    events = to_events(new)
    if args.publish:
        ok, failed = publish_batch(events, args.producer)
        if failed:
            print(
                f"    -> Redpanda: {len(ok)} ok, {len(failed)} gagal; "
                "file tetap *.jsonl untuk replay"
            )
        else:
            mark_sent(path)
            print(f"    -> Redpanda: {len(ok)} event -> {BROKERS}/{TOPIC}")
    else:
        print(f"    -> publish dimatikan, {len(events)} event hanya ada di spool")

    send_dq_report(new, source, args.dq_verbose)

    # Run pertama: jangan banjiri chat dengan semua data awal, cukup ringkasan
    if first_run:
        tg_send(
            f"✅ FIRMS stream dimulai ({source}). Muat awal {len(new)} titik dikirim ke Redpanda. "
            f"Alert hotspot detail aktif mulai polling berikutnya.",
            "general",
        )
    else:
        msg = build_alert(new, source, args, len(new))
        if msg:
            tg_send(msg, "hotspot")
    return len(new)


def poll_all(map_key, args, seen, first_run):
    """Poll semua sumber. Satu sumber gagal tidak menghentikan sumber lain."""
    total, errors = 0, []
    for i, src in enumerate(args.sources):
        if i:
            time.sleep(1)
        try:
            total += poll_once(map_key, args, seen, first_run, src)
        except Exception as e:
            errors.append(f"{src}: {e}")
            print(f"[WARN] {src} gagal: {e}")
    if len(errors) == len(args.sources):  # semua gagal -> picu retry/backoff
        raise RuntimeError(" | ".join(errors)[:500])
    return total


def selftest_publish():
    """Kirim 3 event sintetis ke topik. Untuk tes broker tanpa memanggil API FIRMS."""
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for i, (lat, lon) in enumerate([(-0.5, 101.5), (-2.2, 114.0), (-6.9, 107.6)]):
        acq = now - pd.Timedelta(minutes=30 * (i + 1))
        rows.append(
            {
                "latitude": lat,
                "longitude": lon,
                "brightness": 320.0 + i,
                "scan": 1.0,
                "track": 1.0,
                "acq_date": acq.strftime("%Y-%m-%d"),
                "acq_time": int(acq.strftime("%H%M")),
                "satellite": "SELFTEST",
                "instrument": "VIIRS",
                "confidence": 80,
                "version": "2.0NRT",
                "bright_t31": 295.0,
                "frp": 10.0 + i,
                "daynight": "D",
            }
        )
    df = add_latency(pd.DataFrame(rows), now)
    df["_key"] = df.apply(make_key, axis=1)
    df["ingested_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["source"] = "SELFTEST"
    df["schema_version"] = SCHEMA_VERSION
    df = add_event_id(df)

    ok, failed = publish_batch(to_events(df), make_producer())
    print(f"selftest: {len(ok)} terkirim, {len(failed)} gagal -> {BROKERS}/{TOPIC}")
    if failed:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source",
        default="VIIRS_NOAA20_NRT,VIIRS_NOAA21_NRT,MODIS_NRT",
        help="satu atau beberapa sumber, dipisah koma",
    )
    p.add_argument("--bbox", default=INDONESIA_BBOX)
    p.add_argument("--day-range", type=int, default=1)
    p.add_argument("--interval", type=int, default=600, help="detik antar polling")
    p.add_argument("--min-conf", choices=["low", "nominal", "high"], default="nominal")
    p.add_argument("--min-frp", type=float, default=5.0, help="FRP minimum (MW) untuk alert")
    p.add_argument("--top", type=int, default=8, help="jumlah titik ditampilkan per alert")
    p.add_argument("--fail-alert-after", type=int, default=3, help="alert setelah N error beruntun")
    p.add_argument(
        "--stale-hours", type=float, default=12, help="alert jika tak ada data baru selama X jam"
    )
    p.add_argument(
        "--dq-verbose", action="store_true", help="kirim juga laporan DQ yang lolos (✅)"
    )
    p.add_argument(
        "--no-publish", action="store_true", help="hanya tulis spool, jangan kirim ke Redpanda"
    )
    p.add_argument(
        "--selftest-publish",
        action="store_true",
        help="kirim 3 event sintetis ke topik lalu keluar",
    )
    p.add_argument("--once", action="store_true")
    p.add_argument("--test-telegram", action="store_true")
    p.add_argument("--discover-topics", action="store_true")
    args = p.parse_args()
    args.sources = [x.strip() for x in args.source.split(",") if x.strip()]
    args.publish = not args.no_publish

    if args.discover_topics:
        tg_discover_topics()
        return

    if args.selftest_publish:
        selftest_publish()
        return

    map_key = os.environ.get("FIRMS_MAP_KEY")
    if not map_key:
        raise SystemExit("Set dulu env FIRMS_MAP_KEY")

    if args.publish:
        try:
            args.producer = make_producer()
        except ImportError:
            raise SystemExit(
                "confluent-kafka belum terpasang: pip install -r stream/requirements.txt"
            ) from None
        print(f"[START] publish aktif -> {BROKERS}/{TOPIC}")
    else:
        args.producer = None
        print("[START] publish dimatikan, hanya spool lokal")

    if args.test_telegram:
        for t, label in [
            ("general", "General"),
            ("hotspot", "Hotspot Alerts"),
            ("pipeline", "Pipeline Alerts"),
            ("dq", "Data Quality Alerts"),
        ]:
            ok = tg_send(f"✅ Tes alert FIRMS stream: topik {label} OK.", t)
            print(f"Telegram [{label}]:", "terkirim" if ok else "GAGAL")
            time.sleep(1)

    first_run = not STATE_FILE.exists()
    seen = load_seen()
    fails, backoff = 0, 30
    last_new_ts = time.time()
    stale_alerted = False

    while True:
        try:
            n = poll_all(map_key, args, seen, first_run)
            first_run = False
            if fails >= args.fail_alert_after:
                tg_send(f"✅ FIRMS stream pulih setelah {fails} error beruntun.", "pipeline")
            fails, backoff = 0, 30

            if n > 0:
                last_new_ts, stale_alerted = time.time(), False
            elif (time.time() - last_new_ts) > args.stale_hours * 3600 and not stale_alerted:
                tg_send(
                    f"⚠️ Tidak ada hotspot baru dari {args.source} (semua sumber) "
                    f"selama >{args.stale_hours} jam. "
                    f"Cek apakah API/satelit bermasalah.",
                    "pipeline",
                )
                stale_alerted = True
        except Exception as e:
            fails += 1
            print(f"[ERROR] {e} -> retry {backoff}s (error beruntun: {fails})")
            if fails == args.fail_alert_after:
                tg_send(f"🚨 FIRMS stream ERROR {fails}x beruntun:\n{str(e)[:500]}", "pipeline")
            if args.once:
                raise
            time.sleep(backoff)
            backoff = min(backoff * 2, 600)
            continue

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
