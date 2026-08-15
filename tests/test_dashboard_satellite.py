from __future__ import annotations

from argos.dashboard import app as dashboard_app
from argos.dashboard.app import render_satellite_charts, satellite_acquisition_count, satellite_frame_from_rows


def test_satellite_frame_accepts_mixed_iso8601_precision() -> None:
    frame = satellite_frame_from_rows(
        [
            {"acquisition_time": "2022-05-26T11:21:12", "metric_code": "ndvi", "mean": 0.4},
            {"acquisition_time": "2026-07-26T11:21:22.251000", "metric_code": "savi", "mean": 0.3},
        ]
    )

    assert str(frame.loc[0, "acquisition_time"]) == "2022-05-26 11:21:12"
    assert str(frame.loc[1, "acquisition_time"]) == "2026-07-26 11:21:22.251000"
    assert frame["metric"].tolist() == ["NDVI", "SAVI"]


def test_satellite_acquisition_count_distinguishes_aois() -> None:
    frame = satellite_frame_from_rows(
        [
            {
                "acquisition_time": "2026-01-01T00:00:00",
                "aoi_slug": "olivos_pequenos",
                "metric_code": "ndvi",
                "mean": 0.4,
            },
            {
                "acquisition_time": "2026-01-01T00:00:00",
                "aoi_slug": "olivos_grandes",
                "metric_code": "ndvi",
                "mean": 0.5,
            },
        ]
    )

    assert satellite_acquisition_count(frame) == 2


def test_satellite_chart_separates_all_aoi_series(monkeypatch) -> None:
    figures = []
    frame = satellite_frame_from_rows(
        [
            {
                "acquisition_time": "2026-01-01T00:00:00",
                "aoi_slug": "olivos_pequenos",
                "zone_name": "Olivos pequeños",
                "metric_code": "ndvi",
                "mean": 0.4,
            },
            {
                "acquisition_time": "2026-01-01T00:00:00",
                "aoi_slug": "olivos_grandes",
                "zone_name": "Olivos grandes",
                "metric_code": "ndvi",
                "mean": 0.5,
            },
        ]
    )

    monkeypatch.setattr(dashboard_app.st, "plotly_chart", lambda figure, **_: figures.append(figure))

    render_satellite_charts(frame, ["ndvi"])

    assert figures
    assert {trace.name for trace in figures[0].data} == {"Olivos pequeños · NDVI", "Olivos grandes · NDVI"}
