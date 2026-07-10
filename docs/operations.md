# ARGOS Operations

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

## Recompute Statistics

```powershell
$headers = @{ "X-ARGOS-ADMIN-TOKEN" = $env:ECOWITT_INGEST_TOKEN }

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/v1/weather/statistics/recompute?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z" `
  -Headers $headers
```

## Expected Healthy State

- `/api/v1/weather/gateway/status` returns `online: true`.
- `/api/v1/weather/latest` returns a recent `observed_at_utc`.
- `/api/v1/weather/admin/data-gaps` returns an empty list during uninterrupted operation.
- `/api/v1/weather/admin/events` contains recent `REPORT_RECEIVED` events.
