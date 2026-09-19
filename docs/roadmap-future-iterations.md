# Roadmap de desarrollo futuro de ARGOS

Estado: Vigente
Tipo: Roadmap tecnico
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-09-19
Responsable logico: Mantenimiento de software
Revision: 1

## 1. Principio rector

ARGOS debe evolucionar desde el modo actual, manual supervisado, hacia mas autonomia solo cuando existan datos, seguridad operativa y evidencia de campo suficientes. La prioridad no es anadir automatizacion deprisa, sino conservar trazabilidad, mantener recuperacion ante fallos y evitar decisiones agronomicas opacas.

## 2. Fase 0: recuperar calidad de base

Objetivo: volver a una base verde antes de ampliar funcionalidad.

Acciones:

- Corregir la regresion de `src/argos/services/field_event_photos.py` que deja `np` fuera de alcance.
- Ejecutar:
  - `uv run ruff check .`
  - `uv run pytest`
  - `uv run mypy src`
- Reducir errores de `mypy` por lotes:
  - `main.py`: tipo correcto de lifespan async.
  - `cli.py`: separar variables por subcomando.
  - `data_layout.py`: anotar listas y valores opcionales.
  - `argos_node_flowmeter.py`: manejar `IngestionRun | None`.
  - `dashboard/app.py`: normalizar valores opcionales de formularios.
  - `field_event_photos.py`: estabilizar tipos de PIL/OpenCV/numpy.

Criterio de cierre:

- Tests y lint en verde.
- `mypy` en verde o con linea base documentada y menor que la actual.

## 3. Fase 1: modularizar dashboard sin cambiar comportamiento

Objetivo: reducir el riesgo de cada cambio futuro.

Orden sugerido:

1. Extraer utilidades puras de formato y fechas.
2. Extraer la pagina `Calidad`, porque depende sobre todo de API y tablas.
3. Extraer `AEMET` y `Satelite`, manteniendo llamadas API existentes.
4. Extraer `Diario de campo` y `Plantacion`.
5. Extraer `Valvulas` al final, por su mayor criticidad operativa.

Criterio de cierre:

- Cada extraccion mantiene tests existentes.
- No se cambia UX ni contrato API salvo ajuste explicitamente documentado.
- `src/argos/dashboard/app.py` baja progresivamente por debajo de 2.000 lineas.

## 4. Fase 2: operacion robusta local

Objetivo: hacer que ARGOS sobreviva mejor a reinicios, fallos de red y mantenimiento.

Acciones:

- Confirmar o registrar arranque automatico de API y dashboard.
- Confirmar o registrar tarea Windows de backup.
- Ejecutar restore test de SQLite con un backup reciente.
- Separar jobs periodicos de FastAPI si la instalacion va a funcionar sin supervision:
  - worker local dedicado;
  - Task Scheduler;
  - servicio Windows;
  - o proceso supervisado equivalente.
- Agregar health check de workers:
  - ultimo ciclo diario;
  - ultimo muestreo de caudalimetro;
  - ultimo resultado AEMET/Sentinel/Ecowitt Cloud.

Criterio de cierre:

- Tras reboot controlado, API, dashboard y captura necesaria vuelven a estar disponibles.
- Existe evidencia documental de backup y restore.

## 5. Fase 3: cerrar decisiones de datos

Objetivo: reducir ambiguedad historica.

Acciones:

- Resolver alias de gateway LAN/Cloud/MAC/model.
- Confirmar payload real Ecowitt Cloud y reglas de enriquecimiento.
- Decidir politica de `data/legacy`:
  - conservar local;
  - archivar externo;
  - reconciliar mas;
  - eliminar solo con aprobacion y backup.
- Convertir la decision en ADR o actualizacion de `docs/decisions-pending.md`.
- Mantener manifiestos con checksums para cualquier movimiento.

Criterio de cierre:

- No quedan decisiones de identidad que puedan duplicar observaciones Ecowitt.
- `legacy` tiene politica clara y reversible.

