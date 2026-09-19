# Revision detallada del repositorio ARGOS

Estado: Vigente
Tipo: Auditoria tecnica y estrategica
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-09-19
Responsable logico: Mantenimiento de software
Revision: 1

## 1. Resumen ejecutivo

Esta revision analiza el repositorio en la rama `codex/inventario-arboles-matriz`, commit observado `fd87151`, con dos cambios locales preexistentes en:

- `src/argos/dashboard/api_client.py`
- `src/argos/services/field_event_photos.py`

ARGOS tiene una base solida para una instalacion local agricola: API FastAPI, dashboard Streamlit, persistencia SQLAlchemy/Alembic, ingesta Ecowitt, AEMET, Sentinel-2, diario de campo, plantacion, analitica, backups y control manual de riego. La documentacion existente es inusualmente buena para el estado del proyecto y mantiene una distincion sana entre implementado, validado y operativo.

El principal riesgo tecnico no es ausencia de piezas, sino acumulacion: el dashboard concentra demasiada responsabilidad, la operacion desatendida todavia depende de supuestos no validados en campo, y una funcionalidad nueva de reconocimiento visual de fotos de plantas rompe tests y lint.

## 2. Evidencia revisada

- Documentacion principal: `README.md`, `docs/README.md`, `docs/00-estado-del-proyecto.md`, `docs/decisions-pending.md`, `docs/dashboard-analytics-plan.md`.
- Codigo fuente: `src/argos/**`, excluyendo artefactos `__pycache__`.
- Tests: `tests/**`.
- Migraciones: `alembic/versions/**`.
- Scripts operativos: `scripts/**`.
- Estado local de Git: dos archivos modificados antes de esta auditoria.

## 3. Resultado de comprobaciones

| Comprobacion | Resultado | Observacion |
|---|---:|---|
| `uv run pytest` | 282 passed, 3 failed, 2 skipped | Las 3 fallas pertenecen a `tests/test_plant_photo_batch.py` y comparten `NameError: name 'np' is not defined`. |
| `uv run ruff check .` | Fallo | `field_event_photos.py` importa `numpy` en una funcion y lo usa en otra donde no esta en alcance. |
| `uv run mypy src` | Fallo | 31 errores en 7 archivos: `satellite_geometry.py`, `data_layout.py`, `argos_node_flowmeter.py`, `dashboard/app.py`, `cli.py`, `field_event_photos.py`, `main.py`. |

Hallazgo critico inmediato: `src/argos/services/field_event_photos.py` falla en `_match_component_char()` porque usa `np.array(...)` sin importar `numpy` en ese alcance. El archivo ya estaba modificado antes de esta revision, por lo que este documento lo registra como prioridad de arreglo y verificacion.

## 4. DAFO

### Fortalezas

- Arquitectura funcional completa para el modo actual: API, dashboard, base de datos, ingestas, analitica, backups y operacion manual.
- Excelente cultura documental: el estado del proyecto, decisiones pendientes, operaciones, auditorias y topologia estan descritos con trazabilidad.
- Buen modelo de prudencia operativa: no se declara riego autonomo ni operacion desatendida sin validacion fisica.
- Tests amplios: 287 tests recogidos; pese a las fallas actuales, la cobertura funcional es una ventaja clara para iterar.
- Alembic y SQLAlchemy dan base para evolucionar esquema sin depender solo de SQLite.
- Separacion razonable entre modelos, repositorios, servicios, API y dashboard, salvo el archivo principal de Streamlit.
- Trazabilidad de datos operativos: `data/`, `source_artifacts`, staging, inventarios y reconciliaciones reducen riesgo de perdida historica.
- Identidad de estacion estable (`tomillar`) separada del hardware reemplazable.

### Debilidades

