# ARGOS Data Storage Audit

Date: 2026-08-02

Scope: repository inspection plus read-only inspection of the local SQLite database at `C:\Users\Fizico\Documents\github\argos\var\argos.db`. No data, schemas, production code, or existing directories were modified.

## 1. Executive Summary

ARGOS currently uses SQLAlchemy/Alembic with SQLite by default and optional PostgreSQL. The active local database is `var/argos.db`, ignored by Git, size 47,767,552 bytes, migrated to Alembic revision `20260802_0015`. A second same-size local backup exists at `var/argos.before-remove-finca-completa.db`.

The main source of truth is SQL for normalized and queryable data. Raw payloads are also stored in SQL for Ecowitt LAN, Ecowitt Cloud, AEMET daily rows, and satellite STAC/statistics metadata. Satellite preview PNGs are the only current production artifact family stored outside SQL and referenced by SQL through `satellite_assets.storage_path`, checksum and size.

The `data/` directory is ignored by Git and contains 4,727 files: `data/aemet` has one CSV seed, `data/weather` has legacy JSON/CSV weather captures not referenced by current code, and `data/satellite` has 4,601 PNG preview assets. Rebuilding application containers does not affect these local files in the current repo workflow, but a containerized app would lose SQLite and data artifacts unless `var/` and `data/` are mounted.

No duplicate rows were found in the inspected database for the tested natural keys. Phase 1/2 addressed backup/restore tooling, SQLite hardening, duplicate audits, and natural uniqueness for `weather_observations(gateway_id, observed_at_utc, source)` plus `satellite_assets(observation_id, asset_type)`. Phase 3 adds a shared ingestion ledger, durable cursors and checksummed source artifacts. Remaining risks are documented in `docs/audits/ingestion-traceability-gap-analysis.md`.

## 2. Current Observed Architecture

- Application: FastAPI (`src/argos/main.py`) plus Streamlit dashboard.
- ORM: SQLAlchemy 2.x declarative models in `src/argos/models`.
- Migrations: Alembic in `alembic/versions`, current local DB revision `20260802_0015`.
- Default DB URL: `sqlite:///./var/argos.db` in `src/argos/config/settings.py`, `.env.example`, `alembic.ini`, and README.
- Optional DB: PostgreSQL via `postgresql+psycopg://argos:argos@localhost:5432/argos`.
- Docker Compose only starts PostgreSQL; it does not define the ARGOS app container or app bind mounts.
- Startup workers: `argos-node` flowmeter capture if `ARGOS_NODE_URL` is set; daily sync worker if `ARGOS_DAILY_SYNC_ENABLED=true`.

## 3. Exact Database Location

Observed active SQLite database:

```text
C:\Users\Fizico\Documents\github\argos\var\argos.db
```

Observed backup-like file:

```text
C:\Users\Fizico\Documents\github\argos\var\argos.before-remove-finca-completa.db
```

Connection resolution:

- `DATABASE_URL` env var loaded from `.env` by Pydantic settings.
- Default is `sqlite:///./var/argos.db`, relative to the process working directory.
- `create_db_engine()` creates the parent directory for SQLite and uses `check_same_thread=False`.
- No WAL pragma, busy timeout, backup mode, or read-only mode is configured in the engine.

PostgreSQL persistence:

- Docker service `postgres` uses named volume `postgres-data:/var/lib/postgresql/data`.
- If ARGOS runs against PostgreSQL, the database survives container recreation as long as the named volume is not deleted.
- No app container or mount for `data/`/`var/` exists in `docker-compose.yml`.

## 4. Inventory of Files and Formats

