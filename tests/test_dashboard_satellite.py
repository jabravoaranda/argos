from __future__ import annotations

from argos.dashboard.app import satellite_frame_from_rows


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