- `src/argos/dashboard/app.py` es excesivamente grande: unas 6.200 lineas. Mezcla navegacion, renderizado, llamadas a API, calculos, formularios, acciones admin y control de valvulas.
- El reconocimiento visual de fotos de plantas esta roto actualmente y bloquea la suite completa.
- El tipado no esta limpio: `mypy` reporta 31 errores en archivos centrales.
- El worker diario y el worker de caudalimetro viven dentro del proceso FastAPI mediante hilos; suficiente para laboratorio/local, pero fragil para operacion desatendida.
- Hay muchas rutas administrativas en dashboard/API que dependen de token y convenciones locales; falta un modelo mas explicito de roles, auditoria de acciones y confirmaciones criticas.
- `data/legacy` sigue siendo una carga operativa documentada: preserva evidencia, pero tambien mantiene ambiguedad.
- Los datos voluminosos estan fuera de Git, como debe ser, pero el arbol local acumula miles de archivos en `data/` y `var/`; sin disciplina de manifiestos/backups puede volverse dificil de migrar.
- Hay duplicacion de logica de operaciones entre CLI, dashboard y servicios. No es grave aun, pero crecera con nuevas capacidades.

### Oportunidades

- Extraer el dashboard en modulos por dominio: inicio, observaciones, analitica, plantacion, diario, satelite, AEMET, valvulas, calidad.
- Convertir el roadmap operativo en issues o documentos por fase: estabilidad, limpieza, automatizacion supervisada, analitica avanzada.
- Consolidar jobs periodicos fuera del ciclo de vida HTTP: servicio Windows, Task Scheduler, proceso worker supervisado o cola ligera.
- Hacer que la plantacion evolucione hacia gemelo digital real: historial fotografico, eventos, lineas de riego, sensores y correlaciones por unidad vegetal.
- Elevar las comprobaciones `ruff`, `mypy` y `pytest` a criterio de cierre de cada iteracion.
- Crear snapshots reproducibles de datos: manifiesto + checksum + backup probado + restauracion documentada.
- Persistir productos analiticos estables cuando las formulas esten validadas: mensual, estacional, anual, eventos secos, eventos de lluvia, wind rose.

### Amenazas

- Una automatizacion de riego prematura podria operar sobre sensores incompletos o estados estimados de valvula.
- Dependencias externas inestables: Ecowitt Cloud, AEMET, Copernicus, argos-node y red local.
- SQLite es adecuado para el despliegue actual, pero puede sufrir bloqueos si aumentan workers, dashboard, imports y escritura de sensores concurrentes.
- El crecimiento del dashboard puede ralentizar cada cambio y hacer mas costosa la validacion visual.
- La ambiguedad de aliases LAN/Cloud/MAC/model puede duplicar datos o romper trazabilidad historica.
- Los archivos legacy pueden ocupar cada vez mas tiempo de mantenimiento si no se decide conservar, archivar externo o reconciliar.

## 5. Codigo muerto, inutil o redundante

### Limpieza local no versionada

No se detectaron `__pycache__` ni `.pyc` versionados con Git. Si aparecen en listados locales es por ejecuciones previas y estan correctamente ignorados.

Elementos locales ignorados que pueden limpiarse sin afectar al repositorio, siempre que no haya procesos activos:

- `__pycache__/` bajo `src/`, `tests/` y `alembic/`.
- `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`.
- `.pytest-tmp*`.
- `celerybeat-schedule.*`.
- Entornos locales `.venv/`, `.venv-test/` si se quieren recrear con `uv sync`.

### Directorios historicos o vacios

- `src/argos/weather` y `src/argos/worker` no tienen archivos Python versionados; solo aparecen por artefactos locales. No son codigo vivo del repositorio.
- Los ficheros `celerybeat-schedule.*` indican una etapa anterior con Celery, pero el proyecto actual no declara `celery` en `pyproject.toml` y el worker activo se implementa en `src/argos/main.py` con hilos.

Accion sugerida: documentar que Celery no forma parte de la arquitectura actual o eliminar referencias operativas antiguas si reaparecen.

### Codigo vivo pero con deuda

- `src/argos/dashboard/app.py`: vivo, muy probado, pero sobredimensionado. No debe borrarse; debe partirse.
- `src/argos/cli.py`: vivo, pero tiene ramas con variables reutilizadas que confunden a `mypy`. Conviene separar handlers por dominio.
- `src/argos/services/data_layout.py`: vivo y valioso para auditorias, pero combina inventario, reconciliacion, clasificacion, movimiento y escritura de informes.
- `src/argos/services/field_event_photos.py`: vivo, pero ahora mismo contiene una regresion funcional en reconocimiento visual.

