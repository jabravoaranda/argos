# ARGOS

Estado: Vigente
Tipo: README tecnico
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Mantenimiento de software
Revision: 1

Agricultural Remote Gateway for Observation and Sensing.

ARGOS is being redesigned as a FastAPI-based environmental data platform. The primary Ecowitt GW2000 integration will use the gateway's Customized HTTP upload mode, preserving raw payloads and storing normalized observations in a database.

For current operational state and document navigation, start with [docs/README.md](docs/README.md) and [docs/00-estado-del-proyecto.md](docs/00-estado-del-proyecto.md).

The canonical station identity is the physical site slug `tomillar`. Gateway hardware identifiers such as MAC address, serial number, model or Ecowitt-specific IDs are treated as hardware metadata associated with that station, so the gateway can be replaced without changing the station identity.

## Current Scope

This branch contains the current ARGOS redesign work: FastAPI foundation, direct Ecowitt ingestion, AEMET, Sentinel-2, API analytics, Streamlit dashboard, argos-node valve/flowmeter integration and Ecowitt Cloud backfill support.

Included:

- Python project managed with `uv` and `pyproject.toml`.
- FastAPI application entrypoint.
- Environment-based configuration.
- SQLAlchemy 2.x models.
- Alembic migrations.
- Stable station identity with UUID primary key and unique slug `tomillar`.
- SQLite for local development.
- PostgreSQL-compatible schema and Docker Compose service.
- Basic health endpoints.
- Ruff, mypy and pytest configuration through project dependencies.
- Ecowitt Customized upload endpoint for direct GW2000A capture.
- Raw payload persistence.
- WS90 parser based on a real GW2000A firmware 3.3.2 payload.
- Normalized weather observation persistence.
- Duplicate detection.
- Unknown field catalogue for captured fields without normalized mapping.
- Persisted daily and weekly weather summaries.
- Streamlit dashboard backed by the FastAPI API.
- Ecowitt Cloud history client, adapter and initial backfill persistence.
- Field diary for manual agronomic events.
- Unified analytics API and dashboard section for correlations, distributions and trend references.

Still not declared operational:

- Autonomous irrigation.
- Unattended irrigation scheduling.
- Field-validated automatic valve safety shutdown.

## Installation

```powershell
uv sync
Copy-Item .env.example .env
```

Edit `.env` and set a real ingestion token:

```dotenv
ECOWITT_INGEST_TOKEN=replace-with-a-random-token
ARGOS_ADMIN_TOKEN=replace-with-an-admin-token
```

For local development the default database is SQLite:

```dotenv
DATABASE_URL=sqlite:///./var/argos.db
```

## Database

Apply migrations:

```powershell
uv run alembic upgrade head
```

To use PostgreSQL locally with Docker Desktop:

```powershell
docker compose up -d postgres
```

Then set:

```dotenv
DATABASE_URL=postgresql+psycopg://argos:argos@localhost:5432/argos
```

and run:

```powershell
uv run alembic upgrade head
```

## Run the API

```powershell
uv run uvicorn argos.main:app --host 0.0.0.0 --port 8080
```

Open:

```text
http://localhost:8080/health
http://localhost:8080/ready
http://localhost:8080/docs
```

Useful weather API endpoints:

```text
GET /api/v1/weather/latest
GET /api/v1/weather/station
GET /api/v1/weather/station/hardware
GET /api/v1/weather/observations?from=2026-07-10T00:00:00Z&to=2026-07-10T23:59:59Z
GET /api/v1/weather/summary/daily?from=2026-07-10T00:00:00Z&to=2026-07-10T23:59:59Z
GET /api/v1/weather/summary/weekly?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z
GET /api/v1/weather/gateway/status
POST /api/v1/weather/statistics/recompute?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z
GET /api/v1/weather/admin/raw-reports
GET /api/v1/weather/admin/events
GET /api/v1/weather/admin/unknown-fields
GET /api/v1/weather/admin/data-gaps
GET /api/v1/field-events
POST /api/v1/field-events
GET /api/v1/field-events/export.csv
GET /api/v1/analytics/variables
POST /api/v1/analytics/series
POST /api/v1/analytics/correlation
POST /api/v1/analytics/correlation-matrix
POST /api/v1/analytics/distribution
POST /api/v1/analytics/trend
```

The gateway status endpoint reports the latest gateway seen by ARGOS and marks it offline when the last report is older than `ECOWITT_OFFLINE_AFTER_SECONDS`.

Local operator diagnostic:

```powershell
uv run argos ecowitt status
```