| Path | Format | Producer | Consumer | Role | Git | Survives container rebuild | Unique information |
|---|---|---|---|---|---|---|---|
| `var/argos.db` | SQLite | ARGOS ORM/migrations/services | API, dashboard, CLI, analytics | Primary local database | Ignored by `.gitignore: var/` | Only if host bind-mounted or outside container | Yes: all normalized rows and manual data |
| `var/argos.before-remove-finca-completa.db` | SQLite | Manual/operator copy | None in code | Ad hoc backup | Ignored | Only if host bind-mounted/outside container | Possibly, depending on copy date |
| `data/aemet/6127X.csv` | CSV | Manual local AEMET export | `aemet import-csv` only when path supplied | Seed/source original | Ignored by `.gitignore: data/` | Only if bind-mounted/outside container | Maybe: source evidence if not fully represented elsewhere |
| `data/weather/2026/*.csv` | CSV | Legacy/unknown, not current code | None found in current code | Legacy export/processed weather | Ignored | Only if bind-mounted/outside container | Unknown until reconciled |
| `data/weather/raw/2026/**/*.json` | JSON | Legacy/unknown, likely old raw captures | None found in current code | Legacy raw/source evidence | Ignored | Only if bind-mounted/outside container | Likely yes if not in SQL |
| `data/satellite/**.png` | PNG | `SatelliteIngestionService._store_previews()` | `/api/v1/satellite/assets/{id}`, dashboard | Derived preview assets/cache-like but SQL-referenced | Ignored | Only if bind-mounted/outside container | Regenerable from provider if available; not authoritative metrics |
| `celerybeat-schedule.*` | Celery db/shelve files | Historical Celery usage | None found now | Legacy scheduler state | Ignored pattern exists but current files are untracked | If bind-mounted/outside container | No current value found |
| `.env` | dotenv | Operator | Settings | Secrets/config | Ignored | Host file only | Yes for credentials, but should not be in backups without secret handling |
| `.env.example` | dotenv example | Repo | Humans/tests | Template | Versioned | Yes | No secrets |

`data/` summary observed:

- `data/aemet`: 1 CSV, 747,642 bytes.
- `data/weather`: 121 JSON + 4 CSV, 271,591 bytes.
- `data/satellite`: 4,601 PNG, 48,748,425 bytes.

Formats found under `data/`: PNG, JSON, CSV. No Parquet, NetCDF, TIFF, SQLite, JSONL or GeoJSON files were found under `data/`; GeoJSON geometries are supplied via `ARGOS_SATELLITE_AOIS_JSON` and stored in SQL JSON columns.

## 5. Current SQL Model

The inspected database contains 24 tables, all matching the current Alembic head.

