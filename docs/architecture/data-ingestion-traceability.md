# ARGOS Data Ingestion Traceability

Date: 2026-08-02

ARGOS now uses a shared ingestion ledger alongside typed domain tables. The design keeps Ecowitt, AEMET, satellite, flowmeter and field-event schemas specific to their domains, while centralizing run status, idempotent item tracking, cursors and file artifact integrity.

## Tables

| Table | Purpose |
|---|---|
| `data_sources` | Canonical source codes such as `ecowitt_cloud`, `aemet_api`, `copernicus_sentinel2` and `argos_node_flowmeter`. |
| `ingestion_runs` | One execution attempt with mode, status, requested window, counts, trigger and processing version. |
| `ingestion_items` | Per item or interval status, counters and error fields. |
| `sync_cursors` | Last successful cursor per source/scope/scope_key. |
| `source_artifacts` | Local files with path, size, SHA-256, MIME type, role and provenance links. |

## Domain Links

New nullable foreign keys preserve compatibility with existing rows:

- `ecowitt_raw_reports.ingestion_run_id`
- `ecowitt_cloud_raw_reports.ingestion_run_id`
- `weather_observations.ingestion_run_id`
- `aemet_sync_runs.ingestion_run_id`
- `weather_daily_observations.ingestion_run_id`
- `weather_daily_observations.ingestion_item_id`
- `satellite_observations.ingestion_run_id`
- `satellite_observations.ingestion_item_id`
- `satellite_assets.source_artifact_id`
- `argos_node_flowmeter_minutes.ingestion_run_id`

## Run Status

Supported terminal states are:

- `completed`
- `completed_with_warnings`
- `failed`
- `cancelled`
- `interrupted`

`sync_cursors` only advance after `completed` or `completed_with_warnings` runs. The reconciliation CLI can list stale `running` rows and can mark them as `interrupted` only when explicitly invoked with `--mark-interrupted`.

## Integration Notes

- AEMET API imports create run and item rows for date intervals. CSV import records one file item.
- Ecowitt Cloud backfills create one run, link raw reports and normalized observations, and advance the gateway cursor after successful completion.
- Satellite ingestion creates one run per requested range, one item per STAC scene, source artifacts for preview PNGs, and AOI cursors after successful non-dry runs.
- Flowmeter minute capture creates one run per worker invocation and links minute aggregates to it.
- Ecowitt LAN keeps the new nullable relation available, but this phase does not create one run per HTTP upload because existing raw reports and events already provide request-level evidence and a per-upload run table would add high cardinality without improving idempotence.
