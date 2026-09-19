# Avance del roadmap de ARGOS - 2026-09-19

Estado: Vigente
Tipo: Registro de ejecucion
Fuente de verdad: `docs/roadmap-future-iterations.md`
Ultima actualizacion: 2026-09-19
Responsable logico: Mantenimiento de software
Revision: 1

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
- `mypy src`: correcto, 90 archivos fuente sin incidencias.
- `pytest`: 289 pruebas superadas y 2 omitidas.
- Enlaces Markdown internos: correctos.
- `git diff --check`: correcto; solo avisos informativos de conversion LF/CRLF de Git en Windows.

## Fase 1: en curso

Primera extraccion completada sin cambio de comportamiento:

- `src/argos/dashboard/formatting.py`: formatos numericos, binarios, fechas, identificadores y tamanos.
- `src/argos/dashboard/dataframes.py`: conversion comun de registros API a `DataFrame`.
- `src/argos/dashboard/pages/quality.py`: pagina de Calidad separada.
- `src/argos/dashboard/app.py` mantiene los nombres importados que ya consumian las pruebas y el resto de la aplicacion.
- Se han agregado pruebas directas para formato y para el bloqueo de Calidad sin token administrativo.

El archivo principal ha bajado de 7.077 a 6.873 lineas. La meta de menos de 2.000 lineas sigue abierta y debe alcanzarse mediante extracciones pequenas, cada una con suite completa.

Siguiente orden recomendado:

1. Extraer las utilidades y la pagina AEMET.
2. Extraer utilidades satelitales y despues la pagina Satelite.
3. Extraer Diario de campo y Plantacion.
4. Mantener Valvulas para el final por su criticidad operativa.

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
