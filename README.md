# ARGOS

Agricultural Remote Gateway for Observation and Sensing.

ARGOS is being redesigned as a FastAPI-based environmental data platform. The primary Ecowitt GW2000 integration will use the gateway's Customized HTTP upload mode, preserving raw payloads and storing normalized observations in a database.

## Current Scope

This branch contains Epic 1: the clean FastAPI and database foundation.

Included:

- Python project managed with `uv` and `pyproject.toml`.
- FastAPI application entrypoint.
- Environment-based configuration.
- SQLAlchemy 2.x models.
- Alembic migrations.
- SQLite for local development.
- PostgreSQL-compatible schema and Docker Compose service.
- Basic health endpoints.
- Ruff, mypy and pytest configuration through project dependencies.

Included in the current implementation:

- Ecowitt Customized upload endpoint for direct GW2000A capture.
- Raw payload persistence.
- WS90 parser based on a real GW2000A firmware 3.3.2 payload.
- Normalized weather observation persistence.
- Duplicate detection.
- Unknown field catalogue for captured fields without normalized mapping.

Still not included:

- Dashboard.
- Historical backfill.

## Installation

```powershell
uv sync
Copy-Item .env.example .env
```

Edit `.env` and set a real ingestion token:

```dotenv
ECOWITT_INGEST_TOKEN=replace-with-a-random-token
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
GET /api/v1/weather/observations?from=2026-07-10T00:00:00Z&to=2026-07-10T23:59:59Z
GET /api/v1/weather/summary/daily?from=2026-07-10T00:00:00Z&to=2026-07-10T23:59:59Z
GET /api/v1/weather/summary/weekly?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z
POST /api/v1/weather/statistics/recompute?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z
GET /api/v1/weather/gateway/status
```

The gateway status endpoint reports the latest gateway seen by ARGOS and marks it offline when the last report is older than `ECOWITT_OFFLINE_AFTER_SECONDS`.

Daily and weekly summaries are persisted in `daily_statistics` and `weekly_statistics`. New Ecowitt observations update the affected day and ISO week automatically. The recompute endpoint is idempotent and can be used after migrations or historical imports.

## Quality Checks

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
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
