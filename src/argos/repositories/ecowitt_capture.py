from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.models.ecowitt import EcowittRawReport, Gateway, IngestionEvent, Station, UnknownField, WeatherObservation


class EcowittCaptureRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_raw_report_by_hash(self, payload_hash: str) -> EcowittRawReport | None:
        return self.session.scalar(select(EcowittRawReport).where(EcowittRawReport.payload_hash == payload_hash))

    def get_or_create_station(self, *, slug: str) -> Station:
        station = self.session.scalar(select(Station).where(Station.slug == slug))
        if station is None:
            station = Station(
                uuid=str(uuid4()),
                slug=slug,
                code=slug,
                name=slug.title(),
                metadata_json={"identity_scope": "physical_site"},
            )
            self.session.add(station)
            self.session.flush()
        return station

    def create_raw_report(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        received_at_utc: datetime,
        device_timestamp_utc: datetime | None,
        http_method: str,
        source_ip: str | None,
        content_type: str | None,
        payload_json: dict[str, Any],
        raw_body_text: str | None,
        payload_hash: str,
        headers_json: dict[str, Any] | None,
        query_string: str | None,
        parser_version: str | None,
        ingestion_run_id: int | None = None,
    ) -> EcowittRawReport:
        raw_report = EcowittRawReport(
            station_uuid=station_uuid,
            gateway_id=gateway_id,
            received_at_utc=received_at_utc,
            device_timestamp_utc=device_timestamp_utc,
            http_method=http_method,
            source_ip=source_ip,
            content_type=content_type,
            payload_json=payload_json,
            raw_body_text=raw_body_text,
            payload_hash=payload_hash,
            headers_json=headers_json,
            query_string=query_string,
            parser_version=parser_version,
            ingestion_run_id=ingestion_run_id,
        )
        self.session.add(raw_report)
        self.session.flush()
        return raw_report

    def get_or_create_gateway(
        self,
        *,
        station_uuid: str | None,
        identifier: str,
        station_type: str | None,
        seen_at: datetime,
        metadata_json: dict[str, Any],
    ) -> Gateway:
        gateway = self.session.scalar(select(Gateway).where(Gateway.mac_address == identifier))
        if gateway is None:
            gateway = Gateway(
                station_uuid=station_uuid,
                uuid=identifier,
                mac_address=identifier,
                station_type=station_type,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                metadata_json=metadata_json,
            )
            self.session.add(gateway)
            self.session.flush()
            return gateway

        gateway.station_uuid = station_uuid or gateway.station_uuid
        gateway.station_type = station_type or gateway.station_type
        gateway.last_seen_at = seen_at
        gateway.metadata_json = metadata_json
        return gateway

    def create_weather_observation(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        raw_report_id: int | None,
        cloud_raw_report_id: int | None = None,
        source: str = "DIRECT",
        observed_at_utc: datetime,
        received_at_utc: datetime,
        values: dict[str, float | None],
        ingestion_run_id: int | None = None,
    ) -> WeatherObservation:
        observation = WeatherObservation(
            station_uuid=station_uuid,
            gateway_id=gateway_id,
            raw_report_id=raw_report_id,
            cloud_raw_report_id=cloud_raw_report_id,
            source=source,
            observed_at_utc=observed_at_utc,
            received_at_utc=received_at_utc,
            ingestion_run_id=ingestion_run_id,
            **values,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def upsert_unknown_fields(self, unknown_fields: dict[str, Any], seen_at: datetime) -> None:
        for field_name, sample_value in unknown_fields.items():
            unknown_field = self.session.scalar(select(UnknownField).where(UnknownField.field_name == field_name))
            if unknown_field is None:
                self.session.add(
                    UnknownField(
                        field_name=field_name,
                        sample_value=str(sample_value),
                        occurrence_count=1,
                        first_seen_at=seen_at,
                        last_seen_at=seen_at,
                    )
                )
                continue

            unknown_field.occurrence_count += 1
            unknown_field.last_seen_at = seen_at

    def create_event(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        raw_report_id: int | None,
        event_type: str,
        severity: str,
        message: str,
    ) -> None:
        self.session.add(
            IngestionEvent(
                gateway_id=gateway_id,
                station_uuid=station_uuid,
                raw_report_id=raw_report_id,
                event_type=event_type,
                severity=severity,
                message=message,
            )
        )
