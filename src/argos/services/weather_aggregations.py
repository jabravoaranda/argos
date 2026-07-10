from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from argos.models.ecowitt import WeatherObservation


@dataclass(frozen=True, slots=True)
class WeatherPeriodSummary:
    period_start: date
    period_end: date
    sample_count: int
    outdoor_temperature_mean_c: float | None
    outdoor_temperature_min_c: float | None
    outdoor_temperature_max_c: float | None
    outdoor_humidity_mean_pct: float | None
    relative_pressure_mean_hpa: float | None
    wind_gust_max_ms: float | None
    solar_radiation_max_wm2: float | None
    uv_index_max: float | None
    rain_day_max_mm: float | None
    rain_event_max_mm: float | None
    rain_last_24h_max_mm: float | None


def summarize_daily(observations: Iterable[WeatherObservation]) -> list[WeatherPeriodSummary]:
    grouped: dict[date, list[WeatherObservation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.observed_at_utc.date()].append(observation)

    return [_summarize_period(day, day, grouped[day]) for day in sorted(grouped)]


def summarize_weekly(observations: Iterable[WeatherObservation]) -> list[WeatherPeriodSummary]:
    grouped: dict[date, list[WeatherObservation]] = defaultdict(list)
    for observation in observations:
        week_start = observation.observed_at_utc.date()
        week_start = week_start.fromisocalendar(week_start.isocalendar().year, week_start.isocalendar().week, 1)
        grouped[week_start].append(observation)

    return [
        _summarize_period(week_start, grouped[week_start][-1].observed_at_utc.date(), grouped[week_start])
        for week_start in sorted(grouped)
    ]


def _summarize_period(
    period_start: date,
    period_end: date,
    observations: list[WeatherObservation],
) -> WeatherPeriodSummary:
    return WeatherPeriodSummary(
        period_start=period_start,
        period_end=period_end,
        sample_count=len(observations),
        outdoor_temperature_mean_c=_mean(observation.outdoor_temperature_c for observation in observations),
        outdoor_temperature_min_c=_min(observation.outdoor_temperature_c for observation in observations),
        outdoor_temperature_max_c=_max(observation.outdoor_temperature_c for observation in observations),
        outdoor_humidity_mean_pct=_mean(observation.outdoor_humidity_pct for observation in observations),
        relative_pressure_mean_hpa=_mean(observation.relative_pressure_hpa for observation in observations),
        wind_gust_max_ms=_max(observation.wind_gust_ms for observation in observations),
        solar_radiation_max_wm2=_max(observation.solar_radiation_wm2 for observation in observations),
        uv_index_max=_max(observation.uv_index for observation in observations),
        rain_day_max_mm=_max(observation.rain_day_mm for observation in observations),
        rain_event_max_mm=_max(observation.rain_event_mm for observation in observations),
        rain_last_24h_max_mm=_max(observation.rain_last_24h_mm for observation in observations),
    )


def _values(values: Iterable[float | None]) -> list[float]:
    return [value for value in values if value is not None]


def _mean(values: Iterable[float | None]) -> float | None:
    filtered = _values(values)
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def _min(values: Iterable[float | None]) -> float | None:
    filtered = _values(values)
    if not filtered:
        return None
    return min(filtered)


def _max(values: Iterable[float | None]) -> float | None:
    filtered = _values(values)
    if not filtered:
        return None
    return max(filtered)
