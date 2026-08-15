from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Event
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from argos.dashboard.argos_node_client import ArgosNodeClient, ArgosNodeError
from argos.models.argos_node import ArgosNodeFlowmeterMinute
from argos.repositories.argos_node import ArgosNodeRepository
from argos.services.ingestion_trace import finalize_ingestion_run, mark_run_failed, start_ingestion_run

PULSES_PER_LITER = 27.0
HYDROLOGICAL_YEAR_RESET_TYPE = "hydrological_year"
logger = logging.getLogger(__name__)


class ArgosNodeStatusError(ValueError):
    """Raised when argos-node status does not contain the expected flowmeter fields."""


@dataclass(frozen=True, slots=True)
class ParsedFlowmeterStatus:
    pulse_count: int
    flow_l_min: float
    boot_total_l: float
    total_l: float
    hydrological_year_l: float
    session_active: bool
    session_l: float
    last_session_l: float
    di1_state: bool | None
    relay1_state: bool | None


@dataclass(frozen=True, slots=True)
class FlowmeterSample:
    captured_at_utc: datetime
    pulse_count: int
    flow_l_min: float
    boot_total_l: float
    total_l: float
    hydrological_year_l: float
    session_active: bool
    session_l: float
    last_session_l: float
    di1_state: bool | None
    relay1_state: bool | None


@dataclass(frozen=True, slots=True)
class FlowmeterMinuteAggregate:
    node_url: str
    window_start_utc: datetime
    window_end_utc: datetime
    pulse_count_start: int
    pulse_count_end: int
    pulse_delta: int
    boot_total_l_start: float
    boot_total_l_end: float
    total_l_start: float
    total_l_end: float
    hydrological_year_l_start: float
    hydrological_year_l_end: float
    session_active_start: bool
    session_active_end: bool
    session_l_start: float
    session_l_end: float
    last_session_l_start: float
    last_session_l_end: float
    volume_l: float
    avg_flow_l_min: float
    max_flow_l_min: float
    samples_count: int
    relay1_state_start: bool | None
    relay1_state_end: bool | None
    relay1_open_samples_count: int
    relay1_open_fraction: float | None


@dataclass(frozen=True, slots=True)
class FlowmeterMinuteCapture:
    minute_id: int
    created: bool
    node_url: str
    window_start_utc: datetime
    samples_count: int
    pulse_delta: int
    volume_l: float


class FlowmeterMinuteAggregator:
    def __init__(self, *, node_url: str) -> None:
        self.node_url = node_url.rstrip("/")
        self._current: _WindowAccumulator | None = None

    def add_sample(self, sample: FlowmeterSample) -> FlowmeterMinuteAggregate | None:
        sample = FlowmeterSample(
            captured_at_utc=_as_utc(sample.captured_at_utc),
            pulse_count=sample.pulse_count,
            flow_l_min=sample.flow_l_min,
            boot_total_l=sample.boot_total_l,
            total_l=sample.total_l,
            hydrological_year_l=sample.hydrological_year_l,
            session_active=sample.session_active,
            session_l=sample.session_l,
            last_session_l=sample.last_session_l,
            di1_state=sample.di1_state,
            relay1_state=sample.relay1_state,
        )
        window_start = _minute_start(sample.captured_at_utc)
        if self._current is None:
            self._current = _WindowAccumulator(node_url=self.node_url, window_start_utc=window_start)
        if window_start == self._current.window_start_utc:
            self._current.add(sample)
            return None

        completed = self._current.to_aggregate()
        self._current = _WindowAccumulator(node_url=self.node_url, window_start_utc=window_start)
        self._current.add(sample)
        return completed

    def flush(self) -> FlowmeterMinuteAggregate | None:
        if self._current is None or self._current.samples_count == 0:
            return None
        completed = self._current.to_aggregate()
        self._current = None
        return completed