| Table | Purpose | Producer | Consumer | Primary key | Uniqueness rule | Indexes | Risks detected |
|---|---|---|---|---|---|---|---|
| `stations` | Stable physical site identity | Ecowitt repos, migration seed | Weather APIs, gateway relation | `uuid` | `slug`, `code` | slug, code | Single-station assumptions are implicit |
| `gateways` | Ecowitt hardware | Direct/cloud Ecowitt repos | Weather status, joins | `id` | `uuid`, `mac_address` | mac, station, last_seen | `mac_address` can be model string if real MAC absent |
| `gateway_aliases` | Alternate gateway IDs | Cloud backfill repo | Gateway resolution | `id` | `alias_type, alias_value` | gateway | Limited alias taxonomy |
| `ecowitt_raw_reports` | Direct LAN raw payload | Ecowitt webhook | Admin raw reports, observation relation | `id` | `payload_hash` | gateway, received, device time, station | Hash includes parser version and normalized values, not raw body alone |
| `ecowitt_cloud_raw_reports` | Cloud raw payload | Cloud backfill/sync | Observation relation | `id` | `payload_hash` | gateway/observed, station | Hash includes gateway DB id; alias mistakes can create separate identities |
| `weather_observations` | Normalized Ecowitt weather | Direct/cloud services | Weather API, stats, analytics | `id` | `raw_report_id`, `cloud_raw_report_id` | gateway/time, observed, station | No DB-level natural unique on station/gateway/time/source |
| `daily_statistics` | Derived daily Ecowitt stats | Weather statistics service | API/dashboard | `id` | `gateway_id, period_start` | gateway/period, station | Derived; no source/version marker |
| `weekly_statistics` | Derived weekly Ecowitt stats | Weather statistics service | API/dashboard | `id` | `gateway_id, period_start` | gateway/period, station | Derived; no source/version marker |
| `unknown_fields` | Unmapped Ecowitt fields | Ecowitt parser | Admin quality API | `id` | `field_name` | field_name | Stores sample, not all occurrences |
| `ingestion_events` | Ecowitt events/warnings | Ecowitt direct/cloud | Admin quality API | `id` | None | gateway, raw_report, station | Not a general ingestion run ledger |
| `data_sources` | Canonical ingestion source registry | Migrations/services | Ingestion traceability CLI | `id` | `code` | code, source_type | Configuration must remain non-secret |
| `ingestion_runs` | Shared run ledger | AEMET, Ecowitt Cloud, satellite, flowmeter | CLI/audits/future ops | `id` | `run_uuid` | source/started, status | Legacy rows are not backfilled yet |
| `ingestion_items` | Per item or interval status | AEMET, satellite | CLI/future diagnostics | `id` | `run_id, item_key` | run/status, external id | Not every legacy source has item granularity |
| `sync_cursors` | Durable source cursors | AEMET, Ecowitt Cloud, satellite | Sync code and CLI | `id` | `source_id, scope, scope_key` | source/scope | Only advances after successful runs |
| `source_artifacts` | Checksummed files with provenance | Satellite previews | Asset audits | `id` | None | source/role, sha256, provider external id | Current phase links new artifacts; legacy files can be reconciled later |
| `data_gaps` | Ecowitt communication gaps | Data quality service | Admin quality API | `id` | None | gateway, station | No uniqueness on same gap interval |
| `weather_stations` | External weather stations | AEMET import | Weather API/dashboard | `id` | `provider, external_id` | provider/external | Separate from `stations`; good but needs documented semantics |
| `weather_daily_observations` | AEMET daily normalized rows | AEMET import/CSV | AEMET API/dashboard/analytics | `id` | `station_id, observation_date` | station/date | Good idempotence; corrections overwrite raw payload |
| `aemet_sync_runs` | AEMET run ledger | AEMET service | API/dashboard | `id` | None | station/started, status | Exists only for AEMET, not all sources |
| `satellite_sources` | Satellite provider/source | Satellite service | Satellite API | `id` | `code` | code | Good |
| `satellite_zones` | AOIs | Satellite service | Satellite API | `id` | `slug` | slug, name, geometry_hash | Geometry changes overwrite zone by slug; old geometry not versioned |
| `satellite_observations` | Sentinel scene per AOI/product | Satellite service | API/dashboard/analytics | `id` | `source_id, zone_id, external_item_id, processing_version` | source, zone/time, quality | No ingestion run/cursor table; raw metadata in row |
| `satellite_metrics` | NDVI/NDMI/etc metrics | Satellite service | API/dashboard | `id` | `observation_id, metric_code` | observation, metric | Metrics replaced in place; transformation version only on parent |
| `satellite_assets` | Preview file references | Satellite service | Asset endpoint/dashboard | `id` | None in DB | observation, asset_type, checksum | Code upserts by observation+asset_type but DB has no UNIQUE for it |
| `argos_node_flowmeter_minutes` | Minute aggregates from controller | Startup worker/CLI | Dashboard/analytics | `id` | `node_url, window_start_utc` | node/window, window start | Upsert is app-level before insert; concurrent insert can race |
| `argos_node_flowmeter_sessions` | Closed irrigation/flow sessions | Flowmeter worker | Dashboard/analytics | `id` | `node_url, closed_at_utc` | node/closed, closed time | No source artifact or raw sample log |
| `argos_node_flowmeter_reset_events` | Annual reset audit | Flowmeter worker | Dashboard/analytics | `id` | `node_url, reset_type, administrative_year` | node/type, reset time | External reset call occurs before commit; failure after device reset can lose audit |
| `field_events` | Manual agronomic events | API/dashboard | API/dashboard/analytics | `id` | None | occurred_at, type, zone | Manual duplicates allowed; no actor/user metadata |
| `alembic_version` | Schema version | Alembic | Alembic | `version_num` | PK | PK | Good |

Observed row counts:

| Table | Rows |
|---|---:|
| `weather_daily_observations` | 5,986 |
| `ingestion_events` | 8,079 |
| `ecowitt_cloud_raw_reports` | 4,566 |
| `weather_observations` | 4,371 |
| `satellite_metrics` | 6,136 |
| `satellite_assets` | 3,067 |
| `ecowitt_raw_reports` | 1,820 |
| `satellite_observations` | 1,534 |
| `argos_node_flowmeter_minutes` | 188 |
| `data_gaps` | 8 |
| `aemet_sync_runs` | 7 |
| `field_events` | 0 |

## 6. Ingestion Map

