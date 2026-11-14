from __future__ import annotations

from pathlib import Path

from batch.silver.prepare import PUBLISHED_DATASETS, prepare_publish_root


def test_prepare_creates_every_dataset_folder(tmp_path: Path) -> None:
    created = prepare_publish_root(tmp_path)

    assert len(created) == len(PUBLISHED_DATASETS)
    for source, dataset in PUBLISHED_DATASETS:
        assert (tmp_path / source / dataset).is_dir()


def test_prepare_is_idempotent(tmp_path: Path) -> None:
    prepare_publish_root(tmp_path)
    (tmp_path / "open_meteo" / "weather" / "date=2026-11-14").mkdir()

    prepare_publish_root(tmp_path)

    assert (tmp_path / "open_meteo" / "weather" / "date=2026-11-14").is_dir()


def test_prepare_accepts_custom_datasets(tmp_path: Path) -> None:
    created = prepare_publish_root(tmp_path, [("firms", "hotspot")])

    assert created == [tmp_path / "firms" / "hotspot"]