@dataclass(slots=True)
class _WindowAccumulator:
    node_url: str
    window_start_utc: datetime
    pulse_count_start: int | None = None
    pulse_count_end: int | None = None
    boot_total_l_start: float | None = None
    boot_total_l_end: float | None = None
    total_l_start: float | None = None
    total_l_end: float | None = None
    hydrological_year_l_start: float | None = None
    hydrological_year_l_end: float | None = None
    session_active_start: bool | None = None
    session_active_end: bool | None = None
    session_l_start: float | None = None
    session_l_end: float | None = None
    last_session_l_start: float | None = None
    last_session_l_end: float | None = None
    max_flow_l_min: float | None = None
    samples_count: int = 0
    relay1_state_start: bool | None = None
    relay1_state_end: bool | None = None
    relay1_known_samples_count: int = 0
    relay1_open_samples_count: int = 0

    def add(self, sample: FlowmeterSample) -> None:
        if self.pulse_count_start is None:
            self.pulse_count_start = sample.pulse_count
            self.boot_total_l_start = sample.boot_total_l
            self.total_l_start = sample.total_l
            self.hydrological_year_l_start = sample.hydrological_year_l
            self.session_active_start = sample.session_active
            self.session_l_start = sample.session_l
            self.last_session_l_start = sample.last_session_l
            self.relay1_state_start = sample.relay1_state
        self.pulse_count_end = sample.pulse_count
        self.boot_total_l_end = sample.boot_total_l
        self.total_l_end = sample.total_l
        self.hydrological_year_l_end = sample.hydrological_year_l
        self.session_active_end = sample.session_active
        self.session_l_end = sample.session_l
        self.last_session_l_end = sample.last_session_l
        self.relay1_state_end = sample.relay1_state
        self.max_flow_l_min = sample.flow_l_min if self.max_flow_l_min is None else max(self.max_flow_l_min, sample.flow_l_min)
        self.samples_count += 1
        if sample.relay1_state is not None:
            self.relay1_known_samples_count += 1
            if sample.relay1_state:
                self.relay1_open_samples_count += 1

    def to_aggregate(self) -> FlowmeterMinuteAggregate:
        if (
            self.pulse_count_start is None
            or self.pulse_count_end is None
            or self.boot_total_l_start is None
            or self.boot_total_l_end is None
            or self.total_l_start is None
            or self.total_l_end is None
            or self.hydrological_year_l_start is None
            or self.hydrological_year_l_end is None
            or self.session_active_start is None
            or self.session_active_end is None
            or self.session_l_start is None
            or self.session_l_end is None
            or self.last_session_l_start is None
            or self.last_session_l_end is None
            or self.max_flow_l_min is None
        ):
            raise ArgosNodeStatusError("Cannot aggregate an empty flowmeter window.")
        pulse_delta = self.pulse_count_end - self.pulse_count_start
        window_end = self.window_start_utc + timedelta(minutes=1)
        volume_l = pulse_delta / PULSES_PER_LITER
        window_duration_minutes = (window_end - self.window_start_utc).total_seconds() / 60.0
        relay1_open_fraction = (
            self.relay1_open_samples_count / self.relay1_known_samples_count if self.relay1_known_samples_count else None
        )
        return FlowmeterMinuteAggregate(
            node_url=self.node_url,
            window_start_utc=self.window_start_utc,
            window_end_utc=window_end,
            pulse_count_start=self.pulse_count_start,
            pulse_count_end=self.pulse_count_end,
            pulse_delta=pulse_delta,
            boot_total_l_start=self.boot_total_l_start,
            boot_total_l_end=self.boot_total_l_end,
            total_l_start=self.total_l_start,
            total_l_end=self.total_l_end,
            hydrological_year_l_start=self.hydrological_year_l_start,
            hydrological_year_l_end=self.hydrological_year_l_end,
            session_active_start=self.session_active_start,
            session_active_end=self.session_active_end,
            session_l_start=self.session_l_start,
            session_l_end=self.session_l_end,
            last_session_l_start=self.last_session_l_start,
            last_session_l_end=self.last_session_l_end,
            volume_l=volume_l,
            avg_flow_l_min=volume_l / window_duration_minutes,
            max_flow_l_min=self.max_flow_l_min,
            samples_count=self.samples_count,
            relay1_state_start=self.relay1_state_start,
            relay1_state_end=self.relay1_state_end,
            relay1_open_samples_count=self.relay1_open_samples_count,
            relay1_open_fraction=relay1_open_fraction,
        )


