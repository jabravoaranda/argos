from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import math
from collections.abc import Sequence
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.config.settings import Settings, get_settings
from argos.domain.analytics import ANALYTICS_VARIABLES, ANALYTICS_VARIABLE_BY_ID, AnalyticsVariable
from argos.models.aemet import WeatherDailyObservation
from argos.models.argos_node import ArgosNodeFlowmeterMinute
from argos.models.ecowitt import WeatherObservation
from argos.models.field_event import FieldEvent
from argos.models.satellite import SatelliteMetric, SatelliteObservation, SatelliteZone
from argos.schemas.analytics import (
    AnalyticsCorrelationMatrixRequest,
    AnalyticsCorrelationMatrixResponse,
    AnalyticsCorrelationRequest,
    AnalyticsCorrelationResponse,
    AnalyticsDistributionRequest,
    AnalyticsDistributionResponse,
    AnalyticsDistributionSummaryRead,
    AnalyticsHistogramBinRead,
    AnalyticsMatrixPointRead,
    AnalyticsPointRead,
    AnalyticsSeriesRead,
    AnalyticsSeriesRequest,
    AnalyticsSeriesResponse,
    AnalyticsTrendRequest,
    AnalyticsTrendResponse,
    AnalyticsVariableRead,
    AnalyticsAggregation,
    AnalyticsFieldEventMarkerRead,
    AnalyticsPairPointRead,
    AnalyticsTrendPointRead,
)


DEFAULT_AGGREGATION_BY_TYPE: dict[str, AnalyticsAggregation] = {
    "continuous": "mean",
    "binary": "active_fraction",
}

FREQUENCY_RULES = {
    "hourly": "h",
    "daily": "D",
    "weekly": "W-MON",
    "monthly": "MS",
}

LAG_OFFSETS = {
    "0": pd.Timedelta(0),
    "+1h": pd.Timedelta(hours=1),
    "-1h": -pd.Timedelta(hours=1),
    "+3h": pd.Timedelta(hours=3),
    "-3h": -pd.Timedelta(hours=3),
    "+6h": pd.Timedelta(hours=6),
    "-6h": -pd.Timedelta(hours=6),
    "+12h": pd.Timedelta(hours=12),
    "-12h": -pd.Timedelta(hours=12),
    "+1d": pd.Timedelta(days=1),
    "-1d": -pd.Timedelta(days=1),
    "+3d": pd.Timedelta(days=3),
    "-3d": -pd.Timedelta(days=3),
    "+7d": pd.Timedelta(days=7),
    "-7d": -pd.Timedelta(days=7),
}


class AnalyticsError(ValueError):
    """Raised for invalid analytics requests."""


