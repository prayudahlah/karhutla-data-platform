"""Helper isolasi untuk validasi First/Last coverage MCD64A1.

Modul ini sengaja tidak mengetahui Burn Scar, nearest scar, tier, label, atau
Gold. Ia hanya menggabungkan interval observasi per periode dan memeriksa
apakah seluruh tanggal window event tertutup.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class PeriodObservation:
    """Observation yang relevan untuk satu tile/pixel/period."""

    period: str
    source_status: str
    observation_available: bool
    first_day: int | None
    last_day: int | None


@dataclass(frozen=True)
class WindowCoverage:
    """Hasil coverage window; tidak mengandung keputusan label."""

    window_start: date
    window_end: date
    status: str
    covered_dates: tuple[date, ...] = field(default_factory=tuple)
    missing_dates: tuple[date, ...] = field(default_factory=tuple)
    intervals: tuple[tuple[date, date], ...] = field(default_factory=tuple)


def parse_period(period: str) -> tuple[int, int]:
    year_text, month_text = period.split("-", 1)
    year = int(year_text)
    month = int(month_text)
    if not 1 <= month <= 12:
        raise ValueError(f"periode tidak valid: {period!r}")
    return year, month


def period_bounds(period: str) -> tuple[date, date]:
    year, month = parse_period(period)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return start, end


def month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def doy_to_date(year: int, day_of_year: int | None) -> date | None:
    """Konversi DOY ke tanggal; tolak fill/water dan DOY di luar tahun."""
    if day_of_year is None:
        return None
    if day_of_year < 1 or day_of_year > 366:
        return None
    if day_of_year == 366 and not calendar.isleap(year):
        return None
    value = date(year, 1, 1) + timedelta(days=day_of_year - 1)
    if value.year != year:
        return None
    return value


def coverage_interval(
    period: str,
    first_day: int | None,
    last_day: int | None,
) -> tuple[date, date] | None:
    """Iris First/Last dengan batas periode."""
    year, _ = parse_period(period)
    start, end = period_bounds(period)
    first = doy_to_date(year, first_day)
    last = doy_to_date(year, last_day)
    if first is None or last is None or first > last:
        return None
    lower = max(start, first)
    upper = min(end, last)
    if lower > upper:
        return None
    return lower, upper


def validate_window_coverage(
    event_date: date,
    observations: Mapping[str, PeriodObservation] | Iterable[PeriodObservation],
) -> WindowCoverage:
    """Validasi seluruh tanggal dalam window simetris d-7..d+7.

    Raw pixel status usability sengaja tidak diperiksa di sini. Helper hanya
    memeriksa source availability, observation availability, dan interval
    First/Last. Pemakaian raw status menjadi tanggung jawab Batch 2B.
    """
    start = event_date - timedelta(days=7)
    end = event_date + timedelta(days=7)
    required = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    if isinstance(observations, Mapping):
        by_period = observations
    else:
        by_period = {item.period: item for item in observations}

    intervals: list[tuple[date, date]] = []
    covered: set[date] = set()
    usable_source = False
    for period, observation in by_period.items():
        if observation.source_status not in {"available", "identical_duplicate"}:
            continue
        if not observation.observation_available:
            continue
        interval = coverage_interval(period, observation.first_day, observation.last_day)
        if interval is None:
            continue
        usable_source = True
        intervals.append(interval)
        for day in required:
            if interval[0] <= day <= interval[1] and month_key(day) == period:
                covered.add(day)

    missing = tuple(day for day in required if day not in covered)
    if not missing:
        status = "full"
    elif usable_source:
        status = "partial"
    else:
        status = "unknown"
    return WindowCoverage(
        window_start=start,
        window_end=end,
        status=status,
        covered_dates=tuple(sorted(covered)),
        missing_dates=missing,
        intervals=tuple(intervals),
    )
