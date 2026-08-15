# Decisiones ARGOS

Estado: Vigente
Tipo: Decisiones
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Arquitectura de datos
Revision: 1

## Decisiones consolidadas

| Decision | Contexto | Estado | Impacto |
|---|---|---|---|
| La estacion fisica usa slug `tomillar` | El GW2000 puede cambiar, pero la finca no | Consolidada | Los identificadores hardware no son identidad canonica de estacion |
| SQLite `var/argos.db` es el despliegue activo observado | El proyecto mantiene compatibilidad SQLAlchemy/PostgreSQL, pero la operacion actual usa SQLite | Consolidada | Backups y health checks priorizan SQLite |
| `data/legacy` conserva evidencia no resuelta | Hay archivos historicos sin asociacion segura | Consolidada | No hay borrado automatico de legacy |
| Operacion actual es manual supervisada | El dashboard permite abrir/cerrar valvula, pero no hay riego autonomo | Consolidada | No declarar operacion desatendida |
| Secretos fuera de Git | `.env` esta ignorado | Consolidada | Documentacion solo usa ejemplos seguros |

## Decisiones pendientes

| Decision | Contexto | Estado | Opciones | Criterio de decision | Fecha objetivo | Impacto |
|---|---|---|---|---|---|---|
| Identificador canonico de gateway | Existen referencias LAN, Cloud MAC, modelo y aliases | Pendiente | modelo; MAC Cloud; alias promovido; tabla de aliases | Payload real Cloud y hardware actual confirmados | No definido | Evita duplicar hardware y backfills |
| Resolucion aliases LAN/Cloud/MAC/model | Cloud y LAN pueden nombrar el mismo GW2000 distinto | Pendiente | normalizar aliases; mantener separados; reconciliar manualmente | Backfill Cloud real sin duplicados ni perdida de trazabilidad | No definido | Calidad de historico Ecowitt |
| Enriquecimiento Cloud sobre observaciones `DIRECT` | Hoy Cloud no modifica observaciones directas existentes | Pendiente | no enriquecer; completar solo nulos; crear vista comparativa | Reglas auditables campo a campo | No definido | Evita sobreescritura no trazable |
| Scheduling operativo | Hay worker diario interno y scripts Windows, pero tarea activa no confirmada | Pendiente | worker interno; Task Scheduler; manual | Evidencia de ejecucion estable tras reinicio | No definido | Continuidad de datos |
| Arranque automatico | FastAPI/Streamlit se arrancaron manualmente | Pendiente | Task Scheduler; servicio Windows; manual | API/dashboard disponibles tras reboot controlado | No definido | Recuperacion operativa |
| Politica futura de archivos `legacy` | 1.659 archivos preservados | Pendiente | conservar; archivar externo; borrar con aprobacion; reconciliar mas | Manifest completo, backup externo y decision explicita | No definido | Eficacia operativa y riesgo historico |
| Aceptacion fisica de valvula | UI y `argos-node` responden, pero falta prueba de campo documentada | Pendiente de validacion operativa | checklist manual; instrumentacion adicional | Apertura/cierre fisico y ausencia de caudal confirmados | No definido | Seguridad de operacion manual |
| Backup programado Windows | Scripts existen, registro no confirmado | Pendiente | registrar tarea; mantener manual | `schtasks /Query` y restore test | No definido | Recuperacion ante fallo |

## Decision Ecowitt Cloud actual

La interfaz operativa recomendada para backfill Cloud sigue siendo CLI hasta confirmar payload real y reglas de identidad:

```powershell
uv run argos ecowitt-cloud backfill `
  --start 2026-07-10T00:00:00Z `
  --end 2026-07-10T01:00:00Z `
  --gateway-identifier GW2000A `
  --station-type GW2000A_V3.3.2 `
  --cloud-mac AABBCCDDEEFF
```