Daily and weekly summaries are persisted in `daily_statistics` and `weekly_statistics`. New Ecowitt observations update the affected day and ISO week automatically. The recompute endpoint is idempotent and can be used after migrations or historical imports.

ARGOS detects gaps when consecutive observations for the same gateway are farther apart than twice `ECOWITT_EXPECTED_INTERVAL_SECONDS`. Gaps are stored in `data_gaps` and exposed through the admin API. Admin endpoints and statistics recomputation require the `X-ARGOS-ADMIN-TOKEN` header with the value of `ARGOS_ADMIN_TOKEN`.

See [docs/operations.md](docs/operations.md) for operational checks, [docs/field-diary.md](docs/field-diary.md) for field diary usage and [docs/analytics.md](docs/analytics.md) for the analytics API and dashboard contract.

## Quality Checks

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
```

## Dashboard

Run the local dashboard:

```powershell
uv run streamlit run src/argos/dashboard/app.py
```

Open:

```text
http://localhost:8501
```

The dashboard reads from the FastAPI backend. Start the API first:

```powershell
uv run uvicorn argos.main:app --host 0.0.0.0 --port 8080
```

Dashboard views:

- Inicio: compact station identity, API/gateway state, latest communication, hardware and current weather cards.
- Observaciones: interactive time-series chart and downloadable observation table, with source filtering for `DIRECT` and `BACKFILLED` observations.
- Resúmenes: daily and weekly API summaries plus monthly, seasonal and annual aggregates derived from daily statistics.
- Análisis: cross-source correlations, distributions, aligned series and trend/reference diagnostics over already persisted data.
- Diario de campo: manual agronomic events that can be overlaid in analysis views.
- Actualizar datos: manual historical backfill tools for Ecowitt, AEMET and satellite sources.
- AEMET: stored official daily observations, selected-variable charts and admin-token-protected import/sync actions.
- Satélite: Sentinel-2 index charts, quality filtering, compact coverage metadata and Copernicus update/backfill actions.
- Válvulas: local argos-node valve controls and timing diagnostics.
- Calidad: data gaps, ingestion events, unknown fields and recent raw reports. This view requires the admin token.

## Ecowitt Cloud Backfill

Direct GW2000 Customized ingestion is the primary data source. Ecowitt Cloud is reserved for historical recovery and consistency checks.

Configure Cloud credentials only when backfill is needed:

```dotenv
ECOWITT_CLOUD_APPLICATION_KEY=...
ECOWITT_CLOUD_API_KEY=...
ECOWITT_CLOUD_MAC=...
ECOWITT_CLOUD_MAX_BACKFILL_HOURS=24
```

The current backfill phase includes:

- A tested client for Ecowitt Cloud history requests.
- Separate persistence for Ecowitt Cloud raw payloads in `ecowitt_cloud_raw_reports`.
- `weather_observations.source` to distinguish `DIRECT` and `BACKFILLED` readings.
- Timestamp deduplication so Cloud imports do not duplicate direct LAN observations.
- Bounded manual ranges through `ECOWITT_CLOUD_MAX_BACKFILL_HOURS`.
- Internal manual CLI backfill through `uv run argos ecowitt-cloud backfill`.

The response adapter is implemented conservatively. A real target-station Cloud payload is still needed before treating Cloud backfill as routine operation.

Example manual backfill command:

```powershell
uv run argos ecowitt-cloud backfill `
  --start 2026-07-10T00:00:00Z `
  --end 2026-07-10T01:00:00Z `
  --gateway-identifier GW2000A `
  --station-type GW2000A_V3.3.2 `
  --cloud-mac AABBCCDDEEFF
```

## GW2000 Configuration

Configure the GW2000 Customized service with:

```text
Protocol Type: Ecowitt
Server Hostname: <ARGOS_HOST>
Port: 8080
Path: /api/v1/ecowitt/upload/<ECOWITT_INGEST_TOKEN>
Upload Interval: 60 seconds
```

The receiver captures the raw request body, stores the parsed key/value payload and creates a normalized weather observation for the confirmed GW2000A firmware 3.3.2 + WS90 field set.

Currently mapped fields:

```text
tempinf
humidityin
baromrelin
baromabsin
tempf
humidity
vpd
winddir
windspeedmph
windgustmph
maxdailygust
solarradiation
uv
rrain_piezo
erain_piezo
hrain_piezo
last24hrain_piezo
drain_piezo
wrain_piezo
mrain_piezo
yrain_piezo
wh90batt
winddir_avg10m
ws90cap_volt
srain_piezo
```

Captured but not normalized yet:

```text
```
