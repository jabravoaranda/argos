from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from argos.database.session import get_db_session
from argos.schemas.analytics import (
    AnalyticsCorrelationMatrixRequest,
    AnalyticsCorrelationMatrixResponse,
    AnalyticsCorrelationRequest,
    AnalyticsCorrelationResponse,
    AnalyticsDistributionRequest,
    AnalyticsDistributionResponse,
    AnalyticsSeriesRequest,
    AnalyticsSeriesResponse,
    AnalyticsTrendRequest,
    AnalyticsTrendResponse,
    AnalyticsVariableRead,
)
from argos.services.analytics import AnalyticsError, AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/variables", response_model=list[AnalyticsVariableRead])
def analytics_variables(session: Session = Depends(get_db_session)) -> list[AnalyticsVariableRead]:
    return AnalyticsService(session=session).variables()


@router.post("/series", response_model=AnalyticsSeriesResponse)
def analytics_series(
    payload: AnalyticsSeriesRequest,
    session: Session = Depends(get_db_session),
) -> AnalyticsSeriesResponse:
    return run_analytics(lambda service: service.series(payload), session=session)


@router.post("/correlation", response_model=AnalyticsCorrelationResponse)
def analytics_correlation(
    payload: AnalyticsCorrelationRequest,
    session: Session = Depends(get_db_session),
) -> AnalyticsCorrelationResponse:
    return run_analytics(lambda service: service.correlation(payload), session=session)


@router.post("/correlation-matrix", response_model=AnalyticsCorrelationMatrixResponse)
def analytics_correlation_matrix(
    payload: AnalyticsCorrelationMatrixRequest,
    session: Session = Depends(get_db_session),
) -> AnalyticsCorrelationMatrixResponse:
    return run_analytics(lambda service: service.correlation_matrix(payload), session=session)


@router.post("/distribution", response_model=AnalyticsDistributionResponse)
def analytics_distribution(
    payload: AnalyticsDistributionRequest,
    session: Session = Depends(get_db_session),
) -> AnalyticsDistributionResponse:
    return run_analytics(lambda service: service.distribution(payload), session=session)


@router.post("/trend", response_model=AnalyticsTrendResponse)
def analytics_trend(
    payload: AnalyticsTrendRequest,
    session: Session = Depends(get_db_session),
) -> AnalyticsTrendResponse:
    return run_analytics(lambda service: service.trend(payload), session=session)


def run_analytics(function, *, session: Session):
    try:
        return function(AnalyticsService(session=session))
    except AnalyticsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