class AnalyticsService:
    def __init__(self, *, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def variables(self) -> list[AnalyticsVariableRead]:
        return [variable_read(variable) for variable in ANALYTICS_VARIABLES if variable.enabled]

    def series(self, request: AnalyticsSeriesRequest) -> AnalyticsSeriesResponse:
        warnings: list[str] = []
        series = [
            self._series_for_variable(
                variable=variable_or_raise(variable_id),
                request=request,
                aggregation=request.aggregations.get(variable_id) or request.aggregation,
            )
            for variable_id in request.variable_ids
        ]
        for item in series:
            warnings.extend(item.warnings)
        return AnalyticsSeriesResponse(generated_at=datetime.now(UTC), series=series, warnings=warnings)

    def correlation(self, request: AnalyticsCorrelationRequest) -> AnalyticsCorrelationResponse:
        variable_x = variable_or_raise(request.variable_x)
        variable_y = variable_or_raise(request.variable_y)
        series_request = AnalyticsSeriesRequest(
            variable_ids=[request.variable_x, request.variable_y],
            start=request.start,
            end=request.end,
            frequency=request.frequency,
            aggregations={
                request.variable_x: self._aggregation_for(variable_x, request.aggregation_x),
                request.variable_y: self._aggregation_for(variable_y, request.aggregation_y),
            },
            zone_slug=request.zone_slug,
            quality_status=request.quality_status,
        )
        response = self.series(series_request)
        frame = aligned_frame(response.series)
        warnings = list(response.warnings)
        if request.lag not in LAG_OFFSETS:
            raise AnalyticsError(f"Unsupported lag {request.lag!r}.")
        if request.lag != "0" and request.variable_y in frame:
            frame[request.variable_y] = frame[request.variable_y].shift(freq=LAG_OFFSETS[request.lag])
        frame = apply_season_filter(frame, request.season)
        frame = apply_hour_filter(frame, request.hour_start, request.hour_end)
        frame = apply_missing_policy(frame, request.missing, [variable_x, variable_y], warnings)
        pair_frame = frame[[request.variable_x, request.variable_y]].dropna()
        points = [
            AnalyticsPairPointRead(
                timestamp_utc=pd.Timestamp(cast(Any, timestamp)).to_pydatetime(),
                timestamp_local=local_timestamp(pd.Timestamp(cast(Any, timestamp)), self.settings),
                x=float(row[request.variable_x]),
                y=float(row[request.variable_y]),
            )
            for timestamp, row in pair_frame.iterrows()
        ]
        correlation = series_correlation(
            pair_frame[request.variable_x],
            pair_frame[request.variable_y],
            method=request.method,
        )
        slope, intercept, r_squared = linear_fit(pair_frame[request.variable_x], pair_frame[request.variable_y])
        if len(pair_frame) < 10:
            warnings.append("Menos de 10 pares validos; no interprete la correlacion como robusta.")
        return AnalyticsCorrelationResponse(
            variable_x=variable_read(variable_x),
            variable_y=variable_read(variable_y),
            method=request.method,
            lag=request.lag,
            pairs_count=len(pair_frame),
            correlation=correlation,
            slope=slope,
            intercept=intercept,
            r_squared=r_squared,
            warnings=warnings,
            points=points,
        )

    def correlation_matrix(self, request: AnalyticsCorrelationMatrixRequest) -> AnalyticsCorrelationMatrixResponse:
        response = self.series(request)
        frame = aligned_frame(response.series).dropna(how="all")
        variables = [variable_or_raise(variable_id) for variable_id in request.variable_ids if variable_id in frame]
        variable_ids = [variable.variable_id for variable in variables]
        matrix_frame = correlation_matrix(frame[variable_ids], request.method) if variable_ids else pd.DataFrame()
        pair_counts = frame[variable_ids].notna().astype(int).T.dot(frame[variable_ids].notna().astype(int)) if variable_ids else pd.DataFrame()
        point_frame = frame[variable_ids] if variable_ids else pd.DataFrame()
        points = [
            AnalyticsMatrixPointRead(
                timestamp_utc=pd.Timestamp(cast(Any, timestamp)).to_pydatetime(),
                timestamp_local=local_timestamp(pd.Timestamp(cast(Any, timestamp)), self.settings),
                values={variable_id: none_if_nan(row[variable_id]) for variable_id in variable_ids},
            )
            for timestamp, row in point_frame.iterrows()
        ]
        return AnalyticsCorrelationMatrixResponse(
            variables=[variable_read(variable) for variable in variables],
            method=request.method,
            matrix=[
                [none_if_nan(matrix_frame.loc[row, column]) for column in variable_ids]
                for row in variable_ids
            ],
            pair_counts=[
                [int(cast(Any, pair_counts.loc[row, column])) for column in variable_ids]
                for row in variable_ids
            ],
            points=points,
            warnings=response.warnings,
        )

    def distribution(self, request: AnalyticsDistributionRequest) -> AnalyticsDistributionResponse:
        variable = variable_or_raise(request.variable_id)
        series_response = self.series(
            AnalyticsSeriesRequest(
                variable_ids=[request.variable_id],
                start=request.start,
                end=request.end,
                frequency=request.frequency,
                aggregation=request.aggregation,
                zone_slug=request.zone_slug,
                quality_status=request.quality_status,
            )
        )
        series = series_response.series[0]
        values = pd.Series([point.value for point in series.points], dtype="float64").dropna()
        histogram = histogram_bins(values, request.bins, request.density)
        return AnalyticsDistributionResponse(
            variable=variable_read(variable),
            summary=distribution_summary(values, total_count=len(series.points)),
            histogram=histogram,
            values=series.points,
            warnings=series.warnings,
        )

    def trend(self, request: AnalyticsTrendRequest) -> AnalyticsTrendResponse:
        variable = variable_or_raise(request.variable_id)
        series_response = self.series(
            AnalyticsSeriesRequest(
                variable_ids=[request.variable_id],
                start=request.start,
                end=request.end,
                frequency=request.frequency,
                aggregation=request.aggregation,
                zone_slug=request.zone_slug,
                quality_status=request.quality_status,
            )
        )
        series = series_response.series[0]
        frame = pd.DataFrame(
            {"timestamp": [point.timestamp_utc for point in series.points], "value": [point.value for point in series.points]}
        ).dropna()
        warnings = list(series.warnings)
        if frame.empty:
            return AnalyticsTrendResponse(
                variable=variable_read(variable),
                reference=request.reference,
                slope_per_year=None,
                total_change=None,
                observations_count=0,
                coverage=0.0,
                anomaly_mean=None,
                anomaly_max_positive=None,
                anomaly_max_negative=None,
                warnings=["Sin datos para el periodo seleccionado."],
                points=[],
                field_events=[],
            )
        frame = frame.sort_values("timestamp").set_index(pd.to_datetime(frame["timestamp"], utc=True))
        frame.index = pd.DatetimeIndex(frame.index)
        frame["reference"] = trend_reference(frame["value"], request.reference, request.moving_window)
        frame["anomaly"] = frame["value"] - frame["reference"]
        slope, intercept, _r2 = linear_fit(time_numeric_years(frame.index), frame["value"])
        total_change = None
        if slope is not None and len(frame) >= 2:
            total_change = slope * (time_numeric_years(frame.index).iloc[-1] - time_numeric_years(frame.index).iloc[0])
        points = [
            AnalyticsTrendPointRead(
                timestamp_utc=pd.Timestamp(cast(Any, timestamp)).to_pydatetime(),
                timestamp_local=local_timestamp(pd.Timestamp(cast(Any, timestamp)), self.settings),
                value=none_if_nan(row["value"]),
                reference=none_if_nan(row["reference"]),
                anomaly=none_if_nan(row["anomaly"]),
            )
            for timestamp, row in frame.iterrows()
        ]
        return AnalyticsTrendResponse(
            variable=variable_read(variable),
            reference=request.reference,
            slope_per_year=slope,
            total_change=total_change,
            observations_count=len(frame),
            coverage=coverage(series.points),
            anomaly_mean=none_if_nan(frame["anomaly"].mean()),
            anomaly_max_positive=none_if_nan(frame["anomaly"].max()),
            anomaly_max_negative=none_if_nan(frame["anomaly"].min()),
            warnings=warnings,
            points=points,
            field_events=self._field_events(request) if request.include_field_events else [],
        )

    def _series_for_variable(
        self,
        *,
        variable: AnalyticsVariable,
        request: AnalyticsSeriesRequest,
        aggregation: str | None,
    ) -> AnalyticsSeriesRead:
        aggregation = self._aggregation_for(variable, aggregation)
        if aggregation not in variable.valid_aggregations:
            raise AnalyticsError(f"Aggregation {aggregation!r} is not valid for {variable.variable_id}.")
        raw = self._raw_frame(variable, request)
        warnings: list[str] = []
        if raw.empty:
            return AnalyticsSeriesRead(
                variable=variable_read(variable),
                requested_start=request.start,
                requested_end=request.end,
                covered_start=None,
                covered_end=None,
                frequency=request.frequency,
                aggregation=aggregation,
                zone_slug=request.zone_slug,
                quality_status=request.quality_status,
                observations_count=0,
                missing_count=0,
                warnings=["Sin datos para la variable seleccionada."],
                points=[],
            )
        aggregated = aggregate_frame(raw, request.frequency, aggregation)
        if len(aggregated) > request.max_points:
            factor = max(1, len(aggregated) // request.max_points)
            aggregated = aggregated.iloc[::factor]
            warnings.append("Serie reducida por limite de puntos.")
        points = [
            AnalyticsPointRead(
                timestamp_utc=pd.Timestamp(cast(Any, timestamp)).to_pydatetime(),
                timestamp_local=local_timestamp(pd.Timestamp(cast(Any, timestamp)), self.settings),
                variable_id=variable.variable_id,
                value=none_if_nan(row["value"]),
                quality=row.get("quality"),
                zone_slug=row.get("zone_slug"),
            )
            for timestamp, row in aggregated.iterrows()
        ]
        return AnalyticsSeriesRead(
            variable=variable_read(variable),
            requested_start=request.start,
            requested_end=request.end,
            covered_start=pd.Timestamp(raw.index.min()).to_pydatetime(),
            covered_end=pd.Timestamp(raw.index.max()).to_pydatetime(),
            frequency=request.frequency,
            aggregation=aggregation,
            zone_slug=request.zone_slug,
            quality_status=request.quality_status,
            observations_count=int(raw["value"].notna().sum()),
            missing_count=int(raw["value"].isna().sum()),
            warnings=warnings,
            points=points,
        )

    def _aggregation_for(self, variable: AnalyticsVariable, aggregation: str | None) -> AnalyticsAggregation:
        return cast(AnalyticsAggregation, aggregation or DEFAULT_AGGREGATION_BY_TYPE[variable.data_type])

    def _raw_frame(self, variable: AnalyticsVariable, request: AnalyticsSeriesRequest) -> pd.DataFrame:
        if variable.source == "ecowitt":
            return self._ecowitt_frame(variable, request)
        if variable.source == "aemet":
            return self._aemet_frame(variable, request)
        if variable.source == "satellite":
            return self._satellite_frame(variable, request)
        if variable.source == "controller":
            return self._controller_frame(variable, request)
        raise AnalyticsError(f"Unsupported analytics source {variable.source!r}.")

    def _ecowitt_frame(self, variable: AnalyticsVariable, request: AnalyticsSeriesRequest) -> pd.DataFrame:
        column = variable.database_mapping.split(".")[-1]
        statement = select(WeatherObservation.observed_at_utc, getattr(WeatherObservation, column))
        statement = filter_datetime(statement, WeatherObservation.observed_at_utc, request.start, request.end)
        rows = self.session.execute(statement).all()
        return frame_from_rows(rows, ["timestamp", "value"])

    def _aemet_frame(self, variable: AnalyticsVariable, request: AnalyticsSeriesRequest) -> pd.DataFrame:
        column = variable.database_mapping.split(".")[-1]
        statement = select(WeatherDailyObservation.observation_date, getattr(WeatherDailyObservation, column), WeatherDailyObservation.quality_flag)
        if request.start is not None:
            statement = statement.where(WeatherDailyObservation.observation_date >= request.start.date())
        if request.end is not None:
            statement = statement.where(WeatherDailyObservation.observation_date <= request.end.date())
        if request.quality_status:
            statement = statement.where(WeatherDailyObservation.quality_flag == request.quality_status)
        rows = self.session.execute(statement).all()
        return frame_from_rows([(datetime.combine(row[0], datetime.min.time(), tzinfo=UTC), row[1], row[2]) for row in rows], ["timestamp", "value", "quality"])

    def _satellite_frame(self, variable: AnalyticsVariable, request: AnalyticsSeriesRequest) -> pd.DataFrame:
        metric_code = variable.variable_id.split(".")[-1]
        if metric_code == "valid_pixel_fraction":
            statement = select(
                SatelliteObservation.acquisition_time,
                SatelliteObservation.valid_pixel_fraction,
                SatelliteObservation.quality_status,
                SatelliteZone.slug,
            ).join(SatelliteZone, SatelliteZone.id == SatelliteObservation.zone_id)
        else:
            statement = (
                select(
                    SatelliteObservation.acquisition_time,
                    SatelliteMetric.mean,
                    SatelliteObservation.quality_status,
                    SatelliteZone.slug,
                )
                .join(SatelliteMetric, SatelliteMetric.observation_id == SatelliteObservation.id)
                .join(SatelliteZone, SatelliteZone.id == SatelliteObservation.zone_id)
                .where(SatelliteMetric.metric_code == metric_code)
            )
        statement = filter_datetime(statement, SatelliteObservation.acquisition_time, request.start, request.end)
        if request.zone_slug:
            statement = statement.where(SatelliteZone.slug == request.zone_slug)
        if request.quality_status:
            statement = statement.where(SatelliteObservation.quality_status == request.quality_status)
        return frame_from_rows(self.session.execute(statement).all(), ["timestamp", "value", "quality", "zone_slug"])

    def _controller_frame(self, variable: AnalyticsVariable, request: AnalyticsSeriesRequest) -> pd.DataFrame:
        column = variable.database_mapping.split(".")[-1]
        statement = select(ArgosNodeFlowmeterMinute.window_start_utc, getattr(ArgosNodeFlowmeterMinute, column))
        statement = filter_datetime(statement, ArgosNodeFlowmeterMinute.window_start_utc, request.start, request.end)
        return frame_from_rows(self.session.execute(statement).all(), ["timestamp", "value"])

    def _field_events(self, request: AnalyticsTrendRequest) -> list[AnalyticsFieldEventMarkerRead]:
        statement = select(FieldEvent)
        statement = filter_datetime(statement, FieldEvent.occurred_at, request.start, request.end)
        if request.zone_slug:
            statement = statement.where(FieldEvent.zone_slug == request.zone_slug)
        events = self.session.scalars(statement.order_by(FieldEvent.occurred_at)).all()
        return [
            AnalyticsFieldEventMarkerRead(
                occurred_at=event.occurred_at,
                occurred_at_local=local_timestamp(pd.Timestamp(event.occurred_at), self.settings),
                event_type=event.event_type,
                title=event.title,
                zone_slug=event.zone_slug,
                description=event.description,
            )
            for event in events
        ]


def variable_or_raise(variable_id: str) -> AnalyticsVariable:
    try:
        return ANALYTICS_VARIABLE_BY_ID[variable_id]
    except KeyError as exc:
        raise AnalyticsError(f"Unknown analytics variable {variable_id!r}.") from exc


def variable_read(variable: AnalyticsVariable) -> AnalyticsVariableRead:
    return AnalyticsVariableRead(**asdict(variable))


def filter_datetime(statement: Any, column: Any, start: datetime | None, end: datetime | None) -> Any:
    if start is not None:
        statement = statement.where(column >= as_utc(start))
    if end is not None:
        statement = statement.where(column <= as_utc(end))
    return statement


def frame_from_rows(rows: Sequence[Any], columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return pd.DataFrame(columns=["value"], index=pd.DatetimeIndex([], tz=UTC))
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").set_index("timestamp")
    if "value" in frame:
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame


def aggregate_frame(frame: pd.DataFrame, frequency: str, aggregation: str) -> pd.DataFrame:
    if frequency == "original":
        result = frame.copy()
    else:
        resampler = frame.resample(FREQUENCY_RULES[frequency])
        if aggregation == "mean":
            result = resampler.mean(numeric_only=True)
        elif aggregation == "median":
            result = resampler.median(numeric_only=True)
        elif aggregation == "min":
            result = resampler.min(numeric_only=True)
        elif aggregation == "max":
            result = resampler.max(numeric_only=True)
        elif aggregation == "sum":
            result = resampler.sum(numeric_only=True)
        elif aggregation == "std":
            result = resampler.std(numeric_only=True)
        elif aggregation == "last":
            result = resampler.last(numeric_only=False)
        elif aggregation == "active_fraction":
            result = resampler.mean(numeric_only=True)
        elif aggregation.startswith("p"):
            percentile = int(aggregation[1:]) / 100.0
            result = resampler.quantile(percentile)
        else:
            raise AnalyticsError(f"Unsupported aggregation {aggregation!r}.")
        for column in ("quality", "zone_slug"):
            if column in frame and column not in result:
                result[column] = resampler[column].last()
    if "value" not in result:
        result["value"] = pd.NA
    return result[["value", *[column for column in ("quality", "zone_slug") if column in result]]]


def aligned_frame(series: list[AnalyticsSeriesRead]) -> pd.DataFrame:
    frames = []
    for item in series:
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": [point.timestamp_utc for point in item.points],
                    item.variable.variable_id: [point.value for point in item.points],
                }
            ).set_index(pd.to_datetime([point.timestamp_utc for point in item.points], utc=True))
        )
    if not frames:
        return pd.DataFrame()
    return pd.concat([frame[[column for column in frame.columns if column != "timestamp"]] for frame in frames], axis=1)


