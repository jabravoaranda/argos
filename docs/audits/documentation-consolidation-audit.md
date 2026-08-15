# Auditoria de consolidacion documental

Document type: Historical audit
Snapshot date: 2026-08-02
Current-state authority: docs/00-estado-del-proyecto.md
Generated manually/automatically: manual, from repository inspection
Do not use this document as the sole source of current operational state.

## Alcance

Esta auditoria inventaria la documentacion Markdown existente antes de la fase de consolidacion documental y operativa. No modifica datos, esquema SQL ni arquitectura.

## Resumen

| Ruta | Titulo | Idioma | Finalidad | Tipo | Fecha/snapshot | Estado inicial | Autoridad | Duplicidades/contradicciones/riesgos | Mantenibilidad |
|---|---|---|---|---|---|---|---|---|---|
| `docs/00-estado-del-proyecto.md` | ARGOS Project Status | Ingles | Estado resumido del proyecto | Estado | 2026-08-02 | vigente parcial | fuente de verdad prevista | Centrado en datos; no cubre operacion manual, despliegue ni valvula | buena, 28 lineas |
| `docs/analytics.md` | ARGOS Analytics | Ingles | Describir analitica disponible | Capacidad | No indicada | vigente parcial | auxiliar | No enlazado desde indice central; estado operativo no separado de diseno | buena, 45 lineas |
| `docs/architecture/data-ingestion-traceability.md` | ARGOS Data Ingestion Traceability | Ingles | Arquitectura de trazabilidad | Arquitectura | No indicada | vigente | fuente auxiliar | Referencias a fase 4; debe marcar estado y autoridad actual | buena, 48 lineas |
| `docs/architecture/data-integrity.md` | ARGOS Data Integrity | Ingles | Restricciones e idempotencia | Arquitectura | No indicada | vigente | fuente auxiliar | Falta cabecera documental | buena, 26 lineas |
| `docs/architecture/data-layout.md` | ARGOS Data Layout | Ingles | Layout de `data/` | Arquitectura | 2026-08-02 implicita | vigente | fuente auxiliar | Mezcla estado actual con historia de validacion | media, 72 lineas |
| `docs/audits/data-file-inventory.md` | ARGOS Data File Inventory | Ingles | Inventario generado de archivos | Auditoria generada | 2026-08-02 | generado | auxiliar | No debe ser interfaz humana completa; requiere resumen y manifest regenerable | media, 114 lineas |
| `docs/audits/data-flow.md` | ARGOS Data Flow | Ingles | Diagrama de flujo de datos | Auditoria/arquitectura | No indicada | historico parcial | auxiliar | Puede solaparse con topologia runtime; contiene rutas legacy-readable | buena, 66 lineas |
| `docs/audits/data-integrity-preflight.md` | Data Integrity Preflight | Ingles | Preflight de integridad | Auditoria historica | No indicada | historico | auxiliar | No marcado como snapshot historico | buena, 42 lineas |
| `docs/audits/data-storage-audit.md` | ARGOS Data Storage Audit | Ingles | Auditoria extensa de almacenamiento | Auditoria historica | 2026-08-02 implicita | historico | auxiliar | No debe usarse como estado actual; mezcla recomendaciones y evidencias | media, 273 lineas |
| `docs/audits/ingestion-traceability-gap-analysis.md` | ARGOS Ingestion Traceability Gap Analysis | Ingles | Gap analysis de trazabilidad | Auditoria historica | No indicada | historico | auxiliar | Falta cabecera historica normalizada | buena, 64 lineas |
| `docs/audits/legacy-weather-reconciliation.md` | Legacy Weather Reconciliation | Ingles | Reconciliacion de archivos weather legacy | Auditoria generada | 2026-08-02 | generado/historico | auxiliar | Detalle fila a fila; debe indicar no fuente actual | media, 130 lineas |
| `docs/audits/orphan-satellite-assets-reconciliation.md` | Orphan Satellite Assets Reconciliation | Ingles | Reconciliacion de PNG satelitales huerfanos | Auditoria generada | 2026-08-02 | generado/historico | auxiliar | Debe permanecer resumido y apuntar a manifest completo | media, 118 lineas |
| `docs/dashboard-analytics-plan.md` | ARGOS Dashboard Analytics Plan | Ingles | Plan de dashboard analitico | Plan/borrador | No indicada | borrador historico | auxiliar | Puede confundirse con capacidad operativa actual | buena, 84 lineas |
| `docs/decisions-pending.md` | ARGOS Pending Decisions | Ingles | Decisiones pendientes | Decisiones | No indicada | vigente parcial | fuente auxiliar | Incluye decisiones ya consolidadas junto a pendientes | buena, 30 lineas |
| `docs/field-diary.md` | Diario de campo | Espanol | Diario de campo | Capacidad | No indicada | vigente parcial | auxiliar | Falta estado implementado/desplegado; no enlazado desde indice | buena, 59 lineas |
| `docs/operations.md` | ARGOS Operations | Ingles | Operacion general | Operacion | No indicada | vigente pero mezclado | auxiliar | Mezcla Ecowitt, AEMET, admin, salud; debe pasar a portada | media, 134 lineas |
| `docs/operations/data-backup-and-recovery.md` | ARGOS Data Backup and Recovery | Ingles | Backup y recuperacion SQLite/data | Operacion | No indicada | vigente | fuente operativa auxiliar | Falta cabecera documental; debe enlazarse desde indice | buena, 125 lineas |
| `docs/operations/data-retention-policy.md` | ARGOS Data Retention Policy | Ingles | Retencion de datos | Operacion/politica | No indicada | vigente parcial | auxiliar | Falta estado actual y relacion con legacy | buena, 28 lineas |
| `docs/operations/windows-backup-scheduling.md` | ARGOS Windows Backup Scheduling | Ingles | Registro de tarea Windows | Operacion | No indicada | implementado, registro no confirmado | auxiliar | Debe distinguir script existente de tarea activa no confirmada | buena, 34 lineas |
| `docs/satellite-observation.md` | Satellite observation | Ingles | Capacidad satelital | Capacidad/operacion | No indicada | vigente parcial | auxiliar | Contiene `ARGOS_SATELLITE_ASSET_DIR=data/satellite`, obsoleto tras layout real; requiere correccion | media, 176 lineas |

