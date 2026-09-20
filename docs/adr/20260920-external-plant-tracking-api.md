# ADR: API externa de seguimiento de plantas

Estado: Aceptada
Fecha: 2026-09-20

## Contexto

ARGOS ya conserva plantas en `plant_units`, actuaciones en `field_events`, asociaciones en `field_event_plant_units` y originales fotográficos en `field_event_photos`. Los clientes máquina a máquina necesitan registrar y consultar el mismo seguimiento sin acceder a SQLite ni crear un modelo paralelo.

## Decisión

- Publicar una fachada versionada bajo `/api/v1/external/plants/{plant_code}`.
- Resolver `{plant_code}` exclusivamente contra `plant_units.public_code`.
- Reutilizar `FieldEventRepository`, `PlantRepository` y `field_event_photos`.
- Autenticar con tokens Bearer configurables separados para lectura y escritura. Un token de escritura también puede leer.
- Exigir `Idempotency-Key` en cada POST y auditar la respuesta en `external_api_requests` usando solo la huella SHA-256 del token.
- Conservar `observed_at`, fecha EXIF y fecha de subida como conceptos distintos.
- Mantener `source` independiente del modelo: `web`, `batch_upload`, `api` y `chatgpt` terminan en las mismas tablas.

El segmento `/external/` evita la ambigüedad del API existente, donde `/api/v1/plants/{plant_id}` usa un entero interno y algunos códigos públicos, como `11`, también son numéricos.

## Consecuencias

- No existe código específico de integración con ChatGPT.
- Los clientes externos no conocen rutas de archivos ni la base de datos.
- Rotar un token requiere cambiar `.env` y reiniciar FastAPI.
- Publicar ARGOS fuera del host local sigue siendo una decisión operativa pendiente; este cambio no abre puertos ni modifica red, firewall o túneles.
