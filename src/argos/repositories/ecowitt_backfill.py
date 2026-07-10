from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.models.ecowitt import EcowittCloudRawReport, Gateway, IngestionEvent, WeatherObservation


class EcowittBackfillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_gateway(
        self,
        *,
        identifier: str,
        station_type: str | None,
        metadata_json: dict[str, Any],
    ) -> Gateway:
        gateway = self.session.scalar(select(Gateway).where(Gateway.mac_address == identifier))
        if gateway is None:
            gateway = Gateway(
                uuid=identifier,
                mac_address=identifier,
                station_type=station_type,
                metadata_json=metadata_json,
            )
            self.session.add(gateway)
            self.session.flush()
            return gateway

        gateway.station_type = station_type or gateway.station_type
        gateway.metadata_json = {**(gateway.metadata_json or {}), **metadata_json}
        return gateway

    def get_cloud_raw_report_by_hash(self, payload_hash: str) -> EcowittCloudRawReport | None:
        return self.session.scalar(
            select(EcowittCloudRawReport).where(EcowittCloudRawReport.payload_hash == payload_hash)
        )

    def create_cloud_raw_report(
        self,
        *,
        gateway_id: int | None,
        requested_start_utc: datetime | None,
        requested_end_utc: datetime | None,
        observed_at_utc: datetime,
        payload_json: dict[str, Any],
        payload_hash: str,
        api_version: str | None,
        parser_version: str | None,
    ) -> EcowittCloudRawReport:
        raw_report = EcowittCloudRawReport(
            gateway_id=gateway_id,
            requested_start_utc=requested_start_utc,
            requested_end_utc=requested_end_utc,
            observed_at_utc=observed_at_utc,
            payload_json=payload_json,
            payload_hash=payload_hash,
            api_version=api_version,
            parser_version=parser_version,
        )
        self.session.add(raw_report)
        self.session.flush()
        return raw_report

    def get_observation_by_gateway_and_observed_at(
        self,
        *,
        gateway_id: int | None,
        observed_at_utc: datetime,
    ) -> WeatherObservation | None:
        observed_candidates = {observed_at_utc}
        if observed_at_utc.tzinfo is not None:
            observed_candidates.add(observed_at_utc.replace(tzinfo=None))
        return self.session.scalar(
            select(WeatherObservation).where(
                WeatherObservation.gateway_id == gateway_id,
                WeatherObservation.observed_at_utc.in_(observed_candidates),
            )
        )

    def create_backfilled_observation(
        self,
        *,
        gateway_id: int | None,
        cloud_raw_report_id: int,
        observed_at_utc: datetime,
        received_at_utc: datetime,
        values: dict[str, float | None],
    ) -> WeatherObservation:
        observation = WeatherObservation(
            gateway_id=gateway_id,
            raw_report_id=None,
            cloud_raw_report_id=cloud_raw_report_id,
            source="BACKFILLED",
            observed_at_utc=observed_at_utc,
            received_at_utc=received_at_utc,
            **values,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def create_event(
        self,
        *,
        gateway_id: int | None,
        event_type: str,
        severity: str,
        message: str,
    ) -> None:
        self.session.add(
            IngestionEvent(
                gateway_id=gateway_id,
                raw_report_id=None,
                event_type=event_type,
                severity=severity,
                message=message,
            )
        )
