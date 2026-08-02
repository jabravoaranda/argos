# Arranque y parada de ARGOS

Estado: Vigente
Tipo: Manual operativo
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Operador ARGOS
Revision: 1

## Topologia real observada

- Directorio: `C:\Users\Fizico\Documents\github\argos`.
- API FastAPI: `uvicorn argos.main:app`, puerto `8080`.
- Dashboard Streamlit: `src/argos/dashboard/app.py`, puerto `8501`.
- Base SQLite: `var/argos.db`.
- Datos: `data/raw`, `data/processed`, `data/legacy`.
- `argos-node`: `http://192.168.1.42`.
- Worker de caudalimetro: hilo interno de FastAPI si `ARGOS_NODE_URL` esta definido.
- Worker diario de sync: hilo interno de FastAPI si `ARGOS_DAILY_SYNC_ENABLED=true`.
- Tareas Windows: scripts existentes; registro activo No confirmado.

## Variables necesarias

Ver [configuration-reference.md](configuration-reference.md). Minimo operativo local:

- `DATABASE_URL`
- `ECOWITT_INGEST_TOKEN`
- `ARGOS_ADMIN_TOKEN`
- `ARGOS_NODE_URL` para valvula/caudalimetro
- credenciales AEMET/Copernicus/Ecowitt Cloud solo para sincronizaciones externas

## Arranque normal

En PowerShell:

```powershell
Set-Location "C:\Users\Fizico\Documents\github\argos"
uv sync
uv run alembic current
uv run uvicorn argos.main:app --host 127.0.0.1 --port 8080
```

En otra terminal:

```powershell
Set-Location "C:\Users\Fizico\Documents\github\argos"
uv run streamlit run src/argos/dashboard/app.py --server.port 8501 --server.headless true
```

## Arranque en segundo plano en Windows

```powershell
Start-Process -FilePath ".\.venv\Scripts\uvicorn.exe" -ArgumentList @("argos.main:app", "--host", "127.0.0.1", "--port", "8080") -WorkingDirectory "C:\Users\Fizico\Documents\github\argos" -WindowStyle Hidden
Start-Process -FilePath ".\.venv\Scripts\streamlit.exe" -ArgumentList @("run", "src/argos/dashboard/app.py", "--server.port", "8501", "--server.headless", "true") -WorkingDirectory "C:\Users\Fizico\Documents\github\argos" -WindowStyle Hidden
```

## Orden recomendado

1. Confirmar que la base existe y esta integra.
2. Arrancar FastAPI.
3. Confirmar `/health`.
4. Arrancar Streamlit.
5. Confirmar dashboard.
6. Confirmar `argos-node` antes de usar la valvula.

## Parada normal

1. Si se ha operado riego, cerrar valvula y confirmar `state: closed`.
2. Cerrar Streamlit.
3. Cerrar FastAPI.
4. Ejecutar backup si procede.

Para procesos en segundo plano:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'uvicorn.*argos.main|streamlit.*src/argos/dashboard/app.py' } |
  Select-Object ProcessId,Name,CommandLine
```

Detener solo los procesos identificados como ARGOS.

## Reinicio

1. Confirmar valvula cerrada.
2. Detener dashboard y API.
3. Arrancar API.
4. Arrancar dashboard.
5. Ejecutar [health-checks.md](health-checks.md).

## Recuperacion tras reinicio de Windows

Arranque automatico: No confirmado.

Despues de reiniciar Windows:

1. Abrir PowerShell.
2. Ir a `C:\Users\Fizico\Documents\github\argos`.
3. Arrancar API y dashboard con los comandos anteriores.
4. Verificar `http://127.0.0.1:8080/health`.
5. Verificar `http://127.0.0.1:8501`.
6. Verificar `http://192.168.1.42/status`.
7. No operar valvula hasta conocer su estado.

## Verificacion posterior

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501
Invoke-RestMethod http://192.168.1.42/status
uv run argos ecowitt status
uv run argos data audit-source-artifacts
```
