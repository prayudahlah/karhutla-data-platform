"""Kirim notifikasi Telegram tanpa dependency tambahan (stdlib saja).

Dipakai consumer, yang image-nya tidak memasang requests. Producer tetap
memakai tg_send di firms_stream.py karena di sana requests sudah tersedia.
"""
import json
import os
import urllib.error
import urllib.request

TOPIC_ENV = {
    "hotspot": "TELEGRAM_TOPIC_HOTSPOT",
    "pipeline": "TELEGRAM_TOPIC_PIPELINE",
    "dq": "TELEGRAM_TOPIC_DQ",
    "general": "TELEGRAM_TOPIC_GENERAL",
}


def tg_send(text, topic="general", timeout=15):
    """Return True kalau terkirim. Gagal kirim tidak pernah melempar exception."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"[TG:{topic}] token/chat_id belum di-set, pesan dilewati:\n{text}")
        return False

    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    thread = os.environ.get(TOPIC_ENV.get(topic, ""), "").strip()
    if thread:
        payload["message_thread_id"] = int(thread)

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[TG:{topic}] gagal kirim: {type(exc).__name__}: {exc}")
        return False
