# Plantación

Estado: Vigente
Tipo: Capacidad operativa
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-28
Responsable logico: Operador ARGOS
Revision: 1

ARGOS representa la plantación como ejemplares vegetales persistentes y una matriz 12x12 derivada de datos. Las coordenadas usan dos símbolos base 12: filas y columnas de `1` a `C`; por tanto la primera celda es `11` y la última es `CC`. La línea de riego se deriva de la fila de la matriz (`fila-1` ... `fila-C`).

## Datos

Tablas principales:

- `plant_parcels`
- `plant_matrix_cells`
- `plant_units`
- `plant_irrigation_lines`
- `field_event_plant_units`

La transcripción inicial de la plantilla está en:

```text
docs/reference/plantation_matrix_12x12.csv
```

Columnas mínimas:

```text
cell_position, visible_code, symbol, notes
```

`cell_position` es la celda geométrica de la matriz. `visible_code` es el código mostrado en la plantilla. Esto permite representar casos desplazados como `18#` sin forzar una coordenada inventada.

## Importación

Aplicar primero migraciones:

```powershell
uv run alembic upgrade head
```

Antes de aplicar sobre la base real `var/argos.db`, hacer backup siguiendo `docs/operations/data-backup-and-recovery.md`.

Crear matriz base vacía:

```powershell
uv run argos plants ensure-base-matrix
```

Importar la transcripción versionada:

```powershell
uv run argos plants import-matrix --path docs/reference/plantation_matrix_12x12.csv
```

La importación es idempotente: repetirla actualiza celdas y árboles existentes por código visible, sin duplicarlos.

## Interfaz

La vista `Plantación` del dashboard muestra la matriz, filtros por estado, especie y sector, búsqueda por código, selección de celda ocupada y ficha del árbol con historial de eventos asociados. Desde la ficha se pueden registrar observaciones con foto subida desde el dispositivo o capturada con cámara; si la imagen conserva fecha EXIF, ARGOS registra el evento con esa fecha de captura.

Pendiente:

- Completar variedad, patrón, fecha de plantación, sector de riego y coordenadas GPS si existen.
