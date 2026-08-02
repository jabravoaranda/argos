from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from argos.database.base import Base
from argos.dashboard.argos_node_client import ArgosNodeError
from argos.models import ArgosNodeFlowmeterMinute, ArgosNodeFlowmeterResetEvent, ArgosNodeFlowmeterSession
from argos.services.argos_node_flowmeter import (
    ArgosNodeStatusError,
    FlowmeterMinuteAggregator,
    FlowmeterSample,
    parse_flowmeter_status,
    parse_relay_open_state,
    maybe_reset_hydrological_year,
    persist_flowmeter_minute,
    run_flowmeter_minute_capture,
)


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Session:
    with session_factory() as db_session:
        yield db_session


def test_parse_flowmeter_status_reads_argos_node_fields() -> None:
    parsed = parse_flowmeter_status(
        {
            "flowmeter": {
                "pulse_count": 42,
                "flow_l_min": 12.5,
                "boot_total_l": 1.5,
                "total_l": 100.25,
                "hydrological_year_l": 80.0,
                "session_active": True,
                "session_l": 7.5,
                "last_session_l": 3.25,
            },
            "inputs": {"digital": [{"id": 8, "state": True}]},
        }
    )

    assert parsed.pulse_count == 42
    assert parsed.flow_l_min == 12.5
    assert parsed.boot_total_l == 1.5
    assert parsed.total_l == 100.25
    assert parsed.hydrological_year_l == 80.0
    assert parsed.session_active is True
    assert parsed.session_l == 7.5
    assert parsed.last_session_l == 3.25
    assert parsed.di1_state is True
    assert parsed.relay1_state is True


def test_parse_flowmeter_status_reads_di8_by_position() -> None:
    parsed = parse_flowmeter_status(
        {
            "flowmeter": {
                "pulse_count": 42,
                "flow_l_min": 12.5,
                "boot_total_l": 1.5,
                "total_l": 100.25,
                "hydrological_year_l": 80.0,
                "session_active": False,
                "session_l": 0.0,
                "last_session_l": 3.25,
            },
            "inputs": {"digital": [{"state": False} for _index in range(7)] + [{"state": True}]},
        }
    )

    assert parsed.di1_state is True


def test_parse_flowmeter_status_rejects_missing_flowmeter() -> None:
    with pytest.raises(ArgosNodeStatusError, match="flowmeter"):
        parse_flowmeter_status({"inputs": {"digital": [{"state": False}]}})


def test_flowmeter_minute_aggregator_emits_completed_utc_window() -> None:
    aggregator = FlowmeterMinuteAggregator(node_url="http://192.168.1.40/")

    assert (
        aggregator.add_sample(
            _sample("2026-07-31T08:10:00Z", pulse_count=100, flow_l_min=1.0, relay1_state=False)
        )
        is None
    )
    assert (
        aggregator.add_sample(
            _sample("2026-07-31T08:10:05Z", pulse_count=110, flow_l_min=4.5, relay1_state=True)
        )
        is None
    )
    assert (
        aggregator.add_sample(
            _sample("2026-07-31T08:10:55Z", pulse_count=154, flow_l_min=2.0, relay1_state=True)
        )
        is None
    )
    completed = aggregator.add_sample(
        _sample("2026-07-31T08:11:00Z", pulse_count=160, flow_l_min=1.0, relay1_state=False)
    )

    assert completed is not None
    assert completed.node_url == "http://192.168.1.40"
    assert completed.window_start_utc == datetime(2026, 7, 31, 8, 10, tzinfo=UTC)
    assert completed.window_end_utc == datetime(2026, 7, 31, 8, 11, tzinfo=UTC)
    assert completed.pulse_count_start == 100
    assert completed.pulse_count_end == 154
    assert completed.pulse_delta == 54
    assert completed.total_l_start == 100.0
    assert completed.total_l_end == 154.0
    assert completed.hydrological_year_l_end == 154.0
    assert completed.session_active_end is True
    assert completed.last_session_l_end == 0.0
    assert completed.volume_l == 2.0
    assert completed.avg_flow_l_min == 2.0
    assert completed.max_flow_l_min == 4.5
    assert completed.samples_count == 3
    assert completed.relay1_state_start is False
    assert completed.relay1_state_end is True
    assert completed.relay1_open_samples_count == 2
    assert completed.relay1_open_fraction == pytest.approx(2 / 3)


