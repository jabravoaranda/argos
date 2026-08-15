# Diario de campo

Estado: Vigente
Tipo: Capacidad operativa
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Operador ARGOS
Revision: 1

ARGOS incluye una tabla manual para registrar actuaciones y acontecimientos cualitativos de la finca. Estos eventos ayudan a interpretar las series de observación, pero no sustituyen a las medidas automáticas de Ecowitt, AEMET, satélite, caudalímetro o válvulas.

## Base de datos

Aplicar la migración:

```bash
uv run alembic upgrade head
```

Tabla:

```text
field_events
```

Campos principales:

- `occurred_at`
- `event_type`
- `title`
- `description`
- `zone_slug`
- `tree_reference`
- `quantity`
- `unit`
- `source`

`source` queda preparado para `manual`, `irrigation_system` e `imported`. En esta versión el dashboard crea solo eventos `manual`.

## Catálogos

Los códigos persistidos están en inglés y las etiquetas visibles en español.

Tipos iniciales:

```text
tillage, irrigation, pruning, fertilization, treatment, harvest, planting, maintenance, incident, observation, other
```

Zonas iniciales:

```text
olivos_pequenos, olivos_grandes, casa, arqueta, otra
```

## API

Lectura:

```text
GET /api/v1/field-events/catalog
GET /api/v1/field-events
GET /api/v1/field-events/{id}
GET /api/v1/field-events/export.csv
```

Escritura, con `X-Argos-Admin-Token`:

```text
POST /api/v1/field-events
PATCH /api/v1/field-events/{id}
DELETE /api/v1/field-events/{id}
```

Filtros de listado/exportación:

```text
from
to
event_type
zone_slug
search
limit
offset
```

El orden predeterminado es `occurred_at` descendente.

## Dashboard

Abrir la pestaña `Diario de campo` en la barra lateral. Desde ahí se pueden registrar, filtrar, editar, eliminar y exportar eventos CSV.
