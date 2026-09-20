# Avance del roadmap de ARGOS - 2026-09-19

Estado: Vigente
Tipo: Registro de ejecucion
Fuente de verdad: `docs/roadmap-future-iterations.md`
Ultima actualizacion: 2026-09-20
Responsable logico: Mantenimiento de software
Revision: 4

## Alcance de esta iteracion

Se han ejecutado solamente cambios y comprobaciones verificables por software. No se han enviado ordenes a valvulas, no se ha consultado `argos-node`, no se han reiniciado servicios o Windows y no se han registrado tareas programadas.

## Fase 0: completada

- Corregido el alcance de `numpy` en el reconocimiento visual de codigos de planta sin descartar el refactor previo.
- Eliminado el import redundante detectado en el mismo flujo.
- Corregidas las 30 incidencias iniciales de tipado en siete archivos.
- Separadas variables locales de comandos CLI para evitar tipos cruzados entre ramas.
- Explicitados tipos de geometria, inventario de datos, trazas de caudalimetro, formularios Streamlit, PIL y OpenCV.
- Corregido el tipo del ciclo de vida asincrono de FastAPI.

Validacion final:

- `ruff`: correcto.
- `mypy src`: correcto, 95 archivos fuente sin incidencias.
- `pytest`: 295 pruebas superadas y 2 omitidas.
- Enlaces Markdown internos: correctos.
- `git diff --check`: correcto; solo avisos informativos de conversion LF/CRLF de Git en Windows.

## Fase 1: en curso

Extracciones completadas sin cambio de comportamiento:

- `src/argos/dashboard/formatting.py`: formatos numericos, binarios, fechas, identificadores y tamanos.
- `src/argos/dashboard/dataframes.py`: conversion comun de registros API a `DataFrame`.
- `src/argos/dashboard/pages/quality.py`: pagina de Calidad separada.
- `src/argos/dashboard/pages/aemet.py`: pagina, cache, operaciones de importacion y utilidades AEMET separadas.
- `src/argos/dashboard/pages/satellite.py`: pagina, cache, graficos y operaciones satelitales separadas.
- `src/argos/dashboard/pages/field_diary.py`: pagina, cache, formularios, exportacion y utilidades del Diario de campo separadas.
- `src/argos/dashboard/pages/plantation.py`: pagina, cache, matriz, historial e importacion de fotos de Plantacion separadas.
- `src/argos/dashboard/ui.py`: descarga CSV y metricas compactas compartidas entre paginas.
- `src/argos/dashboard/app.py` mantiene los nombres importados que ya consumian las pruebas y el resto de la aplicacion.
- Se han agregado pruebas directas para formato, AEMET y el bloqueo de Calidad sin token administrativo.

El archivo principal ha bajado de 7.077 a 5.393 lineas. La meta de menos de 2.000 lineas sigue abierta y debe alcanzarse mediante extracciones pequenas, cada una con suite completa.

Siguiente orden recomendado:

1. Extraer Observaciones y sus graficos en bloques acotados.
2. Extraer Resumenes y Analisis, conservando sus contratos internos.
3. Extraer Actualizar datos antes de abordar la zona operativa.
4. Mantener Valvulas para el final por su criticidad operativa.

## Calidad continua: completada

- Agregado `.github/workflows/quality.yml` para ejecutar en cada PR y envio a `main`.
- El flujo instala el entorno bloqueado y Chromium, y ejecuta `ruff`, `mypy`, `pytest`, la validacion de enlaces Markdown y la comprobacion de espacios del diff.
- Se cancela una ejecucion anterior de la misma rama cuando llega una revision nueva.
- La secuencia se ha validado tanto localmente como en PR y tras la integracion en `main`.

## Correcciones operativas de software

- Corregida la recuperacion de las tarjetas de valvulas despues de cambiar una URL o IP incorrecta de `argos-node`.
- El estado `error` vuelve a consultar el nodo al refrescar, en lugar de quedar bloqueado en la sesion de Streamlit.
- Una respuesta valida limpia el error y la respuesta tecnica obsoletos, incluso cuando no contiene un estado de posicion reconocible.
- La correccion dispone de pruebas sin acceso ni envio de ordenes al hardware.
- Las pruebas Playwright contra un dashboard ya iniciado requieren ahora `ARGOS_RUN_LIVE_UI_TESTS=1`; la suite normal no abre la pagina de valvulas ni interrumpe WebSockets de una sesion operativa.
- Identificado el `WinError 10054` de `_ProactorBasePipeTransport` como ruido de desconexion del servidor Streamlit en Windows al cerrar el navegador de pruebas, independiente de la comunicacion con `argos-node`.

## Fase 2: parcialmente completada

Se ejecuto un ensayo no destructivo sobre la base activa mediante la API de backup de SQLite:

- Backup temporal: `.pytest-tmp/roadmap-backup-check/argos-20260919T081550Z.db`.
- Manifest SHA-256 generado y verificado.
- Resultado de integridad del backup: `ok`.
- Restauracion separada: `.pytest-tmp/roadmap-restore-check/argos-restored.db`.
- Resultado de integridad restaurada: `ok`.
- Revision Alembic en backup y restauracion: `20260829_0029`.
- Las tablas operativas principales pudieron leerse y contarse tras la restauracion.
- La base activa `var/argos.db` no fue reemplazada ni modificada por el restore.

Estado operativo observado:

- No se encontraron tareas programadas de Windows cuyo nombre o ruta contuviera `ARGOS`.
- No se encontraron procesos escuchando en los puertos habituales `8080` y `8501`-`8505` durante la comprobacion.
- No se registro ninguna tarea porque faltan una ubicacion externa autorizada para backups y una ventana operativa.
- No se probo el arranque tras reinicio porque interrumpiria el equipo y requiere presencia del operador.

## Punto de parada por interaccion fisica u operativa

No continuar de forma desatendida con estas acciones:

- reiniciar Windows para validar el arranque automatico;
- elegir o conectar un segundo disco, NAS o destino externo de backup;
- registrar la tarea diaria hasta confirmar destino, horario y credenciales del usuario de Windows;
- consultar o accionar valvulas en `argos-node`;
- validar caudal real, ausencia de caudal tras cierre o correspondencia entre EV y sector;
- confirmar sensores, gateways o identificadores Ecowitt mediante observacion fisica;
- eliminar o mover datos `legacy` fuera del almacenamiento actual.

## Reanudacion segura

La siguiente iteracion puede continuar con modularizacion puramente software. Antes de cualquier paso operativo, confirmar:

1. Destino principal y espejo para backups.
2. Horario de la tarea programada.
3. Ventana para reinicio controlado.
4. Presencia de una persona capaz de verificar valvulas y caudal en campo.