def test_persist_flowmeter_minute_upserts_one_row_per_node_and_window(session: Session) -> None:
    aggregator = FlowmeterMinuteAggregator(node_url="http://192.168.1.40")
    aggregator.add_sample(_sample("2026-07-31T08:10:00Z", pulse_count=100, flow_l_min=1.0))
    completed = aggregator.add_sample(_sample("2026-07-31T08:11:00Z", pulse_count=127, flow_l_min=2.0))
    assert completed is not None

    first = persist_flowmeter_minute(session=session, aggregate=completed)
    second = persist_flowmeter_minute(session=session, aggregate=completed)

    minute = session.scalar(select(ArgosNodeFlowmeterMinute))
    assert minute is not None
    assert first.created is True
    assert second.created is False
    assert first.minute_id == second.minute_id == minute.id
    assert minute.pulse_delta == 0
    assert minute.samples_count == 1


def test_run_flowmeter_minute_capture_polls_until_completed_window(session_factory: sessionmaker[Session]) -> None:
    statuses = [
        _status(pulse_count=100, flow_l_min=1.0),
        _status(pulse_count=127, flow_l_min=3.0),
        _status(pulse_count=154, flow_l_min=2.0),
        _status(pulse_count=160, flow_l_min=0.5),
    ]
    timestamps = iter(
        [
            datetime(2026, 7, 31, 8, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 10, 5, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 10, 55, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 11, 0, tzinfo=UTC),
        ]
    )
    client = FakeArgosNodeClient(base_url="http://192.168.1.40", statuses=statuses)

    completed_count = run_flowmeter_minute_capture(
        session_factory=session_factory,
        client=client,
        poll_interval_seconds=5,
        clock=lambda: next(timestamps),
        sleep=lambda _seconds: None,
        max_completed_windows=1,
    )

    with session_factory() as session:
        minute = session.scalar(select(ArgosNodeFlowmeterMinute))
        assert minute is not None
        assert completed_count == 1
        assert minute.pulse_count_start == 100
        assert minute.pulse_count_end == 154
        assert minute.pulse_delta == 54
        assert minute.total_l_end == 154.0
        assert minute.hydrological_year_l_end == 154.0
        assert minute.session_active_end is True
        assert minute.session_l_end == 154.0
        assert minute.last_session_l_end == 0.0
        assert minute.volume_l == 2.0
        assert minute.avg_flow_l_min == 2.0
        assert minute.max_flow_l_min == 3.0
        assert minute.samples_count == 3
        assert minute.relay1_state_start is False
        assert minute.relay1_state_end is True
        assert minute.relay1_open_samples_count == 2
        assert minute.relay1_open_fraction == pytest.approx(2 / 3)


def test_run_flowmeter_minute_capture_retries_transient_node_errors(
    session_factory: sessionmaker[Session],
) -> None:
    statuses: list[dict[str, Any] | Exception] = [
        ArgosNodeError("Could not connect to argos-node at http://192.168.1.40."),
        _status(pulse_count=100, flow_l_min=1.0),
        _status(pulse_count=154, flow_l_min=2.0),
    ]
    timestamps = iter(
        [
            datetime(2026, 7, 31, 8, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 11, 0, tzinfo=UTC),
        ]
    )
    sleep_calls: list[float] = []
    client = FakeArgosNodeClient(base_url="http://192.168.1.40", statuses=statuses)

    completed_count = run_flowmeter_minute_capture(
        session_factory=session_factory,
        client=client,
        poll_interval_seconds=5,
        clock=lambda: next(timestamps),
        sleep=sleep_calls.append,
        max_completed_windows=1,
    )

    with session_factory() as session:
        minute = session.scalar(select(ArgosNodeFlowmeterMinute))
        assert minute is not None
        assert completed_count == 1
        assert minute.pulse_count_start == 100
        assert minute.pulse_count_end == 100
        assert sleep_calls == [5, 5]