def parse_flowmeter_status(status: Mapping[str, Any]) -> ParsedFlowmeterStatus:
    flowmeter = _mapping(status.get("flowmeter"), "flowmeter")
    inputs = status.get("inputs")
    digital = _digital_inputs(inputs)
    relay1_state = _ev8_state_from_status(status)
    return ParsedFlowmeterStatus(
        pulse_count=_required_int(flowmeter.get("pulse_count"), "flowmeter.pulse_count"),
        flow_l_min=_required_float(flowmeter.get("flow_l_min"), "flowmeter.flow_l_min"),
        boot_total_l=_required_float(flowmeter.get("boot_total_l"), "flowmeter.boot_total_l"),
        total_l=_required_float(flowmeter.get("total_l"), "flowmeter.total_l"),
        hydrological_year_l=_required_float(
            flowmeter.get("hydrological_year_l"), "flowmeter.hydrological_year_l"
        ),
        session_active=_required_bool(flowmeter.get("session_active"), "flowmeter.session_active"),
        session_l=_required_float(flowmeter.get("session_l"), "flowmeter.session_l"),
        last_session_l=_required_float(flowmeter.get("last_session_l"), "flowmeter.last_session_l"),
        di1_state=_digital_input_state(digital, input_id=8),
        relay1_state=relay1_state if relay1_state is not None else _required_bool(flowmeter.get("session_active"), "flowmeter.session_active"),
    )


def sample_from_status(
    *,
    status: Mapping[str, Any],
    valve_state: Mapping[str, Any] | None = None,
    captured_at_utc: datetime | None = None,
) -> FlowmeterSample:
    parsed = parse_flowmeter_status(status)
    return FlowmeterSample(
        captured_at_utc=_as_utc(captured_at_utc or datetime.now(UTC)),
        pulse_count=parsed.pulse_count,
        flow_l_min=parsed.flow_l_min,
        boot_total_l=parsed.boot_total_l,
        total_l=parsed.total_l,
        hydrological_year_l=parsed.hydrological_year_l,
        session_active=parsed.session_active,
        session_l=parsed.session_l,
        last_session_l=parsed.last_session_l,
        di1_state=parsed.di1_state,
        relay1_state=parsed.relay1_state if parsed.relay1_state is not None else parse_relay_open_state(valve_state),
    )


def parse_relay_open_state(state: Mapping[str, Any] | None) -> bool | None:
    if state is None:
        return None
    for key in ("open", "is_open", "opened", "relay_active", "relay_on", "relay_enabled", "active", "energized"):
        value = state.get(key)
        if isinstance(value, bool):
            return value
    for key in ("state", "status", "position"):
        value = state.get(key)
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized in {"open", "opened", "true", "1", "on"}:
            return True
        if normalized in {"closed", "close", "false", "0", "off"}:
            return False
    return None


def persist_flowmeter_minute(
    *,
    session: Session,
    aggregate: FlowmeterMinuteAggregate,
    ingestion_run_id: int | None = None,
) -> FlowmeterMinuteCapture:
    repository = ArgosNodeRepository(session)
    minute, created = repository.upsert_flowmeter_minute(
        node_url=aggregate.node_url,
        window_start_utc=aggregate.window_start_utc,
        window_end_utc=aggregate.window_end_utc,
        pulse_count_start=aggregate.pulse_count_start,
        pulse_count_end=aggregate.pulse_count_end,
        pulse_delta=aggregate.pulse_delta,
        boot_total_l_start=aggregate.boot_total_l_start,
        boot_total_l_end=aggregate.boot_total_l_end,
        total_l_start=aggregate.total_l_start,
        total_l_end=aggregate.total_l_end,
        hydrological_year_l_start=aggregate.hydrological_year_l_start,
        hydrological_year_l_end=aggregate.hydrological_year_l_end,
        session_active_start=aggregate.session_active_start,
        session_active_end=aggregate.session_active_end,
        session_l_start=aggregate.session_l_start,
        session_l_end=aggregate.session_l_end,
        last_session_l_start=aggregate.last_session_l_start,
        last_session_l_end=aggregate.last_session_l_end,
        volume_l=aggregate.volume_l,
        avg_flow_l_min=aggregate.avg_flow_l_min,
        max_flow_l_min=aggregate.max_flow_l_min,
        samples_count=aggregate.samples_count,
        relay1_state_start=aggregate.relay1_state_start,
        relay1_state_end=aggregate.relay1_state_end,
        relay1_open_samples_count=aggregate.relay1_open_samples_count,
        relay1_open_fraction=aggregate.relay1_open_fraction,
        ingestion_run_id=ingestion_run_id,
    )
    session.commit()
    return _capture_from_minute(minute, created=created)


