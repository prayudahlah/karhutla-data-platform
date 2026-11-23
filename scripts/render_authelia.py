"""Render infra/authelia/configuration.yml dari templat dan environment.

Kenapa dirender, bukan dibaca langsung: Authelia memakai domain dan skema di
beberapa tempat (cookie, redirect, access control), dan menulisnya sebagai
variabel environment di YAML tidak selalu jelas urutannya. Satu berkas hasil
render lebih mudah diperiksa saat demo.

Jalankan: python scripts/render_authelia.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra" / "authelia" / "configuration.yml.tpl"
OUTPUT = ROOT / "infra" / "authelia" / "configuration.yml"

DEFAULT_SECRET = "ganti-secret-ini-di-env-minimal-32-karakter"


def main() -> int:
    base_domain = os.environ.get("BASE_DOMAIN", "localhost").strip()
    scheme = os.environ.get("SCHEME", "http").strip().lower()
    secret = os.environ.get("AUTHELIA_SESSION_SECRET", "").strip()

    if scheme not in {"http", "https"}:
        print(f"SCHEME harus http atau https, bukan {scheme!r}", file=sys.stderr)
        return 2
    if not base_domain:
        print("BASE_DOMAIN tidak boleh kosong", file=sys.stderr)
        return 2
    if len(secret) < 32:
        print(
            "AUTHELIA_SESSION_SECRET belum diisi atau kurang dari 32 karakter; "
            "memakai nilai contoh. Jangan dipakai di luar demo.",
            file=sys.stderr,
        )
        secret = DEFAULT_SECRET

    rendered = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__BASE_DOMAIN__", base_domain)
        .replace("__SCHEME__", scheme)
        .replace("__SESSION_SECRET__", secret)
        .replace("__COOKIE_SECURE__", "true" if scheme == "https" else "false")
    )
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"ditulis: {OUTPUT.relative_to(ROOT)}")
    print(f"domain : {scheme}://app.{base_domain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