def test_run_flowmeter_minute_capture_records_closed_session_from_last_session_l(
    session_factory: sessionmaker[Session],
) -> None:
    statuses = [
        _status(pulse_count=100, flow_l_min=1.0, session_active=True, session_l=2.0, last_session_l=0.0),
        _status(pulse_count=127, flow_l_min=0.0, session_active=False, session_l=9.25, last_session_l=9.25),
        _status(pulse_count=127, flow_l_min=0.0, session_active=False, session_l=9.25, last_session_l=9.25),
    ]
    timestamps = iter(
        [
            datetime(2026, 7, 31, 8, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 10, 5, tzinfo=UTC),
            datetime(2026, 7, 31, 8, 11, 0, tzinfo=UTC),
        ]
    )
    client = FakeArgosNodeClient(base_url="http://192.168.1.40", statuses=statuses)

    run_flowmeter_minute_capture(
        session_factory=session_factory,
        client=client,
        poll_interval_seconds=5,
        clock=lambda: next(timestamps),
        sleep=lambda _seconds: None,
        max_completed_windows=1,
    )

    with session_factory() as session:
        flowmeter_session = session.scalar(select(ArgosNodeFlowmeterSession))
        assert flowmeter_session is not None
        assert flowmeter_session.last_session_l == 9.25
        assert flowmeter_session.closed_at_utc == datetime(2026, 7, 31, 8, 10, 5)


def test_maybe_reset_hydrological_year_posts_once_per_admin_year(session: Session) -> None:
    client = FakeArgosNodeClient(base_url="http://192.168.1.40", statuses=[])

    first = maybe_reset_hydrological_year(
        session=session,
        client=client,
        now_utc=datetime(2026, 10, 1, 6, 0, tzinfo=UTC),
        reset_month=10,
        reset_day=1,
    )
    second = maybe_reset_hydrological_year(
        session=session,
        client=client,
        now_utc=datetime(2026, 10, 1, 7, 0, tzinfo=UTC),
        reset_month=10,
        reset_day=1,
    )

    event = session.scalar(select(ArgosNodeFlowmeterResetEvent))
    assert first is True
    assert second is False
    assert client.hydrological_year_resets == 1
    assert event is not None
    assert event.administrative_year == 2026


def test_parse_relay_open_state_reads_relay1_response() -> None:
    assert parse_relay_open_state({"open": True}) is True
    assert parse_relay_open_state({"state": "closed"}) is False
    assert parse_relay_open_state({"status": "moving"}) is None


class FakeArgosNodeClient:
    def __init__(self, *, base_url: str, statuses: list[dict[str, Any] | Exception]) -> None:
        self.base_url = base_url
        self.statuses = statuses
        self.hydrological_year_resets = 0

    def get_status(self) -> dict[str, Any] | None:
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        return status

    def get_valve(self, valve_id: int) -> dict[str, Any] | None:
        assert valve_id == 1
        return None

    def reset_flowmeter_hydrological_year(self) -> dict[str, Any] | None:
        self.hydrological_year_resets += 1
        return {}


def _sample(
    captured_at: str,
    *,
    pulse_count: int,
    flow_l_min: float,
    relay1_state: bool | None = None,
) -> FlowmeterSample:
    return FlowmeterSample(
        captured_at_utc=datetime.fromisoformat(captured_at.replace("Z", "+00:00")),
        pulse_count=pulse_count,
        flow_l_min=flow_l_min,
        boot_total_l=float(pulse_count),
        total_l=float(pulse_count),
        hydrological_year_l=float(pulse_count),
        session_active=bool(relay1_state),
        session_l=float(pulse_count),
        last_session_l=0.0,
        di1_state=None,
        relay1_state=relay1_state,
    )


def _status(
    *,
    pulse_count: int,
    flow_l_min: float,
    session_active: bool | None = None,
    session_l: float | None = None,
    last_session_l: float = 0.0,
) -> dict[str, Any]:
    relay_state = pulse_count in {127, 154}
    active = relay_state if session_active is None else session_active
    return {
        "flowmeter": {
            "pulse_count": pulse_count,
            "flow_l_min": flow_l_min,
            "boot_total_l": float(pulse_count),
            "total_l": float(pulse_count),
            "hydrological_year_l": float(pulse_count),
            "session_active": active,
            "session_l": float(pulse_count) if session_l is None else session_l,
            "last_session_l": last_session_l,
        },
        "inputs": {"digital": [{"id": 8, "state": False}]},
    }
