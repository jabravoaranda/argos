from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from argos.domain.analytics import ANALYTICS_VARIABLE_BY_ID

AnalyticsFrequency = Literal["original", "hourly", "daily", "weekly", "monthly"]
AnalyticsAggregation = Literal[
    "mean",
    "median",
    "min",
    "max",
    "sum",
    "std",
    "p05",
    "p25",
    "p75",
    "p95",
    "last",
    "active_fraction",
]


class AnalyticsVariableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variable_id: str
    source: str
    label: str
    unit: str
    description: str
    data_type: str
    temporal_resolution: str
    aggregation_supported: bool
    valid_aggregations: tuple[str, ...]
    database_mapping: str
    zone_dimension: str | None
    quality_field: str | None
    enabled: bool


class AnalyticsSeriesRequest(BaseModel):
    variable_ids: list[str] = Field(min_length=1, max_length=12)
    start: datetime | None = None
    end: datetime | None = None
    frequency: AnalyticsFrequency = "daily"
    aggregation: AnalyticsAggregation | None = None
    aggregations: dict[str, AnalyticsAggregation] = Field(default_factory=dict)
    zone_slug: str | None = None
    quality_status: str | None = None
    max_points: int = Field(default=5000, ge=100, le=20000)

    @field_validator("variable_ids")
    @classmethod
    def validate_variables(cls, values: list[str]) -> list[str]:
        for value in values:
            if value not in ANALYTICS_VARIABLE_BY_ID:
                raise ValueError(f"Unknown analytics variable {value!r}.")
        return values


class AnalyticsPointRead(BaseModel):
    timestamp_utc: datetime
    timestamp_local: str
    variable_id: str
    value: float | None
    quality: str | None = None
    zone_slug: str | None = None


class AnalyticsSeriesRead(BaseModel):
    variable: AnalyticsVariableRead
    requested_start: datetime | None
    requested_end: datetime | None
    covered_start: datetime | None
    covered_end: datetime | None
    frequency: str
    aggregation: str
    zone_slug: str | None
    quality_status: str | None
    observations_count: int
    missing_count: int
    warnings: list[str]
    points: list[AnalyticsPointRead]


class AnalyticsSeriesResponse(BaseModel):
    generated_at: datetime
    series: list[AnalyticsSeriesRead]
    warnings: list[str]


class AnalyticsCorrelationRequest(BaseModel):
    variable_x: str
    variable_y: str
    start: datetime | None = None
    end: datetime | None = None
    frequency: AnalyticsFrequency = "daily"
    aggregation_x: AnalyticsAggregation | None = None
    aggregation_y: AnalyticsAggregation | None = None
    lag: str = "0"
    method: Literal["pearson", "spearman"] = "pearson"
    missing: Literal["intersection", "linear_interpolation", "forward_fill"] = "intersection"
    zone_slug: str | None = None
    quality_status: str | None = None
    season: Literal["all", "winter", "spring", "summer", "autumn"] = "all"
    hour_start: int | None = Field(default=None, ge=0, le=23)
    hour_end: int | None = Field(default=None, ge=0, le=23)

    @field_validator("variable_x", "variable_y")
    @classmethod
    def validate_variable(cls, value: str) -> str:
        if value not in ANALYTICS_VARIABLE_BY_ID:
            raise ValueError(f"Unknown analytics variable {value!r}.")
        return value


class AnalyticsPairPointRead(BaseModel):
    timestamp_utc: datetime
    timestamp_local: str
    x: float
    y: float


class AnalyticsCorrelationResponse(BaseModel):
    variable_x: AnalyticsVariableRead
    variable_y: AnalyticsVariableRead
    method: str
    lag: str
    pairs_count: int
    correlation: float | None
    slope: float | None
    intercept: float | None
    r_squared: float | None
    p_value: float | None = None
    warnings: list[str]
    points: list[AnalyticsPairPointRead]


class AnalyticsCorrelationMatrixRequest(AnalyticsSeriesRequest):
    method: Literal["pearson", "spearman"] = "pearson"


class AnalyticsCorrelationMatrixResponse(BaseModel):
    variables: list[AnalyticsVariableRead]
    method: str
    matrix: list[list[float | None]]
    pair_counts: list[list[int]]
    warnings: list[str]


class AnalyticsDistributionRequest(BaseModel):
    variable_id: str
    start: datetime | None = None
    end: datetime | None = None
    frequency: AnalyticsFrequency = "daily"
    aggregation: AnalyticsAggregation | None = None
    zone_slug: str | None = None
    quality_status: str | None = None
    bins: int | Literal["auto"] = "auto"
    density: bool = False
    compare: AnalyticsSeriesRequest | None = None

    @field_validator("variable_id")
    @classmethod
    def validate_variable(cls, value: str) -> str:
        if value not in ANALYTICS_VARIABLE_BY_ID:
            raise ValueError(f"Unknown analytics variable {value!r}.")
        return value


class AnalyticsDistributionSummaryRead(BaseModel):
    count: int
    coverage: float
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    std: float | None
    p05: float | None
    p25: float | None
    p75: float | None
    p95: float | None
    missing_percent: float


class AnalyticsHistogramBinRead(BaseModel):
    left: float
    right: float
    count: float


class AnalyticsDistributionResponse(BaseModel):
    variable: AnalyticsVariableRead
    summary: AnalyticsDistributionSummaryRead
    histogram: list[AnalyticsHistogramBinRead]
    values: list[AnalyticsPointRead]
    comparison: "AnalyticsDistributionResponse | None" = None
    warnings: list[str]


class AnalyticsTrendRequest(BaseModel):
    variable_id: str
    start: datetime | None = None
    end: datetime | None = None
    frequency: AnalyticsFrequency = "daily"
    aggregation: AnalyticsAggregation | None = None
    zone_slug: str | None = None
    quality_status: str | None = None
    reference: Literal["none", "period_mean", "period_median", "moving_average", "linear_trend"] = "period_mean"
    moving_window: int = Field(default=7, ge=2, le=365)
    anomaly: Literal["absolute"] = "absolute"
    include_field_events: bool = False

    @field_validator("variable_id")
    @classmethod
    def validate_variable(cls, value: str) -> str:
        if value not in ANALYTICS_VARIABLE_BY_ID:
            raise ValueError(f"Unknown analytics variable {value!r}.")
        return value


class AnalyticsTrendPointRead(BaseModel):
    timestamp_utc: datetime
    timestamp_local: str
    value: float | None
    reference: float | None
    anomaly: float | None


class AnalyticsFieldEventMarkerRead(BaseModel):
    occurred_at: datetime
    occurred_at_local: str
    event_type: str
    title: str
    zone_slug: str | None
    description: str | None


class AnalyticsTrendResponse(BaseModel):
    variable: AnalyticsVariableRead
    reference: str
    slope_per_year: float | None
    total_change: float | None
    observations_count: int
    coverage: float
    anomaly_mean: float | None
    anomaly_max_positive: float | None
    anomaly_max_negative: float | None
    warnings: list[str]
    points: list[AnalyticsTrendPointRead]
    field_events: list[AnalyticsFieldEventMarkerRead]