def apply_missing_policy(frame: pd.DataFrame, policy: str, variables: list[AnalyticsVariable], warnings: list[str]) -> pd.DataFrame:
    if policy == "intersection":
        return frame
    if policy == "linear_interpolation":
        if any(variable.data_type != "continuous" for variable in variables):
            raise AnalyticsError("Linear interpolation is only valid for continuous variables.")
        warnings.append("Interpolacion lineal aplicada.")
        return frame.interpolate(method="time")
    if policy == "forward_fill":
        if any(variable.data_type == "continuous" for variable in variables):
            raise AnalyticsError("Forward fill is not valid for these continuous variables.")
        warnings.append("Relleno hacia delante aplicado.")
        return frame.ffill()
    raise AnalyticsError(f"Unsupported missing policy {policy!r}.")


def apply_season_filter(frame: pd.DataFrame, season: str) -> pd.DataFrame:
    if season == "all" or frame.empty:
        return frame
    months_by_season = {
        "winter": {12, 1, 2},
        "spring": {3, 4, 5},
        "summer": {6, 7, 8},
        "autumn": {9, 10, 11},
    }
    index = pd.DatetimeIndex(frame.index)
    return frame[index.month.isin(months_by_season[season])]


def apply_hour_filter(frame: pd.DataFrame, start: int | None, end: int | None) -> pd.DataFrame:
    if start is None or end is None or frame.empty:
        return frame
    index = pd.DatetimeIndex(frame.index)
    if start <= end:
        return frame[(index.hour >= start) & (index.hour <= end)]
    return frame[(index.hour >= start) | (index.hour <= end)]


