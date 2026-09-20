from __future__ import annotations

import base64
from datetime import UTC, datetime, time
from html import escape
from typing import Any, Literal
from zoneinfo import ZoneInfo

import streamlit as st

from argos.config.settings import get_settings
from argos.dashboard.api_client import ArgosApiClient, ArgosApiError
from argos.dashboard.formatting import format_compact_local_datetime, format_file_size
from argos.dashboard.pages.field_diary import cached_field_events, local_datetime_to_utc_iso
from argos.dashboard.ui import compact_metric_html
from argos.domain.plants import PLANT_SPECIES_LABELS, PLANT_STATUS_LABELS

SOURCE_LABELS = {
    "manual": "Manual",
    "web": "Manual",
    "batch_upload": "Importación por lote",
    "api": "API",
    "chatgpt": "ChatGPT",
    "irrigation_system": "Sistema de riego",
    "imported": "Importado",
}


@st.cache_data(ttl=30)
def cached_plant_catalog(base_url: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_plant_catalog()


@st.cache_data(ttl=30)
def cached_plant_matrix(base_url: str, parcel_slug: str) -> dict[str, Any]:
    return ArgosApiClient(base_url=base_url).get_plant_matrix(parcel_slug=parcel_slug)


@st.cache_data(ttl=30)
def cached_plants(
    base_url: str,
    parcel_slug: str,
    status: str | None,
    species: str | None,
    irrigation_sector_id: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_plants(
        parcel_slug=parcel_slug,
        status=status,
        species=species,
        irrigation_sector_id=irrigation_sector_id,
        search=search,
    )


@st.cache_data(ttl=30)
def cached_plant_history(base_url: str, plant_id: int) -> list[dict[str, Any]]:
    return ArgosApiClient(base_url=base_url).get_plant_history(plant_id)


def render_plantation(client: ArgosApiClient) -> None:
    try:
        catalog = cached_plant_catalog(client.base_url)
        matrix = cached_plant_matrix(client.base_url, "tomillar")
    except ArgosApiError as exc:
        st.error(str(exc))
        return

    status_labels = {item["slug"]: item["label"] for item in catalog.get("statuses", [])} or PLANT_STATUS_LABELS
    species_labels = {item["slug"]: item["label"] for item in catalog.get("species", [])} or PLANT_SPECIES_LABELS
    sectors = {item["slug"]: item["label"] for item in catalog.get("irrigation_sectors", [])}
    st.title("Plantación")

    selected_status, selected_species, selected_sector, search = render_plantation_filters(
        status_labels=status_labels,
        species_labels=species_labels,
        sectors=sectors,
    )
    try:
        plants = cached_plants(client.base_url, "tomillar", selected_status, selected_species, selected_sector, search)
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    selected_from_url = st.query_params.get("plant")
    if selected_from_url and "plantation_selected_public_code" not in st.session_state:
        matching = next((plant for plant in plants if plant.get("public_code") == selected_from_url), None)
        if matching:
            st.session_state["plantation_selected_plant_id"] = matching["id"]
            st.session_state["plantation_selected_public_code"] = matching["public_code"]

    summary_col, import_col, refresh_col = st.columns([1, 0.24, 0.18], vertical_alignment="center")
    with summary_col:
        occupied = sum(1 for cell in matrix.get("cells", []) if cell.get("cell_type") == "plant")
        infrastructure = sum(1 for cell in matrix.get("cells", []) if cell.get("cell_type") == "infrastructure")
        st.caption(f"{len(plants)} árboles en el filtro. {occupied} celdas vegetales y {infrastructure} elementos no vegetales en la matriz.")
    with refresh_col:
        if st.button("Actualizar", icon=":material/refresh:", key="plantation_refresh", width="stretch"):
            cached_plant_matrix.clear()
            cached_plants.clear()
            cached_plant_history.clear()
            st.rerun()
    with import_col:
        with st.popover("Importar lote de fotos", icon=":material/add_photo_alternate:"):
            render_plant_photo_batch_import(client, matrix)

    grid_col, detail_col = st.columns([3.6, 6.4], vertical_alignment="top")
    visible_ids = {int(plant["id"]) for plant in plants}
    selected_id = st.session_state.get("plantation_selected_plant_id")
    with grid_col:
        render_plantation_legend(status_labels)
        render_plantation_matrix(matrix, visible_plant_ids=visible_ids, selected_plant_id=selected_id)
    with detail_col:
        selected = selected_plant_from_matrix(matrix, selected_id)
        render_plant_detail(client, selected, status_labels=status_labels, species_labels=species_labels)


def render_plantation_filters(
    *,
    status_labels: dict[str, str],
    species_labels: dict[str, str],
    sectors: dict[str, str],
) -> tuple[str | None, str | None, str | None, str | None]:
    with st.container(border=True, gap="small"):
        status_col, species_col, sector_col, search_col = st.columns([1, 1.15, 0.9, 1.25])
        with status_col:
            status = st.selectbox(
                "Estado",
                options=["Todos", *status_labels],
                key="plantation_status",
                format_func=lambda value: "Todos" if value == "Todos" else status_labels.get(value, value),
            )
        with species_col:
            species = st.selectbox(
                "Especie",
                options=["Todas", *species_labels],
                key="plantation_species",
                format_func=lambda value: "Todas" if value == "Todas" else species_labels.get(value, value),
            )
        with sector_col:
            sector = st.selectbox(
                "Sector",
                options=["Todos", *sectors],
                key="plantation_sector",
                format_func=lambda value: "Todos" if value == "Todos" else sectors.get(value, value),
            )
        with search_col:
            search = st.text_input("Buscar código", key="plantation_search")
    return (
        None if status == "Todos" else status,
        None if species == "Todas" else species,
        None if sector == "Todos" else sector,
        search.strip().upper() or None,
    )


def render_plantation_legend(status_labels: dict[str, str]) -> None:
    labels = " ".join(f"<span>{escape(label)}</span>" for label in status_labels.values())
    st.html(f'<div class="argos-plantation-legend">{labels}<span>Vacía</span><span>Infraestructura</span><span># desplazado</span></div>')


def render_plantation_matrix(matrix: dict[str, Any], *, visible_plant_ids: set[int], selected_plant_id: int | None) -> None:
    cells_by_position = {(cell["row"], cell["column"]): cell for cell in matrix.get("cells", [])}
    column_labels = matrix.get("column_labels", [])
    header_cols = st.columns([0.28, *([1] * 12)], gap=None)
    header_cols[0].html("&nbsp;")
    for index, label in enumerate(column_labels[:12], start=1):
        header_cols[index].html(f'<div class="argos-plantation-label">{escape(label)}</div>')
    for row_index, row_label in enumerate(matrix.get("row_labels", [])[:12], start=1):
        row_cols = st.columns([0.28, *([1] * 12)], gap=None)
        row_cols[0].html(f'<div class="argos-plantation-label">{escape(row_label)}</div>')
        for column_index in range(1, 13):
            cell = cells_by_position.get((row_index, column_index), {})
            plant = cell.get("plant")
            label = plantation_cell_label(cell)
            disabled = plant is None or int(plant["id"]) not in visible_plant_ids
            button_type: Literal["primary", "secondary"] = "primary" if plant and plant.get("id") == selected_plant_id else "secondary"
            with row_cols[column_index]:
                if st.button(
                    label,
                    key=f"plant_cell_{row_index}_{column_index}",
                    disabled=disabled,
                    type=button_type,
                    width="stretch",
                ) and plant:
                    st.session_state["plantation_selected_plant_id"] = plant["id"]
                    st.session_state["plantation_selected_public_code"] = plant["public_code"]
                    st.query_params["plant"] = plant["public_code"]
                    st.rerun()


def render_plant_photo_batch_import(client: ArgosApiClient, matrix: dict[str, Any]) -> None:
    fallback_date = st.date_input("Fecha del lote", value=datetime.now(ZoneInfo(get_settings().local_timezone)).date(), key="plant_photo_batch_date")
    uploaded_files = st.file_uploader(
        "Fotos",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="plant_photo_batch_files",
    )
    if st.button("Analizar fotos", icon=":material/search:", disabled=not bool(uploaded_files), key="plant_photo_batch_stage"):
        if not client.admin_token:
            st.error("Hace falta ARGOS admin token para importar fotos.")
            return
        try:
            photo_payloads = [uploaded_photo_payload(file) for file in uploaded_files]
            response = client.stage_plant_photo_batch(
                {
                    "fallback_taken_at": local_datetime_to_utc_iso(fallback_date, time.min),
                    "photos": photo_payloads,
                }
            )
            st.session_state["plant_photo_batch_uploads"] = {
                item["sha256"]: payload
                for item, payload in zip(response.get("items", []), photo_payloads, strict=False)
            }
            st.session_state["plant_photo_batch_items"] = response.get("items", [])
        except ArgosApiError as exc:
            st.error(str(exc))
            return
    staged_items = st.session_state.get("plant_photo_batch_items") or []
    if not staged_items:
        return
    uploaded_payloads = st.session_state.get("plant_photo_batch_uploads") or {}
    plants = sorted(
        [cell["plant"] for cell in matrix.get("cells", []) if cell.get("plant")],
        key=lambda plant: (plant["matrix_row"], plant["matrix_column"]),
    )
    options = ["", *[str(plant["id"]) for plant in plants]]
    labels = {str(plant["id"]): f"{plant['public_code']} · {plant['matrix_position_code']} · {plant['species_label']}" for plant in plants}
    confirm_items = []
    missing_uploads = False
    for item in staged_items:
        st.image(item["thumbnail_data_url"], width=120)
        st.caption(
            f"{item['filename']} · {item['status']} · código: {item.get('detected_code') or 'sin detectar'} · "
            f"confianza: {float(item.get('confidence') or 0):.2f} · resolver: {item.get('resolver') or '-'} · fecha: {item.get('date_source')}"
        )
        default_value = str(item["plant_id"]) if item.get("plant_id") else ""
        selected = st.selectbox(
            "Árbol",
            options=options,
            index=options.index(default_value) if default_value in options else 0,
            format_func=lambda value: "Sin asignar" if not value else labels[value],
            key=f"plant_photo_batch_assign_{item['index']}_{item['sha256'][:8]}",
            disabled=bool(item.get("duplicate")),
        )
        if item.get("duplicate"):
            st.warning("Duplicada: no se importará.")
        source_payload = uploaded_payloads.get(item["sha256"], {})
        if not source_payload:
            missing_uploads = True
        confirm_item = {
            key: item[key]
            for key in ("filename", "content_type", "sha256", "taken_at", "date_source", "detected_code", "confidence", "status")
        }
        confirm_item["data_base64"] = source_payload.get("data_base64", "")
        confirm_item["plant_id"] = int(selected) if selected else None
        confirm_items.append(confirm_item)
    if missing_uploads:
        st.warning("Vuelve a seleccionar las fotos para confirmar el lote.")
    has_unassigned = any(item.get("plant_id") is None and not item.get("duplicate") for item in confirm_items)
    assigned_count = sum(1 for item in confirm_items if item.get("plant_id") is not None and item.get("status") != "duplicate")
    importable_count = sum(1 for item in confirm_items if item.get("status") != "duplicate")
    if assigned_count == 0 and importable_count:
        st.warning(f"0 de {importable_count} fotografías identificadas. Revise las asignaciones antes de confirmar.")
    elif assigned_count < importable_count:
        st.info(f"{assigned_count} de {importable_count} fotografías identificadas. Complete o revise las asignaciones antes de confirmar.")
    import_unassigned = False
    if has_unassigned:
        import_unassigned = st.checkbox("Confirmar lote dejando fotos sin árbol fuera de la importación", key="plant_photo_batch_confirm_unassigned")
    confirm_disabled = missing_uploads or (has_unassigned and not import_unassigned)
    if st.button("Confirmar lote", icon=":material/check:", type="primary", key="plant_photo_batch_confirm", disabled=confirm_disabled):
        if not client.admin_token:
            st.error("Hace falta ARGOS admin token para importar fotos.")
            return
        try:
            result = client.confirm_plant_photo_batch({"fallback_taken_at": local_datetime_to_utc_iso(fallback_date, time.min), "items": confirm_items})
            st.success(
                f"{result['imported_photos']} fotos importadas en {result['created_events']} observaciones. "
                f"{result['skipped_duplicates']} duplicadas y {result['skipped_unassigned']} sin asignar."
            )
            st.session_state.pop("plant_photo_batch_items", None)
            st.session_state.pop("plant_photo_batch_uploads", None)
            cached_field_events.clear()
            cached_plant_history.clear()
        except ArgosApiError as exc:
            st.error(str(exc))


def plantation_cell_label(cell: dict[str, Any]) -> str:
    plant = cell.get("plant")
    if plant:
        public_code = plant.get("public_code") or cell.get("position_code", "")
        marker = cell.get("displacement_marker") or ""
        return str(public_code) if marker in str(public_code) else f"{public_code}{marker}"
    if cell.get("cell_type") == "infrastructure":
        return str(cell.get("visible_code") or cell.get("position_code") or "")
    return f"{cell.get('position_code', '')}\n-"


def selected_plant_from_matrix(matrix: dict[str, Any], selected_plant_id: int | None) -> dict[str, Any] | None:
    if selected_plant_id is None:
        return None
    for cell in matrix.get("cells", []):
        plant = cell.get("plant")
        if plant and plant.get("id") == selected_plant_id:
            return plant
    return None


def render_plant_detail(
    client: ArgosApiClient,
    plant: dict[str, Any] | None,
    *,
    status_labels: dict[str, str],
    species_labels: dict[str, str],
) -> None:
    if plant is None:
        st.info("Selecciona un árbol ocupado de la matriz para abrir su ficha.")
        return
    with st.container(border=True, gap="small"):
        st.subheader(f"Árbol {plant['public_code']}")
        st.caption(f"{plant['matrix_position_code']} · {plant.get('parcel_name') or plant.get('parcel_slug')}")
        ficha_tab, historial_tab = st.tabs(["Ficha", "Historial"])
        with ficha_tab:
            st.html(
                '<div class="argos-summary-grid">'
                f'{compact_metric_html("Especie", species_labels.get(plant["species"], plant["species"]))}'
                f'{compact_metric_html("Estado", status_labels.get(plant["status"], plant["status"]))}'
                f'{compact_metric_html("Sector", plant.get("irrigation_sector_id") or "Sin dato")}'
                f'{compact_metric_html("Línea", plant.get("irrigation_line_slug") or "Sin dato")}'
                "</div>"
            )
            if plant.get("variety") or plant.get("rootstock") or plant.get("planted_on"):
                st.write(
                    " · ".join(
                        value
                        for value in (
                            f"Variedad: {plant.get('variety')}" if plant.get("variety") else "",
                            f"Patrón: {plant.get('rootstock')}" if plant.get("rootstock") else "",
                            f"Plantación: {plant.get('planted_on')}" if plant.get("planted_on") else "",
                        )
                        if value
                    )
                )
            if plant.get("notes"):
                st.caption(plant["notes"])
            st.caption("Los riegos sectoriales son asociados por sector; no son mediciones individuales del árbol.")
            with st.popover("Nueva observación", icon=":material/add:"):
                render_plant_observation_form(client, plant)
        with historial_tab:
            render_plant_history(client, plant)


def render_plant_observation_form(client: ArgosApiClient, plant: dict[str, Any]) -> None:
    with st.form(f"plant_observation_{plant['id']}"):
        title = st.text_input("Título", value=f"Observación {plant['public_code']}")
        description = st.text_area("Comentario general", height=80)
        visual_observations = st.text_area("Observaciones visuales", height=80)
        interpretation = st.text_area("Interpretación", height=80)
        recommendations = st.text_area("Recomendaciones", height=80)
        actions_taken = st.text_area("Actuaciones realizadas", height=80)
        limitations = st.text_area("Limitaciones", height=80)
        uploaded_photo = st.file_uploader(
            "Foto desde móvil o archivo",
            type=["jpg", "jpeg", "png", "webp"],
            key=f"plant_observation_upload_{plant['id']}",
        )
        st.caption("En móvil, este botón permite elegir galería o cámara. La cámara integrada requiere HTTPS.")
        camera_photo = st.camera_input("Cámara integrada", key=f"plant_observation_camera_{plant['id']}")
        selected_photo = camera_photo or uploaded_photo
        if selected_photo is not None:
            st.success(f"Foto lista para registrar: {selected_photo.name} ({format_file_size(selected_photo.size)})")
        submitted = st.form_submit_button("Registrar", type="primary")
    if not submitted:
        return
    if not client.admin_token:
        st.error("Hace falta ARGOS admin token para crear eventos.")
        return
    payload = {
        "occurred_at": datetime.now(UTC).isoformat(),
        "event_type": "observation",
        "title": title.strip(),
        "description": description.strip() or None,
        "zone_slug": None,
        "tree_reference": plant["public_code"],
        "target_type": "plant",
        "target_value": plant["public_code"],
        "plant_unit_ids": [plant["id"]],
        "source": "web",
        "visual_observations": structured_lines_from_text(visual_observations),
        "interpretation": structured_lines_from_text(interpretation),
        "recommendations": structured_lines_from_text(recommendations),
        "actions_taken": structured_lines_from_text(actions_taken),
        "limitations": structured_lines_from_text(limitations),
    }
    photo_payload = uploaded_photo_payload(selected_photo)
    if photo_payload is not None:
        payload["photo"] = photo_payload
    try:
        client.create_field_event(payload)
        cached_field_events.clear()
        cached_plant_history.clear()
        st.rerun()
    except ArgosApiError as exc:
        st.error(str(exc))


def render_plant_history(client: ArgosApiClient, plant: dict[str, Any]) -> None:
    try:
        history = cached_plant_history(client.base_url, int(plant["id"]))
    except ArgosApiError as exc:
        st.error(str(exc))
        return
    if not history:
        st.caption("Sin eventos asociados.")
        return
    for event in history[:12]:
        st.write(f"{format_compact_local_datetime(event.get('occurred_at'))} · {event.get('title')}")
        source = SOURCE_LABELS.get(str(event.get("source") or ""), str(event.get("source") or ""))
        if source:
            st.caption(f"Origen: {source}")
        if event.get("description"):
            st.caption(event["description"])
        if event.get("photo_url"):
            st.image(f"{client.base_url.rstrip('/')}{event['photo_url']}", width=220)
        render_structured_history_section("OBSERVADO", event.get("visual_observations"))
        render_structured_history_section("INTERPRETACIÓN", event.get("interpretation"))
        render_structured_history_section("RECOMENDACIÓN", event.get("recommendations"))
        render_structured_history_section("ACTUACIÓN", event.get("actions_taken"))
        render_structured_history_section("LIMITACIONES", event.get("limitations"))


def structured_lines_from_text(value: str | None) -> list[str]:
    return [line.strip(" \t-•") for line in (value or "").splitlines() if line.strip(" \t-•")]


def render_structured_history_section(title: str, values: Any) -> None:
    lines = [str(item).strip() for item in (values or []) if str(item).strip()]
    if not lines:
        return
    st.markdown(f"**{title}**")
    for line in lines:
        st.markdown(f"- {line}")


def uploaded_photo_payload(uploaded_file: Any | None) -> dict[str, Any] | None:
    if uploaded_file is None:
        return None
    content = uploaded_file.getvalue()
    return {
        "filename": uploaded_file.name,
        "content_type": uploaded_file.type or "application/octet-stream",
        "data_base64": base64.b64encode(content).decode("ascii"),
    }
