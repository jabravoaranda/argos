from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from argos.models.field_event import FieldEvent


class FieldEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, values: dict[str, Any]) -> FieldEvent:
        event = FieldEvent(**values)
        self.session.add(event)
        self.session.flush()
        return event

    def get(self, event_id: int) -> FieldEvent | None:
        return self.session.get(FieldEvent, event_id)

    def update(self, event: FieldEvent, values: dict[str, Any]) -> FieldEvent:
        for key, value in values.items():
            setattr(event, key, value)
        self.session.flush()
        return event

    def delete(self, event: FieldEvent) -> None:
        self.session.delete(event)
        self.session.flush()

    def list(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        event_type: str | None = None,
        zone_slug: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[FieldEvent]:
        statement = select(FieldEvent).order_by(desc(FieldEvent.occurred_at), desc(FieldEvent.id))
        if start is not None:
            statement = statement.where(FieldEvent.occurred_at >= start)
        if end is not None:
            statement = statement.where(FieldEvent.occurred_at <= end)
        if event_type is not None:
            statement = statement.where(FieldEvent.event_type == event_type)
        if zone_slug is not None:
            statement = statement.where(FieldEvent.zone_slug == zone_slug)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(or_(FieldEvent.title.ilike(pattern), FieldEvent.description.ilike(pattern)))
        statement = statement.limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())
