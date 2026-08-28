# Referencia de configuracion

Estado: Vigente
Tipo: Referencia operativa
Fuente de verdad: `src/argos/config/settings.py`
Ultima actualizacion: 2026-08-15
Responsable logico: Mantenimiento de software
Revision: 2

No copiar secretos reales en documentacion, issues ni commits.

| Variable | Modulo | Obligatoria | Default | Secreto | Ejemplo seguro | Descripcion |
|---|---:|---:|---|---:|---|---|
| `APP_ENV` | app | No | `development` | No | `development` | Entorno logico. |
| `DATABASE_URL` | DB | No | `sqlite:///./var/argos.db` | No | `sqlite:///./var/argos.db` | URL SQLAlchemy. |
| `SQLITE_BUSY_TIMEOUT_MS` | DB | No | `5000` | No | `5000` | Timeout SQLite en ms. |
| `LOCAL_TIMEZONE` | app | No | `Europe/Madrid` | No | `Europe/Madrid` | Zona local. |
| `LOG_LEVEL` | logs | No | `INFO` | No | `INFO` | Nivel de logging. |
| `STATION_SLUG` | Ecowitt | No | `tomillar` | No | `tomillar` | Identidad de estacion fisica. |
| `ARGOS_ADMIN_TOKEN` | seguridad | Si | ninguno | Si | `change-me-long-random` | Token para endpoints admin. |
| `ECOWITT_INGEST_TOKEN` | Ecowitt LAN | Si | ninguno | Si | `change-me-long-random` | Token de subida Customized. |
| `ECOWITT_CAPTURE_RAW` | Ecowitt LAN | No | `false` | No | `true` | Conserva payloads raw LAN. |
| `ECOWITT_EXPECTED_INTERVAL_SECONDS` | Ecowitt LAN | No | `60` | No | `60` | Intervalo esperado para gaps. |
| `ECOWITT_OFFLINE_AFTER_SECONDS` | Ecowitt LAN | No | `180` | No | `180` | Umbral offline del gateway. |
| `ECOWITT_CLOUD_BASE_URL` | Ecowitt Cloud | No | `https://api.ecowitt.net` | No | default | Base API Cloud. |
| `ECOWITT_CLOUD_API_VERSION` | Ecowitt Cloud | No | `v3` | No | `v3` | Version API Cloud. |
| `ECOWITT_CLOUD_APPLICATION_KEY` | Ecowitt Cloud | No | `None` | Si | `<set>` | Credencial Cloud. |
| `ECOWITT_CLOUD_API_KEY` | Ecowitt Cloud | No | `None` | Si | `<set>` | Credencial Cloud. |
| `ECOWITT_CLOUD_MAC` | Ecowitt Cloud | No | `None` | Parcial | `AABBCCDDEEFF` | MAC Cloud del gateway. |
| `ECOWITT_CLOUD_TIMEOUT_SECONDS` | Ecowitt Cloud | No | `10` | No | `10` | Timeout HTTP. |
| `ECOWITT_CLOUD_MAX_BACKFILL_HOURS` | Ecowitt Cloud | No | `24` | No | `24` | Ventana maxima backfill. |
| `ARGOS_SATELLITE_ENABLED` | Satelite | No | `false` | No | `true` | Habilita ingesta Copernicus. |
| `ARGOS_SATELLITE_AOIS_JSON` | Satelite | No | `None` | No | `{...}` | AOIs GeoJSON en una linea. |
| `COPERNICUS_CLIENT_ID` | Satelite | No | `None` | Parcial | `<client-id>` | OAuth client id. |
| `COPERNICUS_CLIENT_SECRET` | Satelite | No | `None` | Si | `<set>` | OAuth secret. |
| `COPERNICUS_TOKEN_URL` | Satelite | No | CDSE token URL | No | default | Endpoint token. |
| `COPERNICUS_STAC_URL` | Satelite | No | CDSE STAC URL | No | default | Endpoint STAC. |
| `COPERNICUS_CATALOG_URL` | Satelite | No | Sentinel Hub catalog URL | No | default | Endpoint catalog. |
| `COPERNICUS_STATISTICS_URL` | Satelite | No | Sentinel Hub statistics URL | No | default | Endpoint estadisticas. |
| `COPERNICUS_PROCESS_URL` | Satelite | No | Sentinel Hub process URL | No | default | Endpoint previews. |
| `ARGOS_SATELLITE_HISTORY_DAYS` | Satelite | No | `730` | No | `730` | Rango historico por defecto. |
| `ARGOS_SATELLITE_MAX_CLOUD_COVER` | Satelite | No | `60.0` | No | `60` | Filtro nubosidad. |
| `ARGOS_SATELLITE_MIN_VALID_PIXEL_FRACTION` | Satelite | No | `0.20` | No | `0.20` | Umbral minimo parcial. |
| `ARGOS_SATELLITE_VALID_PIXEL_FRACTION` | Satelite | No | `0.50` | No | `0.50` | Umbral valido. |
| `ARGOS_SATELLITE_UPDATE_INTERVAL_HOURS` | Satelite | No | `24` | No | `24` | Cadencia recomendada. |
| `ARGOS_SATELLITE_PREVIEW_ENABLED` | Satelite | No | `true` | No | `true` | Genera previews PNG. |
| `ARGOS_SATELLITE_ASSET_DIR` | Satelite | No | `None` | No | no usar salvo compatibilidad | Variable legacy-compatible; el layout actual usa `ARGOS_PROCESSED_DIR` derivado de `ARGOS_DATA_DIR`. |
| `ARGOS_SATELLITE_HTTP_TIMEOUT_SECONDS` | Satelite | No | `30` | No | `30` | Timeout assets/previews. |
| `ARGOS_DATA_DIR` | Datos | No | `data` | No | `data` | Raiz de datos. |
| `ARGOS_RAW_DIR` | Datos | No | `None` | No | `data/raw` | Override de raw. |
| `ARGOS_STAGING_DIR` | Datos | No | `None` | No | `data/staging` | Override de staging. |
| `ARGOS_PROCESSED_DIR` | Datos | No | `None` | No | `data/processed` | Override de processed. |
| `ARGOS_EXPORTS_DIR` | Datos | No | `None` | No | `data/exports` | Override de exports. |
| `ARGOS_CACHE_DIR` | Datos | No | `None` | No | `data/cache` | Override de cache. |
| `ARGOS_LEGACY_DIR` | Datos | No | `None` | No | `data/legacy` | Override de legacy. |
| `ARGOS_QUARANTINE_DIR` | Datos | No | `None` | No | `data/quarantine` | Override de quarantine. |
| `AEMET_API_KEY` | AEMET | No | `None` | Si | `<set>` | API key AEMET. |
| `AEMET_STATION_ID` | AEMET | No | `6127X` | No | `6127X` | Estacion AEMET. |
| `AEMET_BASE_URL` | AEMET | No | `https://opendata.aemet.es/opendata/api` | No | default | Base OpenData. |
| `AEMET_TIMEOUT_SECONDS` | AEMET | No | `20` | No | `20` | Timeout HTTP. |
| `AEMET_MAX_RETRIES` | AEMET | No | `3` | No | `3` | Reintentos. |
| `AEMET_BACKOFF_SECONDS` | AEMET | No | `0.5` | No | `0.5` | Backoff base. |
| `AEMET_BLOCK_DAYS` | AEMET | No | `31` | No | `31` | Bloque de backfill. |
| `AEMET_SYNC_LOOKBACK_DAYS` | AEMET | No | `7` | No | `7` | Ventana sync. |
| `AEMET_BACKFILL_START_DATE` | AEMET | No | `1900-01-01` | No | `1900-01-01` | Inicio backfill por defecto. |
| `AEMET_SEED_CSV_PATH` | AEMET | No | `None` | No | `data/raw/aemet/6127X.csv` | Ruta CSV local. |
| `ARGOS_NODE_URL` | argos-node | No | `None` | No | `http://192.168.1.42` | URL controlador. |
| `ARGOS_NODE_TIMEOUT_SECONDS` | argos-node | No | `5` | No | `5` | Timeout controlador. |
| `ARGOS_NODE_POLL_INTERVAL_SECONDS` | argos-node | No | `5.0` | No | `5.0` | Poll caudalimetro. |
| `ARGOS_IRRIGATION_MAIN_EV` | Riego | No | `8` | No | `8` | EV principal que debe abrirse antes de cualquier sector. |
| `ARGOS_IRRIGATION_SECTOR_I_EV` | Riego | Si para operar sectores | `None` | No | `7` | EV fisica que acciona el Sector I. |
| `ARGOS_IRRIGATION_SECTOR_II_EV` | Riego | Si para operar sectores | `None` | No | `6` | EV fisica que acciona el Sector II. |
| `ARGOS_IRRIGATION_SECTOR_III_EV` | Riego | Si para operar sectores | `None` | No | `6` | EV fisica que acciona el Sector III. |
| `ARGOS_IRRIGATION_SECTOR_IV_EV` | Riego | Si para operar sectores | `None` | No | `6` | EV fisica que acciona el Sector IV. |
| `ARGOS_FLOWMETER_HYDROLOGICAL_YEAR_RESET_MONTH` | Caudalimetro | No | `10` | No | `10` | Mes reset anual. |
| `ARGOS_FLOWMETER_HYDROLOGICAL_YEAR_RESET_DAY` | Caudalimetro | No | `1` | No | `1` | Dia reset anual. |
| `ARGOS_DAILY_SYNC_ENABLED` | Scheduling | No | `true` | No | `true` | Worker diario interno. |
| `ARGOS_DAILY_SYNC_INTERVAL_HOURS` | Scheduling | No | `24.0` | No | `24` | Intervalo worker diario. |
| `ECOWITT_CLOUD_SYNC_LOOKBACK_HOURS` | Scheduling | No | `24` | No | `24` | Lookback sync Cloud. |
| `ARGOS_BACKUP_DIR` | Backups | No | no definido en settings | No | `D:\ARGOS Backups\sqlite` | Usado por scripts de backup, no por `Settings`. |

## Sectores de riego configurados

La operacion normal del dashboard trabaja con una EV principal y sectores logicos I, II, III y IV. La resolucion sector -> EV se carga desde `.env` mediante `argos.config.irrigation`; no debe duplicarse en UI, servicios ni endpoints. Abrir un sector desde ARGOS abre primero la EV principal; la EV principal tambien puede abrirse de forma independiente sin abrir sectores.

| Control logico | Variable de entorno | EV actual de instalacion |
|---|---|---:|
| Principal | `ARGOS_IRRIGATION_MAIN_EV` | 8 |
| Sector I | `ARGOS_IRRIGATION_SECTOR_I_EV` | 7 |
| Sector II | `ARGOS_IRRIGATION_SECTOR_II_EV` | 6 |
| Sector III | `ARGOS_IRRIGATION_SECTOR_III_EV` | 6 |
| Sector IV | `ARGOS_IRRIGATION_SECTOR_IV_EV` | 6 |
