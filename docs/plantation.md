# Plantación

Estado: Vigente
Tipo: Capacidad operativa
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-29
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
- `field_event_photos`

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

## Fotografías

Las fotografías confirmadas no se guardan dentro de SQLite. ARGOS conserva los archivos en el directorio de datos y registra en SQLite los metadatos necesarios para trazabilidad:

- `field_events`: observación agronómica.
- `field_event_plant_units`: enlace entre la observación y el árbol afectado.
- `field_event_photos`: una fila por archivo, con nombre original, MIME, tamaño, SHA256, fecha de captura, origen de fecha, código detectado y confianza del resolvedor.

La importación masiva desde `Plantación` usa dos fases:

1. `Analizar fotos`: calcula SHA256, MIME, tamaño, miniatura y fecha; ejecuta un `PlantCodeResolver`; y propone un árbol únicamente si el código detectado existe en `plant_units`.
2. `Confirmar lote`: crea los `field_events` y sus enlaces solo para las fotos no duplicadas que el usuario deje asignadas a un árbol.

El resolvedor no interpreta posiciones de matriz. Si detecta `11`, `18#` o cualquier otro código, lo resuelve contra `plant_units.public_code`; desde el árbol ya resuelto se obtienen celda, especie, fila, línea y sector.

Pipeline de resolución:

1. QR: máxima prioridad. Un QR con payload `P:<codigo>` se acepta solo si `<codigo>` existe literalmente en `plant_units.public_code`.
2. Visión local de catálogo cerrado: compara la imagen orientada contra los códigos existentes. No genera códigos fuera del catálogo.
3. Nombre de archivo: fallback útil para lotes ya nombrados manualmente.

La primera versión de importación masiva usaba solo el nombre de archivo (`FilenamePlantCodeResolver`). Por eso una fotografía con una tablilla manuscrita `C2`, pero sin `C2` en el nombre del archivo, terminaba como `unassigned`, `código: sin detectar`, `confianza: 0.00`.

Estados de staging:

- `matched`: identificación inequívoca y resuelta contra un árbol existente.
- `review`: detección ambigua o de baja confianza; requiere revisión.
- `unassigned`: no se puede resolver contra un árbol.
- `duplicate`: el SHA256 ya existe en fotos confirmadas o se repite dentro del lote.

La fecha de captura se calcula por este orden: `EXIF DateTimeOriginal`, patrones reconocibles del nombre de archivo como `WhatsApp Image YYYY-MM-DD at HH.MM.SS`, y fecha indicada por el usuario para el lote. Si no hay metadatos ni fecha de lote, la API rechaza la confirmación en lugar de asignar la fecha actual.

Las miniaturas se generan como derivados de previsualización. Antes de redimensionar se aplica la orientación EXIF con `ImageOps.exif_transpose`, de forma que una foto vertical tomada con móvil no aparezca tumbada. El original confirmado se almacena sin reescritura innecesaria.

Al confirmar, ARGOS agrupa las fotos del mismo árbol en una observación de seguimiento fotográfico y conserva cada archivo con sus metadatos individuales en `field_event_photos`. Para compatibilidad con pantallas y APIs existentes, la primera foto del grupo se mantiene también en los campos históricos `photo_*` de `field_events`.

## Interfaz

La vista `Plantación` del dashboard muestra la matriz, filtros por estado, especie y sector, búsqueda por código, selección de celda ocupada y ficha del árbol con historial de eventos asociados. Desde la ficha se pueden registrar observaciones con foto subida desde el dispositivo o capturada con cámara; si la imagen conserva fecha EXIF, ARGOS registra el evento con esa fecha de captura. La acción `Importar lote de fotos` permite revisar una galería de staging con miniatura, código detectado, propuesta de árbol/celda, confianza y selector manual antes de confirmar.

Pendiente:

- Completar variedad, patrón, fecha de plantación, sector de riego y coordenadas GPS si existen.
