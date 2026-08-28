# Topologia runtime de ARGOS

Estado: Vigente
Tipo: Diagrama operativo
Fuente de verdad: codigo y procesos observados
Ultima actualizacion: 2026-08-15
Responsable logico: Mantenimiento de software
Revision: 2

Solo se dibujan componentes confirmados por codigo, configuracion o ejecucion observada.

```mermaid
flowchart LR
    subgraph pc["PC Windows"]
        streamlit["Streamlit dashboard<br/>127.0.0.1:8501"]
        fastapi["FastAPI uvicorn<br/>127.0.0.1:8080"]
        sqlite["SQLite<br/>var/argos.db"]
        data["data/<br/>raw / processed / legacy"]
        worker_flow["Worker interno<br/>argos-node-flowmeter-capture"]
        worker_sync["Worker interno<br/>argos-daily-data-sync"]
        backup["Scripts backup SQLite<br/>manual o tarea Windows no confirmada"]
    end

    ecowitt["Ecowitt GW2000<br/>Customized upload"]
    ecowitt_cloud["Ecowitt Cloud<br/>history API"]
    aemet["AEMET OpenData"]
    copernicus["Copernicus CDSE"]
    node["argos-node<br/>http://192.168.1.42"]
    valves["Electroválvulas<br/>EV físicas configuradas por sector"]
    flowmeter["Caudalimetro"]

    ecowitt -->|"POST /api/v1/ecowitt/upload/{token}"| fastapi
    fastapi <-->|"SQL reads/writes"| sqlite
    fastapi <-->|"file metadata/assets"| data
    streamlit -->|"HTTP API"| fastapi
    streamlit -->|"Sector -> EV en settings; GET /status, GET /valves, POST /valves/<id>"| node
    node --> valves
    flowmeter --> node
    worker_flow -->|"poll /status cada 5s si ARGOS_NODE_URL"| node
    worker_flow --> sqlite
    worker_sync -->|"AEMET sync si habilitado"| aemet
    worker_sync -->|"Cloud backfill/sync si credenciales"| ecowitt_cloud
    worker_sync --> copernicus
    worker_sync --> sqlite
    worker_sync --> data
    fastapi -->|"admin sync/backfill"| aemet
    fastapi -->|"admin update/backfill"| copernicus
    backup --> sqlite
```

## Notas

- La operacion de electroválvulas del dashboard habla directamente con `argos-node`; no pasa por FastAPI.
- La tarea Windows de backup no se dibuja como activa porque su registro no esta confirmado.
- La alimentacion fisica del controlador y la conexion electrica de las electroválvulas son Pendiente de validacion operativa.
