# Satellite observation

ARGOS can ingest free Sentinel-2 Level-2A vegetation information from Copernicus Data Space Ecosystem. The module treats Copernicus as an external provider behind an adapter:

```text
Copernicus Data Space Ecosystem
        -> CopernicusSatelliteAdapter
        -> SatelliteIngestionService
        -> ARGOS database
        -> ARGOS API
        -> Dashboard
```

The rest of ARGOS does not call Copernicus HTTP APIs directly.

## Account and OAuth client

Create a Copernicus Data Space account at `https://dataspace.copernicus.eu/`, then create a Sentinel Hub OAuth client in `https://shapps.dataspace.copernicus.eu/dashboard/`.

Store the client credentials only in environment variables:

```env
ARGOS_SATELLITE_ENABLED=true
COPERNICUS_CLIENT_ID=<client id>
COPERNICUS_CLIENT_SECRET=<client secret>
```

Secrets must not be committed, stored in the database, or logged.

## Configuration

The module is disabled by default. ARGOS starts normally without satellite credentials when:

```env
ARGOS_SATELLITE_ENABLED=false
```

Relevant variables:

```env
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_STAC_URL=https://stac.dataspace.copernicus.eu/v1
COPERNICUS_CATALOG_URL=https://sh.dataspace.copernicus.eu/catalog/v1
COPERNICUS_STATISTICS_URL=https://sh.dataspace.copernicus.eu/statistics/v1
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/process/v1
ARGOS_SATELLITE_AOI_GEOJSON=
ARGOS_SATELLITE_HISTORY_DAYS=730
ARGOS_SATELLITE_MAX_CLOUD_COVER=60
ARGOS_SATELLITE_MIN_VALID_PIXEL_FRACTION=0.20
ARGOS_SATELLITE_VALID_PIXEL_FRACTION=0.50
ARGOS_SATELLITE_UPDATE_INTERVAL_HOURS=24
ARGOS_SATELLITE_PREVIEW_ENABLED=true
ARGOS_SATELLITE_ASSET_DIR=data/satellite
ARGOS_SATELLITE_HTTP_TIMEOUT_SECONDS=30
```

## AOI geometry

No farm coordinates are currently stored in ARGOS. Before real ingestion, provide a WGS84 GeoJSON Polygon in `ARGOS_SATELLITE_AOI_GEOJSON`.

Example shape:

```json
{"type":"Polygon","coordinates":[[[-3.700,37.100],[-3.699,37.100],[-3.699,37.101],[-3.700,37.101],[-3.700,37.100]]]}
```

ARGOS validates that the geometry is a closed GeoJSON Polygon using lon/lat coordinates. It creates or updates a `satellite_zone` named `Finca completa` by default. The schema supports multiple zones later.

## Database

Run migrations before ingestion:

```bash
uv run alembic upgrade head
```

Satellite data is stored in:

- `satellite_sources`
- `satellite_zones`
- `satellite_observations`
- `satellite_metrics`
- `satellite_assets`

Large binary images are stored under `ARGOS_SATELLITE_ASSET_DIR`; the database stores paths, checksums, sizes, and MIME types only.

## Ingestion

Historical load:

```bash
uv run argos satellite backfill --from 2025-01-01 --to 2026-07-26
```

Incremental update:

```bash
uv run argos satellite update
```

Status:

```bash
uv run argos satellite status
```

Useful options:

```bash
uv run argos satellite backfill --dry-run
uv run argos satellite backfill --force
uv run argos satellite update --zone "Finca completa"
```

If dates are omitted for backfill, ARGOS uses the last `ARGOS_SATELLITE_HISTORY_DAYS` days. Incremental update starts from the last processed acquisition with a seven-day overlap.

There is no scheduler in the current ARGOS tree. Use cron, systemd timers, Windows Task Scheduler, or another existing orchestrator to run `uv run argos satellite update` no more than daily initially.

## API

Read endpoints:

```text
GET /api/v1/satellite/status
GET /api/v1/satellite/sources
GET /api/v1/satellite/zones
GET /api/v1/satellite/observations
GET /api/v1/satellite/observations/{id}
GET /api/v1/satellite/timeseries
GET /api/v1/satellite/latest
GET /api/v1/satellite/assets/{id}
```

Administrative endpoints require `X-Argos-Admin-Token`:

```text
POST /api/v1/satellite/update
POST /api/v1/satellite/backfill
```

Time series filters:

```text
zone_id
metric=ndvi|savi|ndre|ndmi
from
to
quality_status=valid|partial|invalid
```

## Indices

Processing version: `s2-indices-v1`.

- NDVI: vigor or relative vegetation activity.
- SAVI: vegetation index adjusted for soil influence; useful for young olive trees and bare soil.
- NDRE: chlorophyll and vegetation response at 20 m.
- NDMI: spectral indicator associated with vegetation water content or canopy moisture.

NDMI is not soil moisture and must not be interpreted as volumetric soil water.

## Quality masking

Statistics use Sentinel-2 `dataMask` and `SCL`.

Initially valid:

```text
4 Vegetation
5 Bare soil
```

Invalid:

```text
0 No data
1 Saturated or defective
3 Cloud shadows
6 Water
8 Clouds medium probability
9 Clouds high probability
10 Thin cirrus
11 Snow or ice
```

`eo:cloud_cover` is only a catalogue prefilter. ARGOS stores actual AOI quality:

- `sample_count`
- `no_data_count`
- `valid_pixel_count`
- `valid_pixel_fraction`
- `invalid_pixel_fraction`
- `quality_status`

Default quality thresholds:

- `valid`: `valid_pixel_fraction >= 0.50`
- `partial`: `0.20 <= valid_pixel_fraction < 0.50`
- `invalid`: `valid_pixel_fraction < 0.20`

## Previews

When `ARGOS_SATELLITE_PREVIEW_ENABLED=true`, ARGOS requests small PNG previews from Process API:

- `preview_rgb_png`
- `preview_ndvi_png`

These previews are visual aids only. They are not used to calculate statistics.

## Quotas

Copernicus services have quotas and processing units. ARGOS reduces usage by:

- searching STAC before processing;
- processing only new acquisitions unless `--force` is used;
- using Statistical API for metrics;
- clipping requests to the AOI;
- caching OAuth tokens in memory;
- storing results and previews.

HTTP 429 responses are retried with bounded backoff and reported as degraded/error rather than retried forever.

## Troubleshooting

- `disabled`: set `ARGOS_SATELLITE_ENABLED=true`.
- `not_configured`: provide credentials and `ARGOS_SATELLITE_AOI_GEOJSON`.
- `Geometría no definida`: the AOI is missing or invalid.
- `Credenciales no disponibles`: OAuth variables are missing.
- `Última actualización fallida`: inspect application logs and retry with `--dry-run`.

To rebuild only satellite data, delete rows from satellite tables and remove the asset directory, then run migrations and a new backfill. Preserve weather and Ecowitt tables.

## Future Sentinel-1

The schema and constants reserve:

```text
source = copernicus_sentinel_1_grd
collection = sentinel-1-grd
```

Future metrics may include VV, VH, VH/VV, and relative surface wetness. ARGOS must not expose `soil_moisture_percent` from Sentinel-1 without local calibration against soil sensors.
