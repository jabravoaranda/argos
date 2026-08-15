# Estado actual de ARGOS

Estado: Vigente
Tipo: Fuente de verdad de estado
Fuente de verdad: Este documento
Ultima actualizacion: 2026-08-15
Responsable logico: Mantenimiento de software
Revision: 3

## Regla de mantenimiento

Actualizar este documento cuando cambie una capacidad operativa, una decision consolidada, el despliegue, una migracion activa, el layout de `data/`, una dependencia critica o el modo de operacion declarado. No copiar inventarios masivos ni auditorias completas.

## 1. Identidad y alcance

ARGOS es el sistema local de observacion y control agricola para la finca `tomillar`. Integra datos meteorologicos, AEMET, Sentinel-2, diario de campo, analitica, estado hidraulico y control manual de electroválvulas de riego a traves de `argos-node`.

Proposito actual: conservar datos trazables, consultar el estado operativo y permitir operacion manual supervisada del riego desde el dashboard.

Principios consolidados:

- SQLite local es la base activa observada.
- SQL es la fuente de verdad para observaciones normalizadas, trazabilidad e historico operativo.
- `data/` conserva artefactos de origen, derivados y material `legacy`; no se borran archivos historicos sin decision explicita.
- Los secretos viven en `.env` y no se versionan.
- La estacion fisica se identifica por el slug `tomillar`; el gateway es hardware reemplazable.
- Las capacidades automaticas no se declaran operativas sin validacion observable.

ARGOS se considera operativo en modo manual supervisado cuando permite arrancar el sistema, comprobar su estado y abrir/cerrar electroválvulas configuradas desde el dashboard, manteniendo registro, cierre global y recuperacion basica de los datos.

No se declara todavia:

- riego autonomo;
- programacion automatica del riego;
- decision agronomica automatica;
- operacion desatendida.

## 2. Estado global por modulo

| Modulo | Disenado | Implementado | Desplegado | Validado | Operativo | Observaciones |
|---|---:|---:|---:|---:|---:|---|
| Base de datos | Si | Si | Si | Si | Si | SQLite `var/argos.db`, Alembic `20260802_0023`, `PRAGMA integrity_check=ok`. |
| Backups | Si | Si | Manual | Si | Parcial | Scripts disponibles y backups manuales verificados; scheduling Windows no confirmado como tarea activa. |
| Layout de datos | Si | Si | Si | Si | Si | `data/`: 1 `raw`, 3.067 `processed`, 1.659 `legacy`; dry-run con 0 movimientos. |
| Ecowitt LAN | Si | Si | Si | Si | Si | Recepcion y estado de gateway confirmados; gateway observado offline segun umbral si no hay informe reciente. |
| Ecowitt Cloud | Si | Si | Si | Parcial | Parcial | Backfill CLI y worker diario existen; una ejecucion reciente termino `completed_with_warnings`. |
| AEMET | Si | Si | Si | Si | Si | 5.986 observaciones diarias; ultimo dato observado `2026-07-30`. |
| Satelite | Si | Si | Si | Si | Si | 1.534 observaciones, 3.067 assets; ultimo `acquisition_time` `2026-07-31 11:11:09.767000`. |
| API FastAPI | Si | Si | Si | Si | Si | Proceso en `127.0.0.1:8080`; endpoints principales responden 200. |
| Dashboard Streamlit | Si | Si | Si | Si | Si | Proceso en `127.0.0.1:8501`; dashboard responde 200. |
| `argos-node` | Si | Integracion ARGOS si | Si | Si | Parcial | `http://192.168.1.42/status` responde 200; firmware/proceso interno externo a este repo. |
| Electrovalvulas | Si | Control dashboard si | Si | Parcial | Parcial | Configuracion actual: General EV8 rele 8, Sector I EV6 rele 6, Sector II EV7 rele 7; confirmacion fisica de campo: Pendiente de validacion operativa. |
| Boton manual apertura/cierre | Si | Si | Si | Software si | Parcial | Botones `Open valve`/`Close valve` y `Cerrar todo` en vista `Valvulas`; prueba fisica: Pendiente de validacion operativa. |
| Caudalimetro | Si | Si | Si | Si | Parcial | Worker registra minutos; 218 agregados observados. Cero sesiones cerradas observadas. |
| Diario de campo | Si | Si | Si | Tests/API | Si | CRUD y export CSV via API/dashboard con token admin para escritura. |
| Analitica | Si | Si | Si | Tests/API | Si | Variables, series, correlaciones, distribuciones y tendencias sobre datos persistidos. |
| Sensores de suelo | Parcial | No confirmado | No confirmado | No confirmado | No | Referencias analiticas posibles, sin integracion operativa confirmada. |
| Scheduling | Si | Si | Parcial | Parcial | Parcial | Worker diario se arranca con FastAPI si `ARGOS_DAILY_SYNC_ENABLED=true`; tarea Windows de backup no confirmada. |
| Logs y supervision de procesos | Parcial | Basico | Parcial | Parcial | Parcial | Logging de app existe; supervisor externo/arranque automatico: No confirmado. |

## 3. Estado de despliegue

