# ARGOS Analytics

La seccion **Analisis** compara datos ya persistidos por ARGOS. No descarga datos, no modifica la ingesta y no cambia las tablas de observaciones originales.

## Fuentes

El catalogo canonico esta en `argos.domain.analytics` y se expone en:

```text
GET /api/v1/analytics/variables
```

Variables incluidas:

- Ecowitt: temperatura exterior, humedad relativa, radiacion solar, lluvia actual y viento.
- AEMET: temperatura media diaria, precipitacion diaria y viento medio diario.
- Satelite: NDVI, NDMI y fraccion valida por AOI.
- Controlador: caudal medio, volumen de agua y estado binario de EV1.

Cada variable declara unidad, resolucion temporal, tabla/columna real, agregaciones validas, campo de calidad si existe y dimension AOI si aplica.

## API

Endpoints disponibles:

```text
POST /api/v1/analytics/series
POST /api/v1/analytics/correlation
POST /api/v1/analytics/correlation-matrix
POST /api/v1/analytics/distribution
POST /api/v1/analytics/trend
```

Las fechas de entrada y salida canonicas son UTC. La API devuelve tambien `timestamp_local` usando `LOCAL_TIMEZONE`, para que el dashboard muestre el eje temporal en hora local sin perder trazabilidad UTC.

## Agregacion y alineamiento

Frecuencias soportadas:

- `original`
- `hourly`
- `daily`
- `weekly`
- `monthly`

Las agregaciones se validan por variable. Por ejemplo, el volumen de agua y la precipitacion acumulada admiten `sum`, mientras que el estado de EV usa `active_fraction` o `last`. Las correlaciones alinean las series por timestamp agregado y permiten lag fijo. Spearman se calcula con rangos para evitar depender de SciPy.

## Calidad, AOI y limites

Los filtros `zone_slug` y `quality_status` se aplican solo cuando la fuente los soporta. En satelite se filtra por AOI y calidad de observacion. En AEMET se puede filtrar por `quality_flag`.

Para proteger la interfaz, las series tienen `max_points`; si una consulta devuelve demasiado, el servicio reduce puntos de forma uniforme y lo comunica en `warnings`.

## Dashboard

La entrada de barra lateral **Analisis** contiene tres subpestanas:

- **Correlaciones**: pares X/Y, lag, Pearson/Spearman, regresion opcional y matriz multivariable.
- **Distribuciones**: histograma, boxplot, resumen estadistico y comparacion opcional.
- **Tendencias y referencias**: serie temporal, referencia media/mediana/media movil/tendencia lineal, anomalias y eventos del Diario de campo opcionales.

La pestaña usa un selector comun compacto para periodo, frecuencia, AOI y calidad. La accion **Restablecer** vuelve al rango local de los ultimos 30 dias con agregacion diaria.

## No incluido

- No se persisten productos analiticos derivados.
- No se recalculan ni rellenan huecos de ingesta.
- No se promedian direcciones de viento en este modulo.
- No se mezclan variables sin una columna real en la base de datos.
