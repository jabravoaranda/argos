# Operacion ARGOS

Estado: Vigente
Tipo: Portada operativa
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Operador ARGOS
Revision: 1

## Proposito

Esta portada dirige al operador a los manuales especializados. No debe mezclar en un unico documento Ecowitt, AEMET, administracion, riego, backup, salud y arranque.

## Flujo operativo habitual

1. Arrancar API y dashboard con [startup-and-shutdown.md](operations/startup-and-shutdown.md).
2. Comprobar salud con [health-checks.md](operations/health-checks.md).
3. Si hay riego manual, seguir [manual-irrigation-operation.md](operations/manual-irrigation-operation.md).
4. Registrar eventos agronomicos desde el diario de campo si procede.
5. Verificar o ejecutar backup con [data-backup-and-recovery.md](operations/data-backup-and-recovery.md).
6. Ante reinicio o fallo, recuperar desde [startup-and-shutdown.md](operations/startup-and-shutdown.md) y repetir health checks.

## Indice operativo

| Necesidad | Documento |
|---|---|
| Arrancar, parar o reiniciar | [startup-and-shutdown.md](operations/startup-and-shutdown.md) |
| Saber si ARGOS funciona en menos de dos minutos | [health-checks.md](operations/health-checks.md) |
| Abrir/cerrar valvula manualmente | [manual-irrigation-operation.md](operations/manual-irrigation-operation.md) |
| Aceptar operacion manual en campo | [manual-operation-acceptance-checklist.md](operations/manual-operation-acceptance-checklist.md) |
| Consultar variables de entorno | [configuration-reference.md](operations/configuration-reference.md) |
| Entender procesos y flujos activos | [runtime-topology.md](operations/runtime-topology.md) |
| Backup y restore | [data-backup-and-recovery.md](operations/data-backup-and-recovery.md) |
| Registrar backup en Windows | [windows-backup-scheduling.md](operations/windows-backup-scheduling.md) |
| Retencion y limpieza | [data-retention-policy.md](operations/data-retention-policy.md) |

## Referencias rapidas

```powershell
Set-Location "C:\Users\Fizico\Documents\github\argos"
uv run alembic current
uv run uvicorn argos.main:app --host 127.0.0.1 --port 8080
uv run streamlit run src/argos/dashboard/app.py --server.port 8501 --server.headless true
```

Endpoints principales:

- `GET http://127.0.0.1:8080/health`
- `GET http://127.0.0.1:8080/api/v1/weather/latest`
- `GET http://127.0.0.1:8080/api/v1/weather/gateway/status`
- `GET http://127.0.0.1:8080/api/v1/weather/aemet/sync/latest?station=6127X`
- `GET http://127.0.0.1:8080/api/v1/satellite/status`
- `GET http://192.168.1.42/status`
- `GET http://192.168.1.42/valves/8`

## Contenido reubicado

- Configuracion GW2000/Ecowitt: [configuration-reference.md](operations/configuration-reference.md) y [health-checks.md](operations/health-checks.md).
- Admin token y endpoints admin: [configuration-reference.md](operations/configuration-reference.md).
- AEMET y satelite: [health-checks.md](operations/health-checks.md), [satellite-observation.md](satellite-observation.md).
- Backup: [data-backup-and-recovery.md](operations/data-backup-and-recovery.md).
- Riego manual: [manual-irrigation-operation.md](operations/manual-irrigation-operation.md).
