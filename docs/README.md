# Documentacion de ARGOS

Estado: Vigente
Tipo: Indice documental
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Mantenimiento de software
Revision: 1

## Empezar aqui

Lee primero [00-estado-del-proyecto.md](00-estado-del-proyecto.md). Es la fuente de verdad del estado actual: que esta operativo, que esta solo implementado, que esta pendiente y que no debe asumirse.

## Operacion

- [operations.md](operations.md): portada operativa y ruta de lectura.
- [operations/startup-and-shutdown.md](operations/startup-and-shutdown.md): arranque, parada y reinicio.
- [operations/manual-irrigation-operation.md](operations/manual-irrigation-operation.md): uso manual supervisado de la valvula.
- [operations/health-checks.md](operations/health-checks.md): comprobacion en menos de dos minutos.
- [operations/configuration-reference.md](operations/configuration-reference.md): variables de entorno y defaults reales.
- [operations/data-backup-and-recovery.md](operations/data-backup-and-recovery.md): backup y restauracion.
- [operations/windows-backup-scheduling.md](operations/windows-backup-scheduling.md): registro de tarea Windows, no confirmado como activo.
- [operations/data-retention-policy.md](operations/data-retention-policy.md): retencion y limpieza, sin borrado automatico.
- [operations/runtime-topology.md](operations/runtime-topology.md): diagrama de ejecucion observado.
- [operations/manual-operation-acceptance-checklist.md](operations/manual-operation-acceptance-checklist.md): checklist de aceptacion.

## Arquitectura

- [architecture/data-integrity.md](architecture/data-integrity.md): restricciones naturales e idempotencia.
- [architecture/data-ingestion-traceability.md](architecture/data-ingestion-traceability.md): trazabilidad de ingesta.
- [architecture/data-layout.md](architecture/data-layout.md): layout fisico de `data/`.

## Capacidades

- Meteorologia Ecowitt: [operations/health-checks.md](operations/health-checks.md) y [operations/configuration-reference.md](operations/configuration-reference.md).
- AEMET: [operations/health-checks.md](operations/health-checks.md) y [operations.md](operations.md).
- Satelite: [satellite-observation.md](satellite-observation.md).
- Analitica: [analytics.md](analytics.md).
- Diario de campo: [field-diary.md](field-diary.md).
- Plantación: [plantation.md](plantation.md).
- Riego manual: [operations/manual-irrigation-operation.md](operations/manual-irrigation-operation.md).

## Decisiones

- [decisions-pending.md](decisions-pending.md): decisiones consolidadas y pendientes.
- [adr/20260828-plant-units-persistent-matrix-view.md](adr/20260828-plant-units-persistent-matrix-view.md): ejemplares vegetales persistentes y matriz derivada.

## Auditorias

Las auditorias en [audits/](audits/) son snapshots historicos o informes generados. No son la fuente principal del estado actual.

- [audits/documentation-consolidation-audit.md](audits/documentation-consolidation-audit.md)
- [audits/data-storage-audit.md](audits/data-storage-audit.md)
- [audits/data-integrity-preflight.md](audits/data-integrity-preflight.md)
- [audits/ingestion-traceability-gap-analysis.md](audits/ingestion-traceability-gap-analysis.md)
- [audits/legacy-weather-reconciliation.md](audits/legacy-weather-reconciliation.md)
- [audits/data-file-inventory.md](audits/data-file-inventory.md)
- [audits/orphan-satellite-assets-reconciliation.md](audits/orphan-satellite-assets-reconciliation.md)
- [audits/data-flow.md](audits/data-flow.md)

## Documentos generados

Estos documentos se regeneran con comandos y no deben editarse manualmente salvo para corregir el generador:

- [audits/data-file-inventory.md](audits/data-file-inventory.md): `uv run argos data inventory-files`.
- [audits/orphan-satellite-assets-reconciliation.md](audits/orphan-satellite-assets-reconciliation.md): `uv run argos data reconcile-orphan-satellite-assets --dry-run`.
- [audits/legacy-weather-reconciliation.md](audits/legacy-weather-reconciliation.md): `uv run argos data reconcile-legacy-weather`.

El detalle completo queda en `var/manifests/`, que no se versiona.

## Documentos que no definen estado actual

- [dashboard-analytics-plan.md](dashboard-analytics-plan.md): plan/borrador historico de analitica.
- Cualquier documento en `docs/audits/`: evidencia historica, no estado actual por si sola.
