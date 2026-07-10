# ARGOS Operations

## Station Identity

The stable station slug is:

```text
tomillar
```

This identifies the physical site. The GW2000 gateway is replaceable hardware associated with the station. Do not use the gateway MAC address or model name as the station identity.

## Start Local API

```powershell
uv run alembic upgrade head
uv run uvicorn argos.main:app --host 0.0.0.0 --port 8080
```

For background execution on Windows:

```powershell
Start-Process -FilePath "uv" -ArgumentList @("run", "uvicorn", "argos.main:app", "--host", "0.0.0.0", "--port", "8080") -WorkingDirectory "C:\Users\Fizico\Documents\github\argos" -WindowStyle Hidden
```

## GW2000 Customized Settings

```text
Protocol Type: Ecowitt
Server Hostname: <ARGOS_HOST>
Port: 8080
Path: /api/v1/ecowitt/upload/<ECOWITT_INGEST_TOKEN>
Upload Interval: 60 seconds
```

## Verify Reception

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/station
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/station/hardware
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/gateway/status
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/latest
```

## Admin Inspection

Admin endpoints require:

```text
X-ARGOS-ADMIN-TOKEN: <ECOWITT_INGEST_TOKEN>
```

Examples:

```powershell
$headers = @{ "X-ARGOS-ADMIN-TOKEN" = $env:ECOWITT_INGEST_TOKEN }

Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/admin/raw-reports?limit=3 -Headers $headers
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/admin/events?limit=10 -Headers $headers
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/admin/unknown-fields -Headers $headers
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/admin/data-gaps -Headers $headers
```

Raw reports are preserved complete in the database for scientific traceability. Diagnostic API responses redact sensitive values such as `PASSKEY`, tokens, authorization headers and cookies.

## Recompute Statistics

```powershell
$headers = @{ "X-ARGOS-ADMIN-TOKEN" = $env:ECOWITT_INGEST_TOKEN }

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/weather/statistics/recompute?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z" `
  -Headers $headers
```

## Ecowitt Cloud Backfill Status

The current implementation can:

- request history data through the Ecowitt Cloud client;
- parse supported history series into normalized weather values when units are explicit;
- preserve Cloud raw payloads separately from LAN raw reports;
- import observations as `BACKFILLED`;
- avoid duplicating existing direct LAN observations for the same gateway and timestamp.
- deduplicate Cloud raw payloads after resolving gateway aliases, so the same hardware is not duplicated when it is referenced by model name, LAN identifier or Cloud MAC.

Backfill is not exposed as an HTTP endpoint yet. Keep it internal until a real Cloud history payload from the target station has been captured and verified.

Manual CLI backfill:

```powershell
uv run argos ecowitt-cloud backfill `
  --start 2026-07-10T00:00:00Z `
  --end 2026-07-10T01:00:00Z `
  --gateway-identifier GW2000A `
  --station-type GW2000A_V3.3.2 `
  --cloud-mac AABBCCDDEEFF
```

The command requires Ecowitt Cloud credentials in `.env`:

```dotenv
ECOWITT_CLOUD_APPLICATION_KEY=...
ECOWITT_CLOUD_API_KEY=...
ECOWITT_CLOUD_MAC=...
```

Pending decisions for operator review:

- canonical gateway identity: `model`, LAN identifier, Cloud MAC, or a promoted gateway alias;
- whether backfill should be triggered by CLI, admin HTTP endpoint, or both;
- whether Cloud imports may fill missing fields in an existing `DIRECT` observation;
- confirmed Cloud history payload shape and units for GW2000A firmware 3.3.2 with WS90.

## Expected Healthy State

- `/api/v1/weather/gateway/status` returns `online: true`.
- `/api/v1/weather/station` returns `slug: tomillar`.
- `/api/v1/weather/station/hardware` lists the current GW2000 hardware associated with `tomillar`.
- `/api/v1/weather/latest` returns a recent `observed_at_utc`.
- `/api/v1/weather/admin/data-gaps` returns an empty list during uninterrupted operation.
- `/api/v1/weather/admin/events` contains recent `REPORT_RECEIVED` events.
