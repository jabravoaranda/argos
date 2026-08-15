from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from argos.models.argos_node import ArgosNodeFlowmeterMinute, ArgosNodeFlowmeterResetEvent, ArgosNodeFlowmeterSession


class ArgosNodeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def flowmeter_minute_by_window(
        self,
        *,
        node_url: str,
        window_start_utc: datetime,
    ) -> ArgosNodeFlowmeterMinute | None:
        return self.session.scalar(
            select(ArgosNodeFlowmeterMinute).where(
                ArgosNodeFlowmeterMinute.node_url == node_url,
                ArgosNodeFlowmeterMinute.window_start_utc == window_start_utc,
            )
        )

    def upsert_flowmeter_minute(
        self,
        *,
        node_url: str,
        window_start_utc: datetime,
        window_end_utc: datetime,
        pulse_count_start: int,
        pulse_count_end: int,
        pulse_delta: int,
        boot_total_l_start: float | None,
        boot_total_l_end: float | None,
        total_l_start: float | None,
        total_l_end: float | None,
        hydrological_year_l_start: float | None,
        hydrological_year_l_end: float | None,
        session_active_start: bool | None,
        session_active_end: bool | None,
        session_l_start: float | None,
        session_l_end: float | None,
        last_session_l_start: float | None,
        last_session_l_end: float | None,
        volume_l: float,
        avg_flow_l_min: float,
        max_flow_l_min: float,
        samples_count: int,
        relay1_state_start: bool | None,
        relay1_state_end: bool | None,
        relay1_open_samples_count: int,
        relay1_open_fraction: float | None,
        ingestion_run_id: int | None = None,
    ) -> tuple[ArgosNodeFlowmeterMinute, bool]:
        minute = self.flowmeter_minute_by_window(node_url=node_url, window_start_utc=window_start_utc)
        created = minute is None
        if minute is None:
            minute = ArgosNodeFlowmeterMinute(
                node_url=node_url,
                window_start_utc=window_start_utc,
                window_end_utc=window_end_utc,
                pulse_count_start=pulse_count_start,
                pulse_count_end=pulse_count_end,
                pulse_delta=pulse_delta,
                boot_total_l_start=boot_total_l_start,
                boot_total_l_end=boot_total_l_end,
                total_l_start=total_l_start,
                total_l_end=total_l_end,
                hydrological_year_l_start=hydrological_year_l_start,
                hydrological_year_l_end=hydrological_year_l_end,
                session_active_start=session_active_start,
                session_active_end=session_active_end,
                session_l_start=session_l_start,
                session_l_end=session_l_end,
                last_session_l_start=last_session_l_start,
                last_session_l_end=last_session_l_end,
                volume_l=volume_l,
                avg_flow_l_min=avg_flow_l_min,
                max_flow_l_min=max_flow_l_min,
                samples_count=samples_count,
                relay1_state_start=relay1_state_start,
                relay1_state_end=relay1_state_end,
                relay1_open_samples_count=relay1_open_samples_count,
                relay1_open_fraction=relay1_open_fraction,
                ingestion_run_id=ingestion_run_id,
            )
            self.session.add(minute)
        else:
            minute.window_end_utc = window_end_utc
            minute.pulse_count_start = pulse_count_start
            minute.pulse_count_end = pulse_count_end
            minute.pulse_delta = pulse_delta
            minute.boot_total_l_start = boot_total_l_start
            minute.boot_total_l_end = boot_total_l_end
            minute.total_l_start = total_l_start
            minute.total_l_end = total_l_end
            minute.hydrological_year_l_start = hydrological_year_l_start
            minute.hydrological_year_l_end = hydrological_year_l_end
            minute.session_active_start = session_active_start
            minute.session_active_end = session_active_end
            minute.session_l_start = session_l_start
            minute.session_l_end = session_l_end
            minute.last_session_l_start = last_session_l_start
            minute.last_session_l_end = last_session_l_end
            minute.volume_l = volume_l
            minute.avg_flow_l_min = avg_flow_l_min
            minute.max_flow_l_min = max_flow_l_min
            minute.samples_count = samples_count
            minute.relay1_state_start = relay1_state_start
            minute.relay1_state_end = relay1_state_end
            minute.relay1_open_samples_count = relay1_open_samples_count
            minute.relay1_open_fraction = relay1_open_fraction
            minute.ingestion_run_id = ingestion_run_id or minute.ingestion_run_id
        self.session.flush()
        return minute, created

    def create_flowmeter_session(
        self,
        *,
        node_url: str,
        closed_at_utc: datetime,
        last_session_l: float,
        pulse_count: int | None,
        total_l: float | None,
        hydrological_year_l: float | None,
    ) -> ArgosNodeFlowmeterSession:
        session = ArgosNodeFlowmeterSession(
            node_url=node_url,
            closed_at_utc=closed_at_utc,
            last_session_l=last_session_l,
            pulse_count=pulse_count,
            total_l=total_l,
            hydrological_year_l=hydrological_year_l,
        )
        self.session.add(session)
        self.session.flush()
        return session

    def flowmeter_reset_event(
        self,
        *,
        node_url: str,
        reset_type: str,
        administrative_year: int,
    ) -> ArgosNodeFlowmeterResetEvent | None:
        return self.session.scalar(
            select(ArgosNodeFlowmeterResetEvent).where(
                ArgosNodeFlowmeterResetEvent.node_url == node_url,
                ArgosNodeFlowmeterResetEvent.reset_type == reset_type,
                ArgosNodeFlowmeterResetEvent.administrative_year == administrative_year,
            )
        )

    def create_flowmeter_reset_event(
        self,
        *,
        node_url: str,
        reset_type: str,
        administrative_year: int,
        reset_at_utc: datetime,
    ) -> ArgosNodeFlowmeterResetEvent:
        event = ArgosNodeFlowmeterResetEvent(
            node_url=node_url,
            reset_type=reset_type,
            administrative_year=administrative_year,
            reset_at_utc=reset_at_utc,
        )
        self.session.add(event)
        self.session.flush()
        return event
