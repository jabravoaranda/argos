# Health checks operativos

Estado: Vigente
Tipo: Manual operativo
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-15
Responsable logico: Operador ARGOS
Revision: 2

## Objetivo

Responder en menos de dos minutos: ARGOS esta funcionando?

No existe un health check unificado; usar estas comprobaciones separadas.

## Comprobacion rapida

```powershell
Set-Location "C:\Users\Fizico\Documents\github\argos"
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/latest
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/gateway/status
Invoke-RestMethod http://127.0.0.1:8080/api/v1/weather/aemet/sync/latest?station=6127X
Invoke-RestMethod http://127.0.0.1:8080/api/v1/satellite/status
Invoke-RestMethod http://192.168.1.42/status
Invoke-RestMethod http://192.168.1.42/valves
uv run argos data audit-source-artifacts
```

## Criterios

| Comprobacion | OK | Warning | Critical |
|---|---|---|---|
| `/health` | HTTP 200 y `status=ok` | Lento pero responde | No responde |
| Dashboard | HTTP 200 en `8501` | Carga lenta | No responde |
| Base de datos | `PRAGMA integrity_check=ok` | WAL/shm persistentes tras parada | Integridad distinta de `ok` |
| Ultima Ecowitt | Observacion reciente segun operacion esperada | Gateway offline por umbral pero datos historicos accesibles | Sin observaciones o errores SQL |
| Gateway | `/api/v1/weather/gateway/status` responde | `online=false` por retraso | Endpoint caido |
| AEMET | `/aemet/sync/latest` responde | Sync antiguo o sin credencial | Error critico persistente |
| Satelite | `/api/v1/satellite/status` responde | Ultima adquisicion antigua por disponibilidad Copernicus | Error de API o assets faltantes |
| Ultima ingesta | `ingestion_runs` sin fallos recientes bloqueantes | Warnings conocidos | Runs fallidos repetidos |
| Cursores | `uv run argos data show-sync-cursors` ejecuta | Cursores antiguos | Comando falla |
| `argos-node` | `/status` responde | Respuesta incompleta de caudalimetro | Timeout o HTTP error |
| Electroválvulas | `/valves` lista General EV8, Sector I EV6 y Sector II EV7 | Alguna aparece en estado inesperado | No responde o falta una electroválvula configurada |
| Caudalimetro | Minutos recientes si worker activo | Sin sesiones cerradas observadas | Caudal inesperado con valvula cerrada |
| Ultimo backup | Backup reciente verificado | Backup solo local | Sin backup valido |
| Espacio en disco | Espacio suficiente para DB + `data` + backup | Menos de 2x DB libre | Sin espacio para escribir DB/WAL |

## Comandos de base y ultimas filas

```powershell
@'
import sqlite3
conn=sqlite3.connect('var/argos.db')
cur=conn.cursor()
print(cur.execute('pragma integrity_check').fetchone()[0])
print(cur.execute('select version_num from alembic_version').fetchone()[0])
print(cur.execute('select count(*), max(observed_at_utc) from weather_observations').fetchone())
print(cur.execute('select count(*), max(observation_date) from weather_daily_observations').fetchone())
print(cur.execute('select count(*), max(acquisition_time) from satellite_observations').fetchone())
print(cur.execute('select count(*), max(window_start_utc) from argos_node_flowmeter_minutes').fetchone())
conn.close()
'@ | python -
```

## Backups y disco

```powershell
Get-ChildItem var/manual-backups -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name,Length,LastWriteTime
Get-PSDrive -PSProvider FileSystem
```

## Estado observado el 2026-08-02

- `/health`: 200.
- Dashboard: 200.
- `argos-node /status`: 200.
- Electroválvula observada entonces: `GET /valves/8` respondio `closed`; configuracion actual ampliada a General EV8, Sector I EV6 y Sector II EV7.
- SQLite integrity: `ok`.
- Ecowitt: 4.560 observaciones; ultima `2026-08-02 18:20:00 UTC`.
- AEMET: 5.986 observaciones; ultima fecha `2026-07-30`.
- Satelite: 1.534 observaciones; ultima adquisicion `2026-07-31 11:11:09.767000 UTC`.
- Caudalimetro: 218 minutos agregados; ultima ventana `2026-08-02 18:55:00 UTC`.
