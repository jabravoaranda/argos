from pathlib import Path

from argos.dashboard.aggregations import annual_monthly, daily_summary, linear_trend
from argos.dashboard.data_loader import available_variables, filter_by_date_range, load_weather_data


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "weather_csv"


def test_load_weather_data_combines_daily_csv_files() -> None:
    loaded = load_weather_data(FIXTURES_DIR)

    assert len(loaded.files) == 2
    assert len(loaded.frame) == 4
    assert "presion_absoluta" in loaded.missing_columns
    assert "temperatura_exterior" in available_variables(loaded.frame)


def test_filter_and_daily_summary() -> None:
    loaded = load_weather_data(FIXTURES_DIR)
    filtered = filter_by_date_range(loaded.frame, "2026-07-09", "2026-07-09")
    summary = daily_summary(filtered)

    assert len(filtered) == 2
    assert summary[("temperatura_exterior", "mean")].iloc[0] == 21.0
    assert summary[("lluvia_diaria", "max")].iloc[0] == 0.2


def test_annual_monthly_and_linear_trend() -> None:
    loaded = load_weather_data(FIXTURES_DIR)
    monthly = annual_monthly(loaded.frame)
    trend = linear_trend(loaded.frame, "temperatura_exterior")

    assert not monthly.empty
    assert "temperatura_exterior" in monthly.columns
    assert "temperatura_exterior_tendencia" in trend.columns