def persist_flowmeter_session_close(
    *,
    session: Session,
    node_url: str,
    sample: FlowmeterSample,
) -> int:
    repository = ArgosNodeRepository(session)
    flowmeter_session = repository.create_flowmeter_session(
        node_url=node_url.rstrip("/"),
        closed_at_utc=sample.captured_at_utc,
        last_session_l=sample.last_session_l,
        pulse_count=sample.pulse_count,
        total_l=sample.total_l,
        hydrological_year_l=sample.hydrological_year_l,
    )
    session.commit()
    return flowmeter_session.id


def maybe_reset_hydrological_year(
    *,
    session: Session,
    client: ArgosNodeClient,
    now_utc: datetime,
    reset_month: int,
    reset_day: int,
) -> bool:
    if not _is_valid_month_day(reset_month, reset_day):
        raise ValueError("hydrological year reset date must be a valid month/day.")
    now_utc = _as_utc(now_utc)
    if (now_utc.month, now_utc.day) != (reset_month, reset_day):
        return False
    repository = ArgosNodeRepository(session)
    node_url = client.base_url.rstrip("/")
    if repository.flowmeter_reset_event(
        node_url=node_url,
        reset_type=HYDROLOGICAL_YEAR_RESET_TYPE,
        administrative_year=now_utc.year,
    ):
        return False
    client.reset_flowmeter_hydrological_year()
    repository.create_flowmeter_reset_event(
        node_url=node_url,
        reset_type=HYDROLOGICAL_YEAR_RESET_TYPE,
        administrative_year=now_utc.year,
        reset_at_utc=now_utc,
    )
    session.commit()
    return True


def run_flowmeter_minute_capture(
    *,
    session_factory: sessionmaker[Session],
    client: ArgosNodeClient,
    poll_interval_seconds: float = 5.0,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_completed_windows: int | None = None,
    stop_event: Event | None = None,
    hydrological_year_reset_month: int | None = None,
    hydrological_year_reset_day: int | None = None,
) -> int:
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than 0.")
    now = clock or (lambda: datetime.now(UTC))
    aggregator = FlowmeterMinuteAggregator(node_url=client.base_url)
    completed_windows = 0
    previous_session_active: bool | None = None
    with session_factory() as trace_session:
        run_trace = start_ingestion_run(
            trace_session,
            source_code="argos_node_flowmeter",
            mode="minute_capture",
            trigger="worker",
            parameters_json={"node_url": client.base_url, "poll_interval_seconds": poll_interval_seconds},
        )
        trace_session.commit()
        ingestion_run_id = run_trace.id
    try:
        while (max_completed_windows is None or completed_windows < max_completed_windows) and not _should_stop(stop_event):
            try:
                status = client.get_status()
                if status is None:
                    raise ArgosNodeStatusError("argos-node returned an empty status response.")
                captured_at_utc = now()
                sample = sample_from_status(status=status, captured_at_utc=captured_at_utc)
            except (ArgosNodeError, ArgosNodeStatusError) as exc:
                logger.warning("argos-node flowmeter poll failed; will retry: %s", exc)
                _wait_for_next_poll(stop_event=stop_event, sleep=sleep, poll_interval_seconds=poll_interval_seconds)
                continue
            if previous_session_active is True and sample.session_active is False:
                with session_factory() as session:
                    persist_flowmeter_session_close(session=session, node_url=client.base_url, sample=sample)
            previous_session_active = sample.session_active
            if hydrological_year_reset_month is not None and hydrological_year_reset_day is not None:
                with session_factory() as session:
                    maybe_reset_hydrological_year(
                        session=session,
                        client=client,
                        now_utc=captured_at_utc,
                        reset_month=hydrological_year_reset_month,
                        reset_day=hydrological_year_reset_day,
                    )
            completed = aggregator.add_sample(sample)
            if completed is not None:
                with session_factory() as session:
                    persist_flowmeter_minute(
                        session=session,
                        aggregate=completed,
                        ingestion_run_id=ingestion_run_id,
                    )
                completed_windows += 1
            if max_completed_windows is None or completed_windows < max_completed_windows:
                _wait_for_next_poll(stop_event=stop_event, sleep=sleep, poll_interval_seconds=poll_interval_seconds)
    except Exception as exc:
        with session_factory() as trace_session:
            run_trace = trace_session.get(type(run_trace), ingestion_run_id)
            if run_trace is not None:
                mark_run_failed(run_trace, exc)
                trace_session.commit()
        raise
    with session_factory() as trace_session:
        run_trace = trace_session.get(type(run_trace), ingestion_run_id)
        if run_trace is not None:
            run_trace.inserted_count = completed_windows
            finalize_ingestion_run(run_trace)
            trace_session.commit()
    return completed_windows


