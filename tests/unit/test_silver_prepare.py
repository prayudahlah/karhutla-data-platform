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


def test_ensure_profiles_copies_example_when_missing(tmp_path: Path) -> None:
    from batch.silver.prepare import ensure_profiles

    (tmp_path / "profiles.yml.example").write_text("karhutla:\n  target: dev\n")

    created = ensure_profiles(tmp_path)

    assert created == tmp_path / "profiles.yml"
    assert (tmp_path / "profiles.yml").exists()


def test_ensure_profiles_keeps_existing_file(tmp_path: Path) -> None:
    from batch.silver.prepare import ensure_profiles

    (tmp_path / "profiles.yml.example").write_text("contoh")
    (tmp_path / "profiles.yml").write_text("milik pengguna")

    assert ensure_profiles(tmp_path) is None
    assert (tmp_path / "profiles.yml").read_text() == "milik pengguna"


def test_ensure_profiles_raises_without_example(tmp_path: Path) -> None:
    import pytest

    from batch.silver.prepare import ensure_profiles

    with pytest.raises(FileNotFoundError):
        ensure_profiles(tmp_path)
