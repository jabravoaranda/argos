# ARGOS Data Integrity

Estado: Vigente
Tipo: Arquitectura
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Arquitectura de datos
Revision: 1

Date: 2026-08-02

ARGOS relies on database-level natural keys for ingestion idempotence wherever the domain has a stable identity.

## Protected Domains

| Table | Natural key |
|---|---|
| `weather_observations` | `gateway_id, observed_at_utc, source` |
| `satellite_assets` | `observation_id, asset_type` |
| `weather_daily_observations` | `station_id, observation_date` |
| `satellite_observations` | `source_id, zone_id, external_item_id, processing_version` |
| `argos_node_flowmeter_minutes` | `node_url, window_start_utc` |
| `argos_node_flowmeter_sessions` | `node_url, closed_at_utc` |
| `argos_node_flowmeter_reset_events` | `node_url, reset_type, administrative_year` |
| `plant_parcels` | `slug` |
| `plant_matrix_cells` | `parcel_id, matrix_row, matrix_column` |
| `plant_units` | `public_code`; `parcel_id, matrix_row, matrix_column` |
| `field_event_plant_units` | `field_event_id, plant_unit_id` |

Phase 3 does not add extra uniqueness to domains that were already protected.

## Ecowitt Nullability

`weather_observations.gateway_id`, `weather_observations.observed_at_utc`, and `weather_observations.source` are part of the natural identity. Migration `20260802_0023` audits these columns and stops if any NULL row exists. The migration does not repair conflicting data automatically.

## Operational Audits

Useful read-only commands:

```powershell
argos data audit-duplicates
argos data audit-ecowitt-nullability
argos data audit-source-artifacts
argos data audit-ingestion-runs
argos data show-sync-cursors
```

`argos data reconcile-ingestion-runs` lists stale running runs by default. Add `--mark-interrupted` only after deciding that those executions really cannot resume.