| Source | Entry point | Frequency | Original format | Transformation | SQL destination | Files generated | Transaction | Retries | Idempotence |
|---|---|---|---|---|---|---|---|---|---|
| Ecowitt LAN | `POST /api/v1/ecowitt/upload/{token}` | Device upload interval, documented 60s | Query/form/JSON HTTP payload | `parse_ws90_payload`, normalized units, payload hash | `ecowitt_raw_reports`, `weather_observations`, events, gaps, stats | None current | One session commit after raw+normalized+quality | No app retry; device may resend | `payload_hash` unique; app duplicate check |
| Ecowitt Cloud | CLI `argos ecowitt-cloud backfill`, daily sync | Manual or daily worker | JSON API response | Cloud adapter to normalized observations | `ecowitt_cloud_raw_reports`, `weather_observations`, events, stats | None | Commit per imported observation | HTTP client behavior only; task catches errors | Cloud raw hash and timestamp duplicate check against existing weather rows |
| AEMET OpenData | CLI/API/dashboard backfill/sync | Manual, dashboard, daily worker | JSON API response through `datos` URL | `normalize_aemet_daily_records` | `weather_stations`, `weather_daily_observations`, `aemet_sync_runs` | None | Run created, then commit per interval | Client retries 429/5xx with backoff | Upsert by `station_id, observation_date` |
| AEMET CSV | CLI/API/dashboard import-csv | Manual | CSV | Same normalizer | Same AEMET tables | None | Single commit after full CSV | None | Upsert by `station_id, observation_date` |
| Satellite | CLI/API/dashboard backfill/update, daily sync | Manual or daily worker | Copernicus STAC JSON, statistics JSON, preview PNG bytes | AOI validation, stats parsing, metric normalization, quality status | `satellite_*` tables | PNG previews under `data/satellite` | Commit per scene after metrics/assets | Adapter/network only; per-item rollback on CopernicusError | Unique scene key; app-level skip/upsert |
| argos-node flowmeter | Startup worker or CLI `node capture-flowmeter-minutely` | Poll interval default 5s; row per UTC minute | JSON `/status` | Minute aggregation from pulse counters | flowmeter minute/session/reset tables | None | Commit per minute/session/reset | Poll loop retries after client/status errors | Unique minute/session/reset keys plus app upsert |
| Manual field diary | `/api/v1/field-events`, dashboard | Manual | JSON form payload | Pydantic validation/domain catalog | `field_events` | CSV export on request only | Commit per create/update/delete | None | None; duplicates allowed |
| Tests | pytest fixtures | Test execution | Synthetic HTTP/ORM data | Varies | Temporary SQLite files or in-memory DB | Temporary fixture files | Test-local | N/A | Covered for several flows |

Textual flows:

- `Ecowitt LAN -> FastAPI endpoint -> token check -> parse/normalize -> payload hash -> raw SQL -> observation SQL -> gap/stat/event SQL`
- `Ecowitt Cloud -> CLI/scheduled sync -> API client -> adapter -> raw Cloud SQL -> timestamp merge/fill -> observation SQL`
- `AEMET -> client or CSV -> normalizer -> station upsert -> daily observation upsert -> sync run update`
- `Copernicus -> STAC search -> per-scene stats -> observation upsert -> metric replacement -> preview PNG -> asset SQL`
- `argos-node -> poll /status -> minute accumulator -> flowmeter minute upsert -> session/reset audit rows`
- `Operator -> dashboard/API -> field event validation -> field_events`

## 7. Integrity, Duplication and Failure Analysis

Duplicate checks on existing data found zero rows for:

- `weather_observations` grouped by `station_uuid, gateway_id, observed_at_utc`.
- `ecowitt_raw_reports.payload_hash`.
- `ecowitt_cloud_raw_reports.payload_hash`.
- `weather_daily_observations(station_id, observation_date)`.
- `satellite_observations(source_id, zone_id, external_item_id, processing_version)`.
- `satellite_assets(observation_id, asset_type)`.
- `argos_node_flowmeter_minutes(node_url, window_start_utc)`.
- `field_events(occurred_at, event_type, title, zone_slug)`.

Specific scenarios:

- Ecowitt sends the same observation twice: exact normalized duplicate is ignored through `ecowitt_raw_reports.payload_hash`; a `DUPLICATE` ingestion event is written.
- Ecowitt same timestamp but changed values: current direct hash changes, so SQL can accept another `weather_observations` row for the same gateway/time because no natural unique exists. This is a high risk.
- Worker restarts during AEMET import: `aemet_sync_runs` remains `running` if the process dies before finalization; completed intervals are committed and reingestion upserts without duplicates.
- Same AEMET interval redownloaded: upsert overwrites corrected values and counts inserted/updated/skipped.
- Same satellite scene reprocessed: existing scene is skipped unless `force`; unique key blocks exact duplicate. With `force`, metrics and asset refs are replaced.
- Satellite file written but SQL commit fails: PNG remains without a reliable committed `satellite_assets` row. This creates orphan files.
- Satellite SQL observation committed but preview generation fails: observation/metrics can still commit with warning; asset may be absent.
- Two processes insert same row concurrently: DB unique constraints protect AEMET/satellite/flowmeter/raw hashes, but app-level select-then-insert may raise integrity errors that are not always retried as upserts.
- Source data changes later: AEMET updates in place and keeps latest raw payload; satellite `force` updates in place; Ecowitt direct changed values can create same-time duplicates.
- Time zones: code generally converts incoming datetimes to UTC using `datetime.now(UTC)`, `_ensure_utc`, `_as_utc`, or parser logic. There is a workaround for SQLite naive datetimes in Ecowitt Cloud duplicate checks, proving mixed aware/naive retrieval is a known risk.
- Floating point keys: no unique key uses floats; good.
- Invalid records: some invalid ranges raise errors; parser warnings and unknown Ecowitt fields are logged. AEMET interval errors are captured in `errors_json`; satellite warnings are returned/logged but not persisted as ingestion records.

Recommended idempotence keys:

| Source | Recommended key |
|---|---|
| Ecowitt LAN raw | `source='ecowitt_lan' + station_uuid + gateway_id + observed_at_utc + parser_version + raw payload checksum` |
| Ecowitt normalized observation | `station_uuid + gateway_id + observed_at_utc + source`, with conflict policy for changed values |
| Ecowitt Cloud raw | `provider + station_uuid + gateway alias canonical id + observed_at_utc + provider payload checksum` |
| AEMET daily | `provider='aemet' + station_external_id + observation_date` |
| Satellite scene | `source_id + zone_id + external_item_id + processing_version`, plus `geometry_hash` if geometry-version semantics require separate records |
| Satellite asset | `observation_id + asset_type` with checksum as integrity metadata |
| Flowmeter minute | `node_url + window_start_utc` |
| Flowmeter reset | `node_url + reset_type + administrative_year` |
| Field event | Leave duplicates possible, or add optional `client_request_id` for UI idempotence |

## 8. Risk Register

| Severity | Risk | Evidence | Recommended first action |
|---|---|---|---|
| Critical | No documented consistent backup/restore procedure for `var/argos.db` plus `data/satellite` | SQLite file and data artifacts are ignored; only ad hoc backup observed | Add backup script using SQLite online backup or `VACUUM INTO`, verify restore |
| High | Direct Ecowitt normalized observations lack DB natural uniqueness | `weather_observations` only unique on raw/cloud report ids | Add dedupe audit then unique constraint or conflict-safe upsert |
| High | Container rebuild can lose data if app writes inside container without mounts | Compose only defines Postgres; no app volumes for `var/`/`data/` | Document required mounts and startup checks |
| High | Satellite asset file and SQL writes are not atomic together | PNG is written before `satellite_assets` commit | Write to temp path, commit metadata, then finalize or reconcile orphan files |
| Medium | No common ingestion run table | Only AEMET has run records; Ecowitt has events; satellite has logs only | Add `data_sources`, `ingestion_runs`, `ingestion_items` |
| Medium | SQLite concurrent writer behavior not tuned | No WAL/busy timeout in engine | Enable WAL/busy timeout for SQLite or constrain workers |
| Medium | `data/weather` legacy files have unclear ownership | No current code references `data/weather` | Reconcile against SQL and classify as raw/archive/delete-candidate later |
| Medium | Timestamps may round-trip as naive through SQLite | Code handles naive candidates in one repository | Standardize serialization and add tests |
| Medium | Field events have no idempotence or actor metadata | Manual CRUD table has no unique/request id/user | Add optional `external_id/client_request_id` and audit fields later |
| Low | `celerybeat-schedule.*` files remain in root | No current Celery code found | Remove only after operator confirmation |

## 9. Role of `data/`

The proposed structure is appropriate, but should be migrated incrementally:

```text
data/
  raw/
    ecowitt/
    aemet/
    satellite/
  staging/
  processed/
  exports/
  cache/
  backups/
```

Recommended classification:

