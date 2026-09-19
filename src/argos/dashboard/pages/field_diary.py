from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from argos.config.settings import get_settings
from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.formatting import format_compact_local_datetime, format_utc_iso, parse_datetime
from argos.domain.field_events import FIELD_EVENT_TYPE_LABELS, FIELD_ZONE_LABELS


@st.cache_data(ttl=60)
def cached_field_event_catalog(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_field_event_catalog()


@st.cache_data(ttl=30)
def cached_field_events(
    base_url: str,
    start: str | None,
    end: str | None,
    event_type: str | None,
    zone_slug: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_field_events(
        start=start,
        end=end,
        event_type=event_type,
        zone_slug=zone_slug,
        search=search,
        limit=1000,
    )


def render_field_diary(client: ArgosApiClient) -> None:
    catalog = cached_field_event_catalog(client.base_url)
    event_type_labels = {item["slug"]: item["label"] for item in catalog.get("event_types", [])} or FIELD_EVENT_TYPE_LABELS
    zone_labels = {item["slug"]: item["label"] for item in catalog.get("zones", [])} or FIELD_ZONE_LABELS

    left, right = st.columns([1, 0.22], vertical_alignment="center")
    with left:
        st.title("Diario de campo")
    with right:
        with st.popover("Registrar evento", icon=":material/add:"):
            render_field_event_form(
                client,
                event_type_labels=event_type_labels,
                zone_labels=zone_labels,
                mode="create",
                event=None,
            )

    start_iso, end_iso, selected_type, selected_zone, search = render_field_event_filters(
        event_type_labels=event_type_labels,
        zone_labels=zone_labels,
    )
    try:
        rows = cached_field_events(client.base_url, start_iso, end_iso, selected_type, selected_zone, search)
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    count_col, export_col = st.columns([1, 0.18], vertical_alignment="center")
    with count_col:
        st.caption(f"{len(rows)} eventos en el filtro activo.")
    with export_col:
        if rows:
            st.download_button(
                "Exportar CSV",
                data=field_events_csv(rows, event_type_labels=event_type_labels, zone_labels=zone_labels),
                file_name="argos_diario_campo.csv",
                mime="text/csv",
                icon=":material/download:",
                key="field_events_export_csv",
                width="stretch",
            )

    render_field_event_delete_confirmation(client)
    edit_id = st.session_state.get("field_event_edit_id")
    if edit_id is not None:
        event = next((row for row in rows if row.get("id") == edit_id), None)
        if event is not None:
            with st.container(border=True, gap="small"):
                st.subheader("Editar evento")
                render_field_event_form(
                    client,
                    event_type_labels=event_type_labels,
                    zone_labels=zone_labels,
                    mode="edit",
                    event=event,
                )

    render_field_event_table(rows, event_type_labels=event_type_labels, zone_labels=zone_labels)


def render_field_event_filters(
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> tuple[str, str, str | None, str | None, str | None]:
    today = datetime.now(ZoneInfo(get_settings().local_timezone)).date()
    st.session_state.setdefault("field_events_start_date", today - timedelta(days=90))
    st.session_state.setdefault("field_events_end_date", today)
    st.session_state.setdefault("field_events_type", "Todos")
    st.session_state.setdefault("field_events_zone", "Todas")
    st.session_state.setdefault("field_events_search", "")

    with st.container(border=True, gap="small"):
        date_col, type_col, zone_col, search_col, reset_col = st.columns([1, 1.05, 1.05, 1.25, 0.55])
        with date_col:
            start_date = st.date_input("Desde", key="field_events_start_date")
            end_date = st.date_input("Hasta", key="field_events_end_date")
        with type_col:
            type_options = ["Todos", *event_type_labels]
            event_type = st.selectbox(
                "Tipo",
                options=type_options,
                key="field_events_type",
                format_func=lambda value: "Todos" if value == "Todos" else event_type_labels.get(value, value),
            )
        with zone_col:
            zone_options = ["Todas", *zone_labels]
            zone = st.selectbox(
                "Zona",
                options=zone_options,
                key="field_events_zone",
                format_func=lambda value: "Todas" if value == "Todas" else zone_labels.get(value, value),
            )
        with search_col:
            search = st.text_input("Buscar", key="field_events_search")
        with reset_col:
            st.write("")
            st.write("")
            if st.button("Limpiar", icon=":material/close:", key="field_events_clear_filters"):
                st.session_state["field_events_start_date"] = today - timedelta(days=90)
                st.session_state["field_events_end_date"] = today
                st.session_state["field_events_type"] = "Todos"
                st.session_state["field_events_zone"] = "Todas"
                st.session_state["field_events_search"] = ""
                st.rerun()

    return (
        field_event_start_iso(start_date),
        field_event_end_iso(end_date),
        None if event_type == "Todos" else event_type,
        None if zone == "Todas" else zone,
        search.strip() or None,
    )


def render_field_event_table(
    rows: list[dict[str, Any]],
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> None:
    if not rows:
        st.info("Sin eventos para los filtros activos.")
        return

    st.html(
        """
        <div class="argos-field-event-table">
            <div class="argos-field-event-row header">
                <span>Fecha y hora</span><span>Tipo</span><span>Título</span><span>Zona</span>
                <span>Árbol/fila</span><span>Cantidad</span><span>Descripción</span>
            </div>
        </div>
        """
    )
    for row in rows:
        content_col, action_col = st.columns([10, 1.2], vertical_alignment="center")
        with content_col:
            st.html(field_event_row_html(row, event_type_labels=event_type_labels, zone_labels=zone_labels))
        with action_col:
            if st.button("Editar", key=f"field_event_edit_{row['id']}", icon=":material/edit:", width="stretch"):
                st.session_state["field_event_edit_id"] = row["id"]
                st.rerun()
            if st.button("Eliminar", key=f"field_event_delete_{row['id']}", icon=":material/delete:", width="stretch"):
                st.session_state["field_event_delete_id"] = row["id"]
                st.rerun()


def render_field_event_form(
    client: ArgosApiClient,
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
    mode: str,
    event: dict[str, Any] | None,
) -> None:
    prefix = f"field_event_{mode}_{event.get('id') if event else 'new'}"
    occurred_at = parse_datetime(event.get("occurred_at")) if event else datetime.now(UTC)
    local_occurred = (occurred_at or datetime.now(UTC)).astimezone(ZoneInfo(get_settings().local_timezone))
    type_options: list[str] = list(event_type_labels)
    zone_options: list[str] = ["", *zone_labels]
    current_event_type = event.get("event_type") if event else None
    event_type_index = type_options.index(current_event_type) if isinstance(current_event_type, str) and current_event_type in type_options else 0
    current_zone_slug = event.get("zone_slug") if event else None
    zone_index = zone_options.index(current_zone_slug) if isinstance(current_zone_slug, str) and current_zone_slug in zone_options else 0

    def event_type_label(value: str) -> str:
        return event_type_labels.get(value, value)

    def zone_label(value: str) -> str:
        return "—" if not value else zone_labels.get(value, value)

    with st.form(prefix):
        date_col, time_col, type_col = st.columns([1, 0.8, 1.2])
        with date_col:
            event_date = st.date_input("Fecha", value=local_occurred.date(), key=f"{prefix}_date")
        with time_col:
            event_time = st.time_input("Hora", value=local_occurred.time().replace(microsecond=0), key=f"{prefix}_time")
        with type_col:
            selected_event_type = st.selectbox(
                "Tipo",
                options=type_options,
                index=event_type_index,
                format_func=event_type_label,
                key=f"{prefix}_type",
            )
        title = st.text_input("Título", value=event.get("title", "") if event else "", key=f"{prefix}_title")
        description = st.text_area(
            "Descripción",
            value=event.get("description") or "" if event else "",
            height=90,
            key=f"{prefix}_description",
        )
        zone_col, tree_col, quantity_col, unit_col = st.columns([1.1, 1.1, 0.8, 0.8])
        with zone_col:
            selected_zone_slug = st.selectbox(
                "Zona",
                options=zone_options,
                index=zone_index,
                format_func=zone_label,
                key=f"{prefix}_zone",
            )
        with tree_col:
            tree_reference = st.text_input("Árbol/fila", value=event.get("tree_reference") or "" if event else "", key=f"{prefix}_tree")
        with quantity_col:
            quantity_text = st.text_input(
                "Cantidad",
                value=format_field_event_quantity(event.get("quantity")) if event else "",
                key=f"{prefix}_quantity",
            )
        with unit_col:
            unit = st.text_input("Unidad", value=event.get("unit") or "" if event else "", key=f"{prefix}_unit")
        submitted = st.form_submit_button(
            "Guardar" if mode == "edit" else "Registrar",
            type="primary",
            disabled=not bool(client.admin_token),
        )
    if not client.admin_token:
        st.caption("Hace falta ARGOS admin token para crear o modificar eventos.")
    if not submitted:
        return
    event_type = selected_event_type or type_options[0]
    zone_slug = selected_zone_slug or ""
    try:
        payload = field_event_form_payload(
            event_date=event_date,
            event_time=event_time,
            event_type=event_type,
            title=title,
            description=description,
            zone_slug=zone_slug,
            tree_reference=tree_reference,
            quantity_text=quantity_text,
            unit=unit,
        )
        if mode == "edit" and event is not None:
            client.update_field_event(int(event["id"]), payload)
            st.session_state.pop("field_event_edit_id", None)
        else:
            client.create_field_event(payload)
        cached_field_events.clear()
        st.rerun()
    except (ArgosApiError, ValueError) as exc:
        st.error(str(exc))


def render_field_event_delete_confirmation(client: ArgosApiClient) -> None:
    event_id = st.session_state.get("field_event_delete_id")
    if event_id is None:
        return
    with st.container(border=True, gap="small"):
        st.warning(f"¿Eliminar el evento {event_id}? Esta acción no se puede deshacer.")
        yes_col, no_col = st.columns([0.2, 0.2])
        with yes_col:
            if st.button("Eliminar", type="primary", key="field_event_confirm_delete", disabled=not bool(client.admin_token)):
                try:
                    client.delete_field_event(int(event_id))
                    st.session_state.pop("field_event_delete_id", None)
                    cached_field_events.clear()
                    st.rerun()
                except ArgosApiError as exc:
                    st.error(str(exc))
        with no_col:
            if st.button("Cancelar", key="field_event_cancel_delete"):
                st.session_state.pop("field_event_delete_id", None)
                st.rerun()


def field_event_form_payload(
    *,
    event_date: date,
    event_time: time,
    event_type: str,
    title: str,
    description: str,
    zone_slug: str,
    tree_reference: str,
    quantity_text: str,
    unit: str,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("El título es obligatorio.")
    quantity = parse_optional_float(quantity_text)
    unit = unit.strip()
    if unit and quantity is None:
        raise ValueError("La unidad requiere una cantidad.")
    return {
        "occurred_at": local_datetime_to_utc_iso(event_date, event_time),
        "event_type": event_type,
        "title": title.strip(),
        "description": description.strip() or None,
        "zone_slug": zone_slug or None,
        "tree_reference": tree_reference.strip() or None,
        "quantity": quantity,
        "unit": unit or None,
        "source": "manual",
    }


def field_event_row_html(
    row: dict[str, Any],
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> str:
    quantity = field_event_quantity_label(row.get("quantity"), row.get("unit"))
    values = [
        format_compact_local_datetime(row.get("occurred_at")),
        event_type_labels.get(str(row.get("event_type")), str(row.get("event_type"))),
        row.get("title") or "—",
        zone_labels.get(str(row.get("zone_slug")), str(row.get("zone_slug"))) if row.get("zone_slug") else "—",
        row.get("tree_reference") or "—",
        quantity,
        row.get("description") or "—",
    ]
    cells = "".join(f"<span>{escape(str(value))}</span>" for value in values)
    return f'<div class="argos-field-event-row">{cells}</div>'


def field_events_csv(
    rows: list[dict[str, Any]],
    *,
    event_type_labels: dict[str, str],
    zone_labels: dict[str, str],
) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["Fecha y hora", "Tipo", "Título", "Zona", "Árbol/fila", "Cantidad", "Descripción", "Origen"],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "Fecha y hora": format_compact_local_datetime(row.get("occurred_at")),
                "Tipo": event_type_labels.get(str(row.get("event_type")), str(row.get("event_type"))),
                "Título": row.get("title") or "",
                "Zona": zone_labels.get(str(row.get("zone_slug")), str(row.get("zone_slug"))) if row.get("zone_slug") else "",
                "Árbol/fila": row.get("tree_reference") or "",
                "Cantidad": field_event_quantity_label(row.get("quantity"), row.get("unit"), empty=""),
                "Descripción": row.get("description") or "",
                "Origen": row.get("source") or "",
            }
        )
    return output.getvalue().encode("utf-8-sig")


def field_event_quantity_label(quantity: Any, unit: Any, *, empty: str = "—") -> str:
    if quantity is None:
        return empty
    suffix = f" {unit}" if unit else ""
    return f"{float(quantity):g}{suffix}"


def format_field_event_quantity(quantity: Any) -> str:
    return "" if quantity is None else f"{float(quantity):g}"


def parse_optional_float(value: str) -> float | None:
    text = value.strip().replace(",", ".")
    if not text:
        return None
    return float(text)


def field_event_start_iso(value: date) -> str:
    return local_datetime_to_utc_iso(value, time.min)


def field_event_end_iso(value: date) -> str:
    return local_datetime_to_utc_iso(value, time.max.replace(microsecond=0))


def local_datetime_to_utc_iso(day: date, clock_time: time) -> str:
    timezone = ZoneInfo(get_settings().local_timezone)
    return format_utc_iso(datetime.combine(day, clock_time).replace(tzinfo=timezone))