def _capture_from_minute(minute: ArgosNodeFlowmeterMinute, *, created: bool) -> FlowmeterMinuteCapture:
    return FlowmeterMinuteCapture(
        minute_id=minute.id,
        created=created,
        node_url=minute.node_url,
        window_start_utc=minute.window_start_utc,
        samples_count=minute.samples_count,
        pulse_delta=minute.pulse_delta,
        volume_l=minute.volume_l,
    )


def _digital_inputs(inputs: Any) -> list[Mapping[str, Any]]:
    if inputs is None:
        return []
    inputs_mapping = _mapping(inputs, "inputs")
    digital = inputs_mapping.get("digital")
    if digital is None:
        return []
    if not isinstance(digital, list):
        raise ArgosNodeStatusError("inputs.digital must be a list.")
    if digital and not isinstance(digital[0], Mapping):
        raise ArgosNodeStatusError("inputs.digital[0] must be an object.")
    return digital


def _digital_input_state(digital: list[Mapping[str, Any]], *, input_id: int) -> bool | None:
    for item in digital:
        if item.get("id") == input_id:
            return _optional_bool(item.get("state"))
    index = input_id - 1
    if 0 <= index < len(digital):
        return _optional_bool(digital[index].get("state"))
    if input_id == 8 and digital:
        return _optional_bool(digital[0].get("state"))
    return None


def _ev8_state_from_status(status: Mapping[str, Any]) -> bool | None:
    valves = status.get("valves")
    if isinstance(valves, list):
        for valve in valves:
            if isinstance(valve, Mapping) and valve.get("id") == 8:
                return parse_relay_open_state(valve)
    outputs = status.get("outputs")
    if isinstance(outputs, Mapping):
        relays = outputs.get("relays")
        if isinstance(relays, list) and relays:
            for relay in relays:
                if isinstance(relay, Mapping) and relay.get("id") == 8:
                    return _optional_bool(relay.get("state"))
            if len(relays) >= 8 and isinstance(relays[7], Mapping):
                return _optional_bool(relays[7].get("state"))
            for relay in relays:
                if isinstance(relay, Mapping) and relay.get("id") == 1:
                    return _optional_bool(relay.get("state"))
    if isinstance(valves, list):
        for valve in valves:
            if isinstance(valve, Mapping) and valve.get("id") == 1:
                return parse_relay_open_state(valve)
    return None


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArgosNodeStatusError(f"{field_name} must be an object.")
    return value


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ArgosNodeStatusError("digital input state must be a boolean.")
    return value


def _required_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ArgosNodeStatusError(f"{field_name} must be a boolean.")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArgosNodeStatusError(f"{field_name} must be an integer.")
    return value


def _required_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ArgosNodeStatusError(f"{field_name} must be a number.")
    return float(value)


def _minute_start(value: datetime) -> datetime:
    return _as_utc(value).replace(second=0, microsecond=0)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_valid_month_day(month: int, day: int) -> bool:
    try:
        date(2000, month, day)
    except ValueError:
        return False
    return True


def _should_stop(stop_event: Event | None) -> bool:
    return stop_event is not None and stop_event.is_set()


def _wait_for_next_poll(
    *,
    stop_event: Event | None,
    sleep: Callable[[float], None],
    poll_interval_seconds: float,
) -> None:
    if _should_stop(stop_event):
        return
    if stop_event is not None:
        stop_event.wait(poll_interval_seconds)
    else:
        sleep(poll_interval_seconds)