## 6. Fase 4: plantacion y diario como gemelo digital

Objetivo: que cada ejemplar vegetal tenga historial util, no solo posicion en matriz.

Acciones:

- Completar variedad, patron, fecha, linea de riego y coordenadas cuando existan.
- Estabilizar lote fotografico:
  - codigo por nombre de archivo;
  - QR;
  - vision como ayuda, no como verdad unica;
  - revision manual antes de confirmar.
- Asociar eventos de campo, fotos, riego y observaciones relevantes por planta/sector.
- Crear vistas de historial por ejemplar y por linea de riego.

Criterio de cierre:

- Una planta puede auditarse desde posicion, especie, historial de eventos, fotos y riego asociado.

## 7. Fase 5: riego manual seguro ampliado

Objetivo: pasar de control manual funcional a operacion manual robusta.

Acciones:

- Ejecutar checklist fisico de apertura/cierre por sector.
- Registrar evidencia de caudal durante apertura y ausencia de caudal tras cierre.
- Persistir eventos manuales de valvula con:
  - sector;
  - EV fisica;
  - instante de orden;
  - respuesta de argos-node;
  - resultado estimado;
  - caudal observado;
  - operador logico.
- Definir timeout maximo por seguridad incluso en modo manual.
- Mostrar advertencias si el caudal no concuerda con el estado esperado.

Criterio de cierre:

- Operador puede abrir/cerrar sectores con registro y verificacion basica de seguridad.

## 8. Fase 6: analitica agronomica validada

Objetivo: convertir datos en decisiones explicables.

Acciones:

- Persistir agregados mensuales, estacionales y anuales solo cuando las formulas esten validadas.
- Implementar deteccion de periodos secos y eventos de lluvia.
- Anadir wind rose cuando la agregacion direccional este consolidada.
- Cruzar riego, lluvia, AEMET, Ecowitt y satelite por ventanas temporales.
- Mantener las recomendaciones como diagnostico, no como actuacion automatica.

Criterio de cierre:

- Cada indicador tiene fuente, formula, periodo, cobertura y limitaciones visibles.

## 9. Fase 7: automatizacion supervisada, no autonoma

Objetivo: preparar programacion de riego sin saltar directamente a autonomia.

Precondiciones:

- Validacion fisica de valvulas.
- Caudalimetro fiable.
- Cierre seguro probado.
- Logs de accion manual suficientes.
- Backups y arranque automatico confirmados.

Acciones:

- Crear programaciones propuestas, no ejecutadas automaticamente al principio.
- Simular ventanas de riego contra meteorologia, humedad disponible si llega sensor de suelo, lluvia y restricciones.
- Implementar modo "armado": requiere confirmacion humana antes de ejecutar.
- Definir condiciones de bloqueo:
  - perdida de red;
  - caudal inesperado;
  - valvula no confirmada;
  - datos meteorologicos obsoletos;
  - backup/estado critico pendiente.

Criterio de cierre:

- ARGOS puede sugerir y, solo con confirmacion, ejecutar un plan supervisado con trazabilidad completa.

## 10. Backlog transversal

- CI local o remoto con `ruff`, `pytest` y `mypy`.
- Snapshot de rendimiento de endpoints de series antes de ampliar datos.
- Paginacion y limites explicitos en endpoints que devuelven historicos.
- Auditoria de seguridad de endpoints admin y secretos.
- Mejoras de observabilidad: logs estructurados, ultimos errores visibles, estado de workers.
- Guia de restauracion en maquina nueva: clonar repo, restaurar backup, reconstruir entorno, levantar API/dashboard.

## 11. Orden recomendado de proximas 5 iteraciones

1. Arreglar `field_event_photos.py` y recuperar checks.
2. Modularizar una pagina sencilla del dashboard y fijar patron.
3. Cerrar evidencia de backup/restore y arranque automatico.
4. Resolver identidad Ecowitt LAN/Cloud con payload real.
5. Ejecutar y documentar checklist fisico de riego manual.

