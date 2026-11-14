from __future__ import annotations

import json

import httpx
import pytest

from common.config import BurnedAreaSettings
from ingest.burned_area.cmr import (
    CmrClient,
    CmrError,
    granule_from_entry,
    granule_id_to_month,
    month_window,
    parse_month,
)


def _entry(granule_id: str, size: float = 193258.0) -> dict:
    return {
        "title": granule_id,
        "granule_size": str(size),
        "links": [
            {"href": "https://example.invalid/readme.txt"},
            {"href": f"https://data.example.invalid/{granule_id}/{granule_id}.hdf"},
        ],
    }


def test_parse_month_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError):
        parse_month("2026-9-1")


def test_month_window_covers_whole_month() -> None:
    start, end = month_window("2026-09")

    assert start == "2026-09-01T00:00:00Z"
    assert end == "2026-09-30T23:59:59Z"


def test_month_window_handles_february() -> None:
    _, end = month_window("2024-02")

    assert end.startswith("2024-02-29")


def test_granule_id_becomes_month() -> None:
    assert granule_id_to_month("MCD64A1.A2026244.h28v09.061.2026314124402") == "2026-09"


def test_granule_id_with_bad_date_raises() -> None:
    with pytest.raises(CmrError):
        granule_id_to_month("MCD64A1.A2026999.h28v09.061.2026314124402")


def test_granule_entry_picks_hdf_link_only() -> None:
    granule = granule_from_entry(_entry("MCD64A1.A2026244.h28v09.061.2026314124402"))

    assert granule.tile == "h28v09"
    assert granule.month == "2026-09"
    assert granule.url.endswith(".hdf")
    assert granule.filename == "MCD64A1.A2026244.h28v09.061.2026314124402.hdf"


def test_granule_entry_without_hdf_raises() -> None:
    with pytest.raises(CmrError):
        granule_from_entry({"title": "MCD64A1.A2026244.h28v09.061", "links": []})


def test_search_month_filters_other_months() -> None:
    september = _entry("MCD64A1.A2026244.h28v09.061.2026314124402")
    august = _entry("MCD64A1.A2026213.h27v09.061.2026286113023")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"feed": {"entry": [september, august]}})

    settings = BurnedAreaSettings(token="token", page_size=10)
    with CmrClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as cmr:
        granules = cmr.search_month("2026-09")

    assert [granule.granule_id for granule in granules] == [
        "MCD64A1.A2026244.h28v09.061.2026314124402"
    ]


def test_search_month_follows_pagination() -> None:
    seen_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page_num"]
        seen_pages.append(page)
        if page == "1":
            entries = [
                _entry("MCD64A1.A2026244.h28v08.061.2026314124402"),
                _entry("MCD64A1.A2026244.h28v09.061.2026314124402"),
            ]
        else:
            entries = [_entry("MCD64A1.A2026244.h28v10.061.2026314124402")]
        return httpx.Response(200, json={"feed": {"entry": entries}})

    settings = BurnedAreaSettings(token="token", page_size=2)
    with CmrClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as cmr:
        granules = cmr.search_month("2026-09")

    assert seen_pages == ["1", "2"]
    assert len(granules) == 3


def test_latest_month_reads_newest_granule() -> None:
    entry = _entry("MCD64A1.A2026244.h28v09.061.2026314124402")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sort_key"] == "-start_date"
        return httpx.Response(200, json={"feed": {"entry": [entry]}})

    settings = BurnedAreaSettings(token="token")
    with CmrClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as cmr:
        assert cmr.latest_month() == "2026-09"


def test_latest_month_returns_none_when_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"feed": {"entry": []}})

    settings = BurnedAreaSettings(token="token")
    with CmrClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as cmr:
        assert cmr.latest_month() is None


def test_search_month_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    settings = BurnedAreaSettings(token="token", max_retries=1)
    with CmrClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler))) as cmr:
        with pytest.raises(CmrError):
            cmr.search_month("2026-09")


def test_config_snapshot_hides_token() -> None:
    from ingest.burned_area.ingest import config_snapshot

    snapshot = config_snapshot(BurnedAreaSettings(token="rahasia"))

    assert "rahasia" not in json.dumps(snapshot)
    assert snapshot["has_token"] is True
