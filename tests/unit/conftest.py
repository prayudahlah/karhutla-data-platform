from __future__ import annotations

import pytest


@pytest.fixture
def hotspot_factory():
    """Buat tabel hotspot sintetis dengan kolom seperti Silver."""

    def factory(days: int = 3, rows_per_day: int = 2):
        pd = pytest.importorskip("pandas")
        start = pd.Timestamp("2026-01-01")
        tiers = ("kandidat", "lemah", "sedang", "kuat")
        rows = []
        for day in range(days):
            current = start + pd.Timedelta(days=day)
            for item in range(rows_per_day):
                index = day * rows_per_day + item
                rows.append(
                    {
                        "event_id": f"e{index:06d}",
                        "date": current,
                        "latitude": 0.5071 + item * 0.01,
                        "longitude": 101.4478 + item * 0.01,
                        "acq_ts_utc": current + pd.Timedelta(hours=5, minutes=30),
                        "acq_date": current.date(),
                        "acq_time": "0530",
                        "source": "VIIRS_NOAA20_NRT",
                        "satellite": "N20",
                        "instrument": "VIIRS",
                        "confidence": "n",
                        "confidence_score": None,
                        "frp": 10.0 + index,
                        "brightness": 330.0,
                        "brightness_secondary": 300.0,
                        "scan": 0.4,
                        "track": 0.4,
                        "daynight": "D",
                        "tier": tiers[index % len(tiers)],
                        "burn_date": current.date(),
                        "gap_days": 0,
                        "in_bbox": True,
                    }
                )
        return pd.DataFrame(rows)

    return factory


@pytest.fixture
def weather_factory():
    """Buat tabel cuaca sintetis per provinsi/jam."""

    def factory(days: int = 3, province: str = "Riau", start: str = "2026-01-01"):
        pd = pytest.importorskip("pandas")
        start_date = pd.Timestamp(start)
        rows = []
        for day in range(days):
            current = start_date + pd.Timedelta(days=day)
            for hour in (0, 6, 12, 18):
                rows.append(
                    {
                        "province": province,
                        "city": "Pekanbaru",
                        "date": current,
                        "ts_utc": current + pd.Timedelta(hours=hour),
                        "temperature_2m": 28.0 + hour / 6.0,
                        "relative_humidity_2m": 80.0 - hour,
                        "precipitation": 0.5 if hour == 12 else 0.0,
                        "wind_speed_10m": 5.0 + hour / 12.0,
                        "soil_moisture_0_to_7cm": 0.25,
                        "vapour_pressure_deficit": 1.0 + hour / 24.0,
                        "et0_fao_evapotranspiration": 0.1,
                    }
                )
        return pd.DataFrame(rows)

    return factory


@pytest.fixture
def air_quality_factory():
    """Buat tabel kualitas udara sintetis per provinsi/jam."""

    def factory(days: int = 3, province: str = "Riau", start: str = "2026-01-01"):
        pd = pytest.importorskip("pandas")
        start_date = pd.Timestamp(start)
        rows = []
        for day in range(days):
            current = start_date + pd.Timedelta(days=day)
            for hour in (0, 6, 12, 18):
                rows.append(
                    {
                        "province": province,
                        "city": "Pekanbaru",
                        "date": current,
                        "ts_utc": current + pd.Timedelta(hours=hour),
                        "pm2_5": 10.0 + hour,
                        "pm10": 20.0 + hour,
                        "carbon_monoxide": 100.0 + hour,
                        "aerosol_optical_depth": 0.2 + hour / 100.0,
                    }
                )
        return pd.DataFrame(rows)

    return factory


@pytest.fixture
def cell_factory():
    """Buat tabel Gold sel-hari sintetis dengan kolom seperti gold_hotspot_cell_day."""

    def factory(days: int = 6, cells: int = 2, complete: bool = True):
        pd = pytest.importorskip("pandas")
        start = pd.Timestamp("2026-09-01")
        rows = []
        for day in range(days):
            current = start + pd.Timedelta(days=day)
            for cell in range(cells):
                if cell == 0:
                    cell_y, cell_x = 2, 405  # Riau
                else:
                    cell_y, cell_x = -26, 425  # DKI Jakarta, provinsi berbeda
                n_hotspot = 1 + ((day + cell) % 5)
                label = int((day + cell) % 2 == 0)
                rows.append(
                    {
                        "cell_id": f"{cell_y}_{cell_x}",
                        "cell_y": cell_y,
                        "cell_x": cell_x,
                        "center_lat": cell_y * 0.25 + 0.125,
                        "center_lon": cell_x * 0.25 + 0.125,
                        "date": current,
                        "n_hotspot": n_hotspot,
                        "n_night": n_hotspot // 2,
                        "n_satellite": 1 + cell,
                        "n_viirs": max(n_hotspot - 1, 0),
                        "frp_max": 10.0 + day + cell,
                        "frp_mean": 5.0 + day / 2,
                        "frp_p95": 8.0 + day,
                        "brightness_max": 350.0,
                        "brightness_mean": 330.0,
                        "brightness_diff_max": 20.0,
                        "confidence_max": 90.0,
                        "confidence_mean": 70.0,
                        "scan_max": 0.5,
                        "track_max": 0.4,
                        "hour_of_max_frp": 5 + day % 3,
                        "hour_sin_mean": 0.8,
                        "hour_cos_mean": -0.1,
                        "label": label,
                        "label_complete": complete,
                        "audit_tier_max": "kuat" if label else "kandidat",
                        "audit_n_confirmed": max(n_hotspot - 1, 1) if label else 0,
                        "audit_n_weak": 0,
                        "audit_n_candidate": 0 if label else n_hotspot,
                        "audit_n_tile": 1,
                    }
                )
        return pd.DataFrame(rows)

    return factory
