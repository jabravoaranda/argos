# Migración de observaciones agronómicas estructuradas

Estado: Vigente
Fecha: 2026-09-20
Migración Alembic: `20260920_0031`

Estado operativo local: aplicada el 2026-09-20 sobre `var/argos.db`, con comprobación de integridad satisfactoria y copia previa en `var/backups/`.

## Alcance

La migración añade a `field_events` cinco columnas JSON nullable:

- `visual_observations`
- `interpretation`
- `recommendations`
- `actions_taken`
- `limitations`

No modifica ni borra filas existentes, enlaces `field_event_plant_units`, fotografías, rutas de almacenamiento, `public_code`, metadatos ni auditoría de idempotencia.

## Compatibilidad

Las entradas antiguas tienen `NULL` en las columnas nuevas y las APIs las serializan como `[]`. El comentario libre continúa en `description`/`note`; `metadata_json` sigue reservado para provenance adicional.

## Aplicación

Antes de aplicarla sobre `var/argos.db`, crear backup siguiendo `docs/operations/data-backup-and-recovery.md`.

```powershell
uv run alembic upgrade head
```

La reversión elimina únicamente estas cinco columnas:

```powershell
uv run alembic downgrade 20260920_0030
```
