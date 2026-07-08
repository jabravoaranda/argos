# ARGOS

Agricultural Remote Gateway for Observation and Sensing.

## Instalacion

El proyecto usa `uv` para crear el entorno, instalar dependencias y ejecutar comandos.

```powershell
uv venv
uv sync
```

Tambien se incluye `requirements.txt` para documentar las dependencias principales.

## Configuracion de la IP

Configura la IP LAN del Ecowitt GW2000 con `.env`:

```powershell
Copy-Item .env.example .env
```

```dotenv
ECOWITT_GW2000_IP=192.168.1.137
ECOWITT_TIMEOUT_SECONDS=10
ECOWITT_INTERVAL_SECONDS=60
ARGOS_WEATHER_DATA_DIR=data/weather
ARGOS_BROKER_URL=redis://localhost:6379/0
ARGOS_RESULT_BACKEND=redis://localhost:6379/0
ARGOS_TIMEZONE=Europe/Madrid
```

O con `config.yaml`:

```powershell
Copy-Item config.yaml.example config.yaml
```

```yaml
ecowitt:
  gw2000_ip: 192.168.1.137
  timeout_seconds: 10
  interval_seconds: 60
  data_dir: data/weather
```

El modulo consulta:

```text
http://<GW2000_IP>/get_livedata_info
```

## Ejecucion manual

Una sola lectura:

```powershell
uv run python -m argos.weather.ecowitt
```

Worker continuo, una lectura cada `ECOWITT_INTERVAL_SECONDS` segundos:

```powershell
uv run python -m argos.weather.ecowitt --worker
```

Worker con Celery y Redis en Windows. Abre una terminal para el worker:

```powershell
uv run celery -A argos.worker.celery_app:app worker --loglevel=info --pool=solo
```

Y otra terminal para Celery Beat, que lanza la tarea periodica:

```powershell
uv run celery -A argos.worker.celery_app:app beat --loglevel=info
```

En Linux se puede ejecutar worker y Beat en el mismo proceso:

```bash
uv run celery -A argos.worker.celery_app:app worker --beat --loglevel=info
```

Este modo necesita un Redis accesible en `ARGOS_BROKER_URL`. Docker no es obligatorio; basta con que Redis este ejecutandose en la maquina o en la red.

Con Docker Desktop, levanta Redis asi:

```powershell
docker compose up -d redis
```

Comprueba que responde:

```powershell
docker compose exec redis redis-cli ping
```

Debe devolver:

```text
PONG
```

Panel web con Flower:

```powershell
uv run celery -A argos.worker.celery_app:app flower --port=5555
```

Despues abre:

```text
http://localhost:5555
```

Flower permite ver workers, tareas registradas, tareas ejecutadas y estado de la cola Celery. Redis sigue siendo el broker; Flower no sustituye a Redis ni es un editor general de claves Redis.

Cada ejecucion guarda una fila en el CSV diario:

```text
data/weather/YYYY/YYYY-MM-DD.csv
```

Tambien guarda el JSON bruto en:

```text
data/weather/raw/YYYY/YYYY-MM-DD/
```

## Cron cada minuto

Si prefieres no dejar un worker vivo, tambien puedes programar una ejecucion por minuto con cron en Linux:

```cron
* * * * * cd /ruta/a/argos && /usr/bin/env uv run python -m argos.weather.ecowitt >> logs/ecowitt.log 2>&1
```

## Tests

```powershell
uv run pytest
```

## Dashboard local

La primera interfaz web de ARGOS usa Streamlit, Pandas y Plotly para visualizar los CSV meteorologicos guardados en `data/weather`.

Ejecuta:

```powershell
uv run streamlit run argos/dashboard/app.py
```

La app combina automaticamente todos los CSV diarios disponibles en:

```text
data/weather/YYYY/YYYY-MM-DD.csv
```

Incluye vistas diaria, semanal, mensual, anual y tendencias, con graficos interactivos, filtros de fecha, seleccion de variables y descarga de tablas resumen en CSV.
