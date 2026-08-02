# Data Integrity Preflight

Document type: Historical audit
Snapshot date: 2026-08-02
Current-state authority: docs/00-estado-del-proyecto.md
Generated manually/automatically: manual
Do not use this document as the sole source of current operational state.

Date: 2026-08-02

This preflight was run before adding database-level uniqueness for Ecowitt weather observations and satellite assets. The active database `var/argos.db` was not migrated or modified.

## Copy Used

Commands:

```powershell
uv run python scripts/backup_sqlite.py --database-url "sqlite:///./var/argos.db" --backup-dir ".pytest-tmp/audit-backups"
uv run python scripts/restore_sqlite.py --backup ".pytest-tmp/audit-backups/argos-20260802T161535Z.db" --target ".pytest-tmp/audit-real-db/argos-restored.db" --overwrite
$env:DATABASE_URL = "sqlite:///C:/Users/Fizico/Documents/github/argos/.pytest-tmp/audit-real-db/argos-restored.db"
uv run argos data audit-duplicates
```

Restored copy:

```text
C:\Users\Fizico\Documents\github\argos\.pytest-tmp\audit-real-db\argos-restored.db
```

Result:

- `PRAGMA integrity_check`: `ok`
- Alembic revision: `20260802_0015`
- `weather_observations`: 4,413 rows
- `satellite_assets`: 3,067 rows

## Duplicate Audit

No duplicate groups were found for:

- `weather_observations(gateway_id, observed_at_utc, source)`
- `ecowitt_raw_reports(payload_hash)`
- `ecowitt_cloud_raw_reports(payload_hash)`
- `weather_daily_observations(station_id, observation_date)`
- `satellite_observations(source_id, zone_id, external_item_id, processing_version)`
- `satellite_assets(observation_id, asset_type)`
- `argos_node_flowmeter_minutes(node_url, window_start_utc)`
- field event duplicate warning key

## Existing Natural Constraints Verified

These domains already had database-level uniqueness and were not expanded in this phase:

- `weather_daily_observations`: `uq_weather_daily_observations_station_date`
- `satellite_observations`: `uq_satellite_observations_source_zone_item_version`
- `argos_node_flowmeter_minutes`: `uq_argos_node_flowmeter_minutes_node_window`
- `argos_node_flowmeter_sessions`: `uq_argos_node_flowmeter_sessions_node_closed_at`
- `argos_node_flowmeter_reset_events`: `uq_argos_node_flowmeter_reset_year`

## New Constraints Prepared

The only new uniqueness constraints in this phase are:

- `uq_weather_observations_gateway_observed_source`
- `uq_satellite_assets_observation_type`

The Alembic migration includes preflight duplicate checks and aborts before schema changes if conflicting rows are present.
