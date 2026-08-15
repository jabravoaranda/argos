# ARGOS Ingestion Traceability Gap Analysis

Document type: Historical audit
Snapshot date: 2026-08-02
Current-state authority: docs/00-estado-del-proyecto.md
Generated manually/automatically: manual
Do not use this document as the sole source of current operational state.

Date: 2026-08-02

Scope: phase 3 data architecture work for shared ingestion traceability. The schema was audited against a restored copy of the real SQLite database, not against `var/argos.db` directly. No conflicting rows were automatically removed, merged, or modified.

## Restored Database Audit

Restored copy:

```text
.pytest-tmp/traceability-real-db/argos-restored-20260802T164904Z.db
```

Backup source:

```text
.pytest-tmp/traceability-backups/argos-20260802T164904Z.db
```

Observed state before new migrations:

- Alembic revision: `20260802_0015`.
- SQLite integrity check: `ok`.
- `weather_observations`: 4,446 rows.
- `satellite_assets`: 3,067 rows.
- `ecowitt_raw_reports`: 1,895 rows.
- `ecowitt_cloud_raw_reports`: 4,566 rows.
- `weather_daily_observations`: 5,986 rows.
- `satellite_observations`: 1,534 rows.
- `argos_node_flowmeter_minutes`: 188 rows.

Ecowitt nullability audit on `weather_observations`:

| Column | NULL rows |
|---|---:|
| `gateway_id` | 0 |
| `observed_at_utc` | 0 |
| `source` | 0 |

Ecowitt source distribution:

| Source | Rows |
|---|---:|
| `BACKFILLED` | 2,556 |
| `DIRECT` | 1,890 |

No duplicate groups were found for the phase 1 natural keys.

## Existing Natural Constraints

The following domains were verified as already protected by database-level unique constraints or unique indexes:

| Domain | Natural key | Status |
|---|---|---|
| `weather_daily_observations` | `station_id, observation_date` | Protected |
| `satellite_observations` | `source_id, zone_id, external_item_id, processing_version` | Protected |
| `argos_node_flowmeter_minutes` | `node_url, window_start_utc` | Protected |
| `argos_node_flowmeter_sessions` | `node_url, closed_at_utc` | Protected |
| `argos_node_flowmeter_reset_events` | `node_url, reset_type, administrative_year` | Protected |

No extra uniqueness migrations are included for those domains in this phase.

## Gap Analysis

Before this phase, traceability was source-specific:

- AEMET had `aemet_sync_runs`, but it did not cover other domains.
- Ecowitt LAN and Cloud had raw report tables plus events, but no run ledger or durable cursor.
- Satellite had raw STAC/statistics metadata in `satellite_observations` and file references in `satellite_assets`, but no common run, item, or artifact table.
- Flowmeter data had idempotent minute/session/reset keys, but no ingestion run relation for capture windows.

This phase introduces additive shared tables:

- `data_sources`: canonical source registry.
- `ingestion_runs`: execution status, requested windows, counts, trigger and processing version.
- `ingestion_items`: per-interval or per-source-item status and counters.
- `sync_cursors`: durable last-success cursor per source scope.
- `source_artifacts`: checksummed local artifacts such as satellite preview files.

Domain rows keep their typed schemas. New provenance columns are nullable so legacy rows remain valid and can be backfilled later by explicit operator decision.

## Migration Policy

The migration path is intentionally additive except for Ecowitt observation identity hardening:

- Add shared traceability tables.
- Seed `data_sources` idempotently without secrets.
- Add nullable foreign keys from domain tables to traceability tables.
- Make `weather_observations.gateway_id`, `observed_at_utc`, and `source` non-null only after a precheck confirms zero incompatible rows.

If future real data contains NULL identity rows, migration `20260802_0023` raises an error and stops. It does not repair or delete data.
