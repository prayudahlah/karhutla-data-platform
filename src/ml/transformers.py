"""Transformer kecil untuk pipeline ML.

Diletakkan di modul tersendiri supaya objek yang disimpan dengan joblib bisa
dimuat dari proses lain. Fungsi yang didefinisikan di ``ml.train`` akan
ter-pickle sebagai ``__main__`` ketika modul dijalankan lewat ``python -m``.
"""

from __future__ import annotations

import pandas as pd


def stringify_categorical(frame: pd.DataFrame) -> pd.DataFrame:
    """Ubah kategori pandas menjadi objek string yang aman untuk one-hot."""
    return frame.astype("string").fillna("TIDAK_DIKETAHUI").astype(object)