- Immutable raw evidence: provider HTTP responses that are not already preserved in SQL, AEMET original CSV seeds if legally/operationally needed, and future source artifacts.
- Regenerable processed data: dashboard CSV exports, derived summaries, satellite preview images if provider access and processing version are available.
- Cache: transient downloads, temporary STAC responses, preview files if SQL metrics are authoritative.
- SQL-only: normalized observations, station identities, ingestion runs, quality flags, manual field events, flowmeter aggregates, sync cursors.
- SQL-linked files: `source_artifacts` rows should store path, checksum, size, MIME type, provider, immutable flag, created_at, and optional ingestion_run_id.
- Never in Git: `data/**`, `var/**`, `.env`, backups containing real data or secrets.
- Retention policies needed: raw provider responses, satellite previews/cache, backups, temporary staging.

Phase 4/5 added inventory manifests, `data/weather` reconciliation, read-compatible support for old and new satellite asset paths, orphan satellite reconciliation and a dry-run/apply migration command. The real `data/` tree has been physically migrated after a verified backup and dry-run.

## 10. Target Architecture

Keep SQLite for now if ARGOS runs as a small single-node system with one API process and a small number of threads. Harden it before introducing new infrastructure:

- Configure SQLite WAL and a busy timeout.
- Use explicit transaction boundaries and conflict-handling upserts for idempotent writes.
- Add a small ingestion ledger shared across sources.
- Keep raw, normalized and derived data separate.
- Persist provider cursors/checkpoints.
- Add backup/restore scripts and tests.

Objective criteria to migrate to PostgreSQL:

- Multiple app processes or hosts writing concurrently.
- Need for remote access by services.
- SQLite lock contention appears in logs.
- Database grows beyond practical local backup/restore windows.
- Need richer operational backup, roles, or query concurrency.

Minimal recommended schema concepts:

- `data_sources`: canonical source registry (`ecowitt_lan`, `ecowitt_cloud`, `aemet_api`, `aemet_csv`, `copernicus_sentinel2`, `argos_node_flowmeter`, `manual_field_event`).
- `ingestion_runs`: source, mode, requested window, status, started/finished timestamps, code version and counts.
- `ingestion_items`: item key, status, error and row counts.
- `source_artifacts`: path, checksum, MIME, size, immutable flag, regenerable flag and optional run/item links.
- `sync_cursors`: source-specific last successful cursor/window, advanced only after successful runs.
- `data_quality_flags`: normalized quality issues linked to observations or runs.

Model recommendation: use a hybrid model. Keep typed domain tables for Ecowitt, AEMET, satellite, flowmeter and field events; add shared source/run/artifact/quality tables for traceability. Avoid a universal EAV observations table as the main storage model because ARGOS already has typed domains with different semantics and query patterns.

## 11. Backup and Recovery

To recover ARGOS completely today, copy:

- `var/argos.db` using a SQLite-consistent method.
- `data/satellite` if previews must remain available without regeneration.
- `data/aemet` and `data/weather` until classified/reconciled.
- `.env` or an external secret backup, stored separately and encrypted.
- The Git repository at or after the commit containing matching migrations.

Copying `var/argos.db` while the app writes may be inconsistent unless SQLite backup APIs, `VACUUM INTO`, or a stopped app are used. If WAL is enabled later, `-wal` and `-shm` handling must be explicit unless using the online backup API.

Minimum strategy:

- Nightly backup using SQLite online backup or `sqlite3 ".backup"`/Python sqlite backup API.
- Include a manifest with file checksums for `data/satellite` and any retained raw files.
- Retention: daily 14 days, weekly 8 weeks, monthly 12 months.
- Verify: `PRAGMA integrity_check`, row counts, Alembic version, and checksum manifest.
- Restore test monthly into a temporary path, run `alembic current`, smoke-query key endpoints using the restored DB.
- Exclude secrets from data archives; back up `.env` separately via password manager or encrypted store.

Data that can be redownloaded: AEMET public records and satellite previews/metrics if credentials, AOIs, product versions and provider availability remain stable. Irrecoverable if lost: manual field events, local-only legacy files, Ecowitt LAN raw reports, flowmeter aggregates, and any provider responses not stored elsewhere.

## 12. Required Tests

Add automated tests for:

