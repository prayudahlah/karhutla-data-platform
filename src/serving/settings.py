"""Konfigurasi layanan serving Gold.

Semua nilai bisa dioverride lewat environment supaya container dan test bisa
memakai akar data yang berbeda tanpa mengubah kode.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    """Pengaturan aplikasi FastAPI."""

    gold_root: Path = field(
        default_factory=lambda: _env_path("GOLD_PUBLISH_ROOT", "data/gold/published")
    )
    title: str = "Karhutla Gold API"
    version: str = "0.1.0"
    max_limit: int = 1000
    default_limit: int = 200

    @property
    def gold_tables(self) -> tuple[str, ...]:
        return ("province_daily", "burn_scar_monthly", "cell_daily")