## 6. Redundancias y acoplamientos

- Dashboard y CLI disparan operaciones similares para AEMET, satelite, Ecowitt Cloud y datos. La logica critica debe vivir en servicios; dashboard/CLI deben ser envoltorios finos.
- `ArgosApiClient` replica todas las rutas REST de forma manual. Es simple y explicito, pero con el crecimiento de endpoints puede convenir agrupar clientes por dominio.
- Las acciones admin mezclan UX, validacion de token, llamada API y presentacion de resultados. Conviene crear helpers por dominio para evitar divergencias.
- La logica de fechas, rangos y formatos aparece en varios puntos del dashboard. Mover utilidades ya estabilizadas a modulos pequenos reducira errores.

## 7. Opciones de optimizacion

### Corto plazo

- Corregir `field_event_photos.py` y reejecutar `ruff`, `mypy` focalizado y `pytest tests/test_plant_photo_batch.py`.
- Resolver primero los errores `ruff`; son pocos y uno explica las fallas de tests.
- Anotar tipos locales en `data_layout.py`, `cli.py` y `main.py` para bajar ruido de `mypy`.
- Mantener limpieza local periodica de cachés y temporales ignorados.

### Mantenibilidad

- Extraer `dashboard/app.py` por paginas:
  - `dashboard/pages/home.py`
  - `dashboard/pages/observations.py`
  - `dashboard/pages/analytics.py`
  - `dashboard/pages/plantation.py`
  - `dashboard/pages/field_diary.py`
  - `dashboard/pages/aemet.py`
  - `dashboard/pages/satellite.py`
  - `dashboard/pages/valves.py`
  - `dashboard/pages/quality.py`
- Extraer componentes comunes: metric cards, charts, date filters, CSV export, admin action feedback.
- Crear pruebas por modulo extraido antes o durante cada corte para no perder cobertura.

### Rendimiento

- Revisar queries de endpoints de series y observaciones antes de aumentar volumen; priorizar indices por fecha, fuente, estacion/AOI y variable cuando proceda.
- Limitar payloads grandes en dashboard y usar paginacion real en tablas operativas.
- Cachear en backend productos caros y estables, no solo en Streamlit.
- Mantener previews satelitales y fotos con politica de retencion y thumbnails para evitar arrastrar binarios grandes en cada flujo.

### Operacion

- Sacar jobs periodicos a un mecanismo supervisado cuando se quiera operacion desatendida.
- Registrar health checks de workers, no solo de API/dashboard.
- Formalizar un log/auditoria de acciones manuales de valvula: usuario/logical actor, sector, orden, respuesta, duracion, estado de caudal.
- Probar restore de backup como parte del checklist, no solo creacion de backup.

## 8. Riesgos prioritarios

| Prioridad | Riesgo | Impacto | Siguiente accion |
|---:|---|---|---|
| P0 | Falla actual en reconocimiento visual de fotos de plantas | Suite roja; lote fotografico no fiable | Corregir `np` fuera de alcance y ejecutar tests focalizados. |
| P1 | Dashboard monolitico | Cambios lentos y riesgo de regresiones visuales | Extraer una primera pagina de bajo riesgo y fijar patron. |
| P1 | Operacion de riego no validada fisicamente | Riesgo operativo en campo | Ejecutar checklist de aceptacion y documentar evidencia. |
| P1 | Jobs en hilos dentro de FastAPI | Recuperacion fragil tras fallo/reinicio | Decidir supervisor externo o proceso worker. |
| P2 | `mypy` con 31 errores | Menos confianza al refactorizar | Resolver por lotes pequenos. |
| P2 | Legacy sin decision final | Carga de mantenimiento | Cerrar politica de archivo/reconciliacion. |

## 9. Criterios de cierre sugeridos para proximas iteraciones

Una iteracion deberia cerrar con:

- `uv run ruff check .` en verde.
- `uv run pytest` en verde o fallas explicitamente justificadas.
- `uv run mypy src` al menos no peor que la linea base, idealmente reduciendo errores.
- Documento actualizado si cambia una capacidad operativa.
- Sin modificar datos historicos ni `legacy` salvo decision documentada.
- Si toca riego, evidencia de prueba segura y rollback operativo.