- Rama observada: `codex/data-protection-phase-1`.
- Commit de consolidacion documental observado: `b884636`. Para el commit exacto del arbol desplegado, ejecutar `git rev-parse --short HEAD`.
- Revision Alembic activa: `20260802_0023`.
- Motor de base de datos: SQLite.
- Base activa: `var/argos.db`.
- Integridad SQL: `ok`.
- Estructura real de `data/`: `raw/`, `processed/`, `legacy/`; quedan directorios vacios heredados `aemet/`, `satellite/`, `weather/`.
- FastAPI observado: `uvicorn argos.main:app --host 127.0.0.1 --port 8080`.
- Streamlit observado: `streamlit run src/argos/dashboard/app.py --server.port 8501 --server.headless true`.
- `ARGOS_NODE_URL` observado: `http://192.168.1.42`.
- Procesos automaticos internos: worker `argos-node-flowmeter-capture` si `ARGOS_NODE_URL` esta definido; worker `argos-daily-data-sync` si `ARGOS_DAILY_SYNC_ENABLED=true`.
- Procesos aun manuales: arranque de FastAPI/Streamlit, backups si la tarea de Windows no esta registrada, operaciones de valvula, decisiones de limpieza `legacy`.

## 4. Capacidades operativas actuales

- Recepcion Ecowitt LAN en `POST /api/v1/ecowitt/upload/{token}`.
- Consulta Ecowitt por API y dashboard.
- Diagnostico Ecowitt por `uv run argos ecowitt status`.
- Consulta AEMET por API/dashboard y sync/backfill manual/admin.
- Consulta satelital por API/dashboard y update/backfill manual/admin.
- Dashboard Streamlit con vistas de estado, observaciones, AEMET, satelite, diario, analitica, valvulas y calidad.
- Apertura/cierre manual de electroválvulas configuradas desde la vista `Valvulas`: General EV8, Sector I EV6, Sector II EV7.
- Cierre global `Cerrar todo` para todas las electroválvulas configuradas.
- Lectura de `argos-node` `/status` y `/valves/<id>`.
- Persistencia de caudalimetro por minuto cuando `ARGOS_NODE_URL` esta configurado.
- Backup/restore SQLite mediante scripts.
- Auditorias de duplicados, `source_artifacts`, staging, cursores e inventario de archivos.

## 5. Limitaciones actuales

- No hay riego autonomo ni programacion automatica de riego.
- No hay cierre automatico documentado ante caudal anomalo, perdida de red o timeout operativo.
- La posicion de valvula es estimada por ARGOS; no hay sensor independiente de final de carrera confirmado.
- Confirmacion fisica de apertura/cierre en campo: Pendiente de validacion operativa.
- `argos-node` es externo al repositorio; su arranque y firmware no estan documentados aqui como controlados por ARGOS.
- Arranque automatico tras reinicio de Windows: No confirmado.
- Tarea programada Windows de backup: No confirmado.
- Supervision externa de procesos FastAPI/Streamlit: No confirmado.
- Ecowitt Cloud puede completar con warnings; payload real y reglas de enriquecimiento siguen pendientes.
- Quedan 1.659 archivos `legacy` preservados; no se han eliminado ni declarado innecesarios.

## 6. Decisiones consolidadas

- La estacion canonica es `tomillar`.
- SQLite local `var/argos.db` es el despliegue activo observado.
- Los secretos se gestionan por `.env` y no se versionan.
- `data/processed/satellite` contiene assets satelitales operativos referenciados por SQL.
- `data/legacy` conserva material historico no resuelto hasta decision explicita.
- El modo operativo declarado es manual supervisado.
- No se borran, fusionan ni modifican automaticamente datos conflictivos.

## 7. Decisiones abiertas

- Politica final para 1.534 PNG satelitales unscoped preservados en `data/legacy/satellite`.
- Politica final para 125 archivos historicos de `data/weather` preservados en `data/legacy/weather`.
- Identificador canonico de gateway y aliases LAN/Cloud/MAC/model.
- Si Ecowitt Cloud puede enriquecer observaciones `DIRECT` existentes.
- Registro real de tareas Windows para backup y arranque automatico.
- Criterios de aceptacion fisica de electroválvulas y caudalimetro en campo.

## 8. Proximos pasos

| Prioridad | Accion | Responsable logico | Criterio de cierre |
|---:|---|---|---|
| 1 | Ejecutar checklist de operacion manual en campo | Operador ARGOS | Apertura/cierre de electroválvulas configuradas y `Cerrar todo` confirmados fisicamente y documentados. |
| 2 | Verificar cierre seguro y ausencia de caudal tras cierre | Operador ARGOS | Checklist firmado con caudal observado o limitacion registrada. |
| 3 | Registrar o descartar tarea Windows de backup | Operador ARGOS | `schtasks /Query` confirma tarea o decision documentada de backup manual. |
| 4 | Definir politica de archivos `legacy` | Arquitectura de datos | Decision escrita: conservar, archivar externo o eliminar con aprobacion. |
| 5 | Confirmar arranque automatico tras reinicio Windows | Mantenimiento de software | Reboot controlado con API/dashboard/worker disponibles. |
| 6 | Resolver aliases Ecowitt LAN/Cloud | Arquitectura de datos | Gateway identity documentada y probada con payload Cloud real. |

## 9. Fuentes documentales

- Indice documental: [README](README.md)
- Operacion: [Portada operativa](operations.md)
- Arranque/parada: [startup-and-shutdown](operations/startup-and-shutdown.md)
- Valvula manual: [manual-irrigation-operation](operations/manual-irrigation-operation.md)
- Health checks: [health-checks](operations/health-checks.md)
- Configuracion: [configuration-reference](operations/configuration-reference.md)
- Backups: [data-backup-and-recovery](operations/data-backup-and-recovery.md)
- Topologia runtime: [runtime-topology](operations/runtime-topology.md)
- Decisiones: [decisions-pending](decisions-pending.md)
- Arquitectura de datos: [data-integrity](architecture/data-integrity.md), [data-ingestion-traceability](architecture/data-ingestion-traceability.md), [data-layout](architecture/data-layout.md)
- Auditorias historicas: [documentation-consolidation-audit](audits/documentation-consolidation-audit.md)