def linear_fit(x_values: Any, y_values: Any) -> tuple[float | None, float | None, float | None]:
    frame = pd.DataFrame({"x": x_values, "y": y_values}).dropna()
    if len(frame) < 2 or frame["x"].nunique() < 2:
        return None, None, None
    x = frame["x"].astype(float)
    y = frame["y"].astype(float)
    slope = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
    intercept = float(y.mean() - slope * x.mean())
    predictions = intercept + slope * x
    ss_res = float(((y - predictions) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r_squared = None if ss_tot == 0 else 1 - ss_res / ss_tot
    return slope, intercept, r_squared


def series_correlation(x_values: pd.Series, y_values: pd.Series, *, method: str) -> float | None:
    frame = pd.DataFrame({"x": x_values, "y": y_values}).dropna()
    if len(frame) < 2:
        return None
    if method == "spearman":
        frame = frame.rank()
    value = frame["x"].corr(frame["y"], method="pearson")
    return none_if_nan(value)


def correlation_matrix(frame: pd.DataFrame, method: str) -> pd.DataFrame:
    if method == "spearman":
        return frame.rank().corr(method="pearson", min_periods=2)
    return frame.corr(method="pearson", min_periods=2)


def histogram_bins(values: pd.Series, bins: int | str, density: bool) -> list[AnalyticsHistogramBinRead]:
    if values.empty:
        return []
    finite_values = values[values.map(math.isfinite)]
    if finite_values.empty:
        return []
    counts, edges = np.histogram(cast(Any, finite_values.to_numpy(dtype=float)), bins=cast(Any, bins), density=density)  # type: ignore[call-overload]
    return [
        AnalyticsHistogramBinRead(left=float(edges[index]), right=float(edges[index + 1]), count=none_if_nan(count) or 0.0)
        for index, count in enumerate(counts)
    ]


def distribution_summary(values: pd.Series, *, total_count: int) -> AnalyticsDistributionSummaryRead:
    if values.empty:
        return AnalyticsDistributionSummaryRead(
            count=0,
            coverage=0.0,
            mean=None,
            median=None,
            minimum=None,
            maximum=None,
            std=None,
            p05=None,
            p25=None,
            p75=None,
            p95=None,
            missing_percent=100.0 if total_count else 0.0,
        )
    return AnalyticsDistributionSummaryRead(
        count=int(values.count()),
        coverage=float(values.count() / total_count) if total_count else 0.0,
        mean=none_if_nan(values.mean()),
        median=none_if_nan(values.median()),
        minimum=none_if_nan(values.min()),
        maximum=none_if_nan(values.max()),
        std=none_if_nan(values.std()),
        p05=none_if_nan(values.quantile(0.05)),
        p25=none_if_nan(values.quantile(0.25)),
        p75=none_if_nan(values.quantile(0.75)),
        p95=none_if_nan(values.quantile(0.95)),
        missing_percent=float((total_count - values.count()) / total_count * 100.0) if total_count else 0.0,
    )


def trend_reference(values: pd.Series, reference: str, moving_window: int) -> pd.Series:
    if reference == "none":
        return pd.Series(index=values.index, data=pd.NA, dtype="float64")
    if reference == "period_mean":
        return pd.Series(index=values.index, data=values.mean(), dtype="float64")
    if reference == "period_median":
        return pd.Series(index=values.index, data=values.median(), dtype="float64")
    if reference == "moving_average":
        return values.rolling(moving_window, min_periods=1).mean()
    if reference == "linear_trend":
        x = time_numeric_years(pd.DatetimeIndex(values.index))
        slope, intercept, _r2 = linear_fit(x, values)
        if slope is None or intercept is None:
            return pd.Series(index=values.index, data=pd.NA, dtype="float64")
        return pd.Series(index=values.index, data=intercept + slope * x)
    raise AnalyticsError(f"Unsupported trend reference {reference!r}.")


def time_numeric_years(index: pd.DatetimeIndex) -> pd.Series:
    if len(index) == 0:
        return pd.Series(dtype="float64")
    start = index[0]
    return pd.Series([(timestamp - start).total_seconds() / (365.25 * 24 * 3600) for timestamp in index], index=index)


def coverage(points: list[Any]) -> float:
    if not points:
        return 0.0
    valid = sum(1 for point in points if point.value is not None)
    return valid / len(points)


def local_timestamp(timestamp: pd.Timestamp, settings: Settings) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    return timestamp.tz_convert(ZoneInfo(settings.local_timezone)).isoformat()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def none_if_nan(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result
