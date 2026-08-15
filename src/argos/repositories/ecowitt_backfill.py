from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.models.ecowitt import EcowittCloudRawReport, Gateway, GatewayAlias, IngestionEvent, Station, WeatherObservation


class EcowittBackfillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_gateway(
        self,
        *,
        station_uuid: str | None,
        identifier: str,
        station_type: str | None,
        metadata_json: dict[str, Any],
        aliases: dict[str, str] | None = None,
    ) -> Gateway:
        gateway = self.resolve_gateway(identifier=identifier, aliases=aliases or {})
        if gateway is None:
            gateway = Gateway(
                station_uuid=station_uuid,
                uuid=identifier,
                mac_address=identifier,
                station_type=station_type,
                metadata_json=metadata_json,
            )
            self.session.add(gateway)
            self.session.flush()
            self.upsert_gateway_aliases(gateway_id=gateway.id, aliases=aliases or {})
            return gateway

        gateway.station_uuid = station_uuid or gateway.station_uuid
        gateway.station_type = station_type or gateway.station_type
        gateway.metadata_json = {**(gateway.metadata_json or {}), **metadata_json}
        self.upsert_gateway_aliases(gateway_id=gateway.id, aliases=aliases or {})
        return gateway

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

    def resolve_gateway(self, *, identifier: str, aliases: dict[str, str]) -> Gateway | None:
        gateway = self.session.scalar(select(Gateway).where(Gateway.mac_address == identifier))
        if gateway is not None:
            return gateway

        for alias_type, alias_value in aliases.items():
            alias = self.session.scalar(
                select(GatewayAlias).where(
                    GatewayAlias.alias_type == alias_type,
                    GatewayAlias.alias_value == normalize_gateway_alias(alias_value),
                )
            )
            if alias is not None:
                return alias.gateway
        return None

    def upsert_gateway_aliases(self, *, gateway_id: int, aliases: dict[str, str]) -> None:
        for alias_type, alias_value in aliases.items():
            normalized_value = normalize_gateway_alias(alias_value)
            if not normalized_value:
                continue
            alias = self.session.scalar(
                select(GatewayAlias).where(
                    GatewayAlias.alias_type == alias_type,
                    GatewayAlias.alias_value == normalized_value,
                )
            )
            if alias is None:
                self.session.add(
                    GatewayAlias(
                        gateway_id=gateway_id,
                        alias_type=alias_type,
                        alias_value=normalized_value,
                    )
                )

    def get_cloud_raw_report_by_hash(self, payload_hash: str) -> EcowittCloudRawReport | None:
        return self.session.scalar(
            select(EcowittCloudRawReport).where(EcowittCloudRawReport.payload_hash == payload_hash)
        )

    def create_cloud_raw_report(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        requested_start_utc: datetime | None,
        requested_end_utc: datetime | None,
        observed_at_utc: datetime,
        payload_json: dict[str, Any],
        payload_hash: str,
        api_version: str | None,
        parser_version: str | None,
        ingestion_run_id: int | None = None,
    ) -> EcowittCloudRawReport:
        raw_report = EcowittCloudRawReport(
            station_uuid=station_uuid,
            gateway_id=gateway_id,
            requested_start_utc=requested_start_utc,
            requested_end_utc=requested_end_utc,
            observed_at_utc=observed_at_utc,
            payload_json=payload_json,
            payload_hash=payload_hash,
            api_version=api_version,
            parser_version=parser_version,
            ingestion_run_id=ingestion_run_id,
        )
        self.session.add(raw_report)
        self.session.flush()
        return raw_report

    def get_observation_by_gateway_and_observed_at(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        observed_at_utc: datetime,
    ) -> WeatherObservation | None:
        observed_candidates = {observed_at_utc}
        if observed_at_utc.tzinfo is not None:
            observed_candidates.add(observed_at_utc.replace(tzinfo=None))
        return self.session.scalar(
            select(WeatherObservation).where(
                WeatherObservation.station_uuid == station_uuid,
                WeatherObservation.observed_at_utc.in_(observed_candidates),
            )
        )

    def create_backfilled_observation(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        cloud_raw_report_id: int,
        observed_at_utc: datetime,
        received_at_utc: datetime,
        values: dict[str, float | None],
        ingestion_run_id: int | None = None,
    ) -> WeatherObservation:
        observation = WeatherObservation(
            station_uuid=station_uuid,
            gateway_id=gateway_id,
            raw_report_id=None,
            cloud_raw_report_id=cloud_raw_report_id,
            source="BACKFILLED",
            observed_at_utc=observed_at_utc,
            received_at_utc=received_at_utc,
            ingestion_run_id=ingestion_run_id,
            **values,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def fill_missing_observation_values(
        self,
        observation: WeatherObservation,
        *,
        values: dict[str, float | None],
    ) -> None:
        for field_name, value in values.items():
            if value is not None and getattr(observation, field_name) is None:
                setattr(observation, field_name, value)
        self.session.flush()

    def create_event(
        self,
        *,
        station_uuid: str | None,
        gateway_id: int | None,
        event_type: str,
        severity: str,
        message: str,
    ) -> None:
        self.session.add(
            IngestionEvent(
                station_uuid=station_uuid,
                gateway_id=gateway_id,
                raw_report_id=None,
                event_type=event_type,
                severity=severity,
                message=message,
            )
        )


def normalize_gateway_alias(value: str) -> str:
    return value.strip().upper().replace(":", "").replace("-", "")