## Hallazgos iniciales

| Problema | Evidencia | Accion requerida |
|---|---|---|
| Falta indice documental central | No existe `docs/README.md` | Crear indice y ruta de lectura |
| Estado principal incompleto | `00-estado-del-proyecto.md` solo resume datos | Rehacer como fuente de verdad global |
| Manual de valvula inexistente | No existe `docs/operations/manual-irrigation-operation.md` | Crear manual para operacion manual supervisada |
| Arranque/parada no separado | `docs/operations.md` incluye comandos y salud mezclados | Crear manual especializado y convertir `operations.md` en portada |
| Health checks dispersos | Endpoints y CLI estan en README/operations | Crear health checks de dos minutos |
| Configuracion dispersa | Settings en codigo y fragmentos en docs | Crear referencia unica de variables |
| Auditorias sin cabecera historica uniforme | Varias auditorias no indican autoridad actual | Normalizar cabeceras |
| Inventarios generados demasiado detallados para revision humana | Informes generados en `docs/audits/` | Mantener resumen y manifest regenerable |
| Decision pending mezcla estados | `decisions-pending.md` contiene contexto consolidado | Separar consolidadas y pendientes |
| Referencia obsoleta a `data/satellite` | `docs/satellite-observation.md` | Corregir a layout actual o marcar legacy |

## Estado observado para consolidacion

- Rama: `codex/data-protection-phase-1`.
- Commit observado: `926ecf2`.
- Alembic activo: `20260802_0023`.
- Base activa: SQLite en `var/argos.db`.
- Procesos observados: FastAPI en `127.0.0.1:8080` y Streamlit en `127.0.0.1:8501`.
- `argos-node`: `http://192.168.1.42/status` respondio `200`; `GET /valves/8` respondio `state=closed`.
- Layout real de `data/`: 1 `raw`, 3.067 `processed`, 1.659 `legacy`; dry-run de migracion con 0 movimientos y 0 conflictos.
- Auditorias de duplicados y `source_artifacts`: OK en el snapshot.

## Referencias rotas o sospechosas detectadas

- `docs/satellite-observation.md` mantiene `ARGOS_SATELLITE_ASSET_DIR=data/satellite`, incompatible con el layout real desplegado.
- `docs/operations.md` recomienda scheduling externo para AEMET, mientras el codigo actual arranca un worker diario si `ARGOS_DAILY_SYNC_ENABLED=true`; debe distinguir diseno anterior de despliegue observado.
- No hay documento unico que explique que el modo operativo actual es manual supervisado, no riego autonomo.