- Reingesting identical Ecowitt LAN payload does not duplicate raw or normalized rows.
- Same Ecowitt timestamp with changed values follows an explicit conflict policy.
- Ecowitt Cloud backfill overlapping direct observations fills only missing values and does not duplicate.
- AEMET same interval reimport updates/skips deterministically.
- Satellite same scene reprocess does not duplicate observations, metrics or assets.
- Satellite preview write failure leaves a traceable failed item and no false completed run.
- Two concurrent insert attempts for each natural key do not create duplicates.
- All persisted datetimes are UTC and compare correctly after SQLite round-trip.
- Invalid records create `ingestion_items`/quality rows, not silent loss.
- Alembic migrations run against a copy of the current DB.
- Backup can restore to a temp DB and pass `PRAGMA integrity_check`.
- Deleting cache/preview files is either harmless and regenerable or reported as missing assets.

## 13. Incremental Implementation Plan

| PR | Objective | Files affected | Migrations | Compatibility | Tests | Risks | Rollback |
|---|---|---|---|---|---|---|---|
| 1 | Commit this audit and operational inventory | `docs/audits/*` | None | Full | Docs/link check | None | Revert docs |
| 2 | Add non-destructive backup script and restore docs | `scripts/backup_sqlite.py`, `docs/operations.md` | None | Full | Backup/restore temp DB test | Backup size/storage | Stop scheduled job, revert script |
| 3 | Harden SQLite engine | `database/session.py`, docs | None | Full | WAL/busy timeout test | Platform-specific pragmas | Disable pragmas |
| 4 | Add duplicate audit commands/tests | CLI/tests | None | Full | Current DB copy duplicate checks | None | Revert command |
| 5 | Add DB uniqueness/idempotent upsert for Ecowitt observations and satellite assets | Models, repos, Alembic | Yes | Requires pre-migration duplicate audit | Reingestion/concurrency tests | Migration fails if hidden duplicates | Drop new constraints after backup |
| 6 | Add shared `data_sources`, `ingestion_runs`, `ingestion_items`, `source_artifacts` | Models, migrations, services | Yes | Backfill run records optional | Failure/resume tests | More schema complexity | Revert migration before use or keep inert |
| 7 | Normalize `data/` layout with compatibility paths | Satellite service, docs, migration script | Maybe source artifact rows | Old paths remain readable | Asset path tests | Broken file links | Use compatibility resolver |
| 8 | Add scheduled backup and restore drill | Ops docs/scripts | None | Full | CI/local restore test | Disk usage | Disable schedule |
| 9 | Improve domain model where needed | Field events actor/idempotency, quality flags, cursors | Yes | Additive | API tests | UX/API changes | Feature flag or revert |
| 10 | Evaluate PostgreSQL migration only if criteria are met | Config/docs/deployment | Maybe | Requires planned cutover | Migration on copy | Operational overhead | Stay on SQLite |

## 14. Open Questions

- Is `data/weather` historical evidence that must be retained, or can it be reconciled to SQL and archived?
- Should satellite PNG previews be considered cache or part of the scientific record?
- What is the authoritative gateway identifier: MAC, model string, Ecowitt Cloud MAC, or an operator-managed device UUID?
- Does production run from this repo directory, a service, or a future app container?
- Where should backups be stored physically: local disk, NAS, cloud drive, or both?
- What retention period is required for raw provider payloads?
- Should manual field events support user identity, attachments, or edit history?
- Are AEMET corrections expected to overwrite history silently, or should previous values be versioned?

## Acceptance Answers

- Database location: `C:\Users\Fizico\Documents\github\argos\var\argos.db` for current local SQLite; optional PostgreSQL via `DATABASE_URL`.
- Container rebuild: PostgreSQL data survives with `postgres-data`; SQLite/data artifacts survive only if stored on host or mounted.
- Source of truth: SQL for normalized/queryable data; source artifacts are raw SQL JSON/text except satellite PNG previews and legacy `data/` files.
- `data/` role: currently mixed raw/legacy/cache-like artifacts; target is raw/staging/processed/exports/cache/backups with explicit retention.
- Reingestion without duplicates: AEMET/satellite/flowmeter mostly yes; Ecowitt exact duplicates yes; changed same-time Ecowitt needs DB natural key.
- Traceability: partial today; raw payloads exist for major sources, but no universal ingestion run/artifact model.
- Partial failures: AEMET records partial runs; Ecowitt has events; satellite returns/logs warnings but lacks persisted runs/errors.
- Backup: not yet robust; needs online backup, manifest, integrity check and restore drill.
- Recovery after losing main machine: possible only with Git + consistent DB backup + `data/` backup + secrets backup.
- Originals vs normalized vs derived: originals in raw SQL JSON/text and some `data/`; normalized in domain tables; derived in statistics, metrics, exports/previews.
