from __future__ import annotations

import firms_stream
import pytest
import requests

MAP_KEY = "kunci-rahasia-123"
BBOX = "95,-11,141,6"


def test_connection_error_does_not_expose_map_key(monkeypatch) -> None:
    def boom(url: str, timeout: int) -> None:
        raise requests.ConnectionError(
            f"Failed to connect to https://firms.example/api/area/csv/{MAP_KEY}/x"
        )

    monkeypatch.setattr(firms_stream.requests, "get", boom)

    with pytest.raises(RuntimeError) as exc:
        firms_stream.fetch(MAP_KEY, "VIIRS_NOAA20_NRT", BBOX, 1)

    assert MAP_KEY not in str(exc.value)
    assert "VIIRS_NOAA20_NRT" in str(exc.value)


def test_http_error_does_not_expose_map_key(monkeypatch) -> None:
    class Response:
        status_code = 401
        text = "unauthorized"

        def raise_for_status(self) -> None:
            error = requests.HTTPError(
                f"401 Client Error for url: https://firms.example/api/area/csv/{MAP_KEY}/x"
            )
            error.response = self  # type: ignore[assignment]
            raise error

    monkeypatch.setattr(firms_stream.requests, "get", lambda url, timeout: Response())

    with pytest.raises(RuntimeError) as exc:
        firms_stream.fetch(MAP_KEY, "MODIS_NRT", BBOX, 1)

    assert MAP_KEY not in str(exc.value)
    assert "401" in str(exc.value)


def test_non_csv_response_does_not_echo_body(monkeypatch) -> None:
    class Response:
        status_code = 200
        text = "Error: kuota habis untuk kunci " + MAP_KEY

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(firms_stream.requests, "get", lambda url, timeout: Response())

    with pytest.raises(ValueError) as exc:
        firms_stream.fetch(MAP_KEY, "MODIS_NRT", BBOX, 1)

    assert MAP_KEY not in str(exc.value)
