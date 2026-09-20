# 1. Estado previo encontrado

ARGOS ya disponía de `plant_units.public_code` como identidad persistente, `field_events` para observaciones/actuaciones, la relación muchos a muchos `field_event_plant_units` y `field_event_photos` para originales y metadatos. La web creaba eventos mediante `POST /api/v1/field-events`; el lote usaba `/api/v1/plants/photos/stage` y `/photos/confirm`. Ambos guardaban bajo `data/processed/field-events/photos`. No existían autenticación Bearer externa, multipart directo por código público, auditoría de actor ni idempotencia de estos POST.

# 2. Arquitectura final

`cliente autorizado -> FastAPI /api/v1/external -> autenticación/scopes -> repositorios y servicio field_event_photos -> field_events + field_event_plant_units + field_event_photos / data/processed -> historial existente de Plantación`

No hay subsistema ChatGPT. Web, lote y API comparten modelos, repositorios y almacenamiento; se diferencian por `source`.

# 3. Endpoints disponibles

| Método y path | Finalidad | Entrada | Respuesta | Errores principales |
|---|---|---|---|---|
| `GET /api/v1/external/plants/{plant_code}` | Consultar ejemplar | path `plant_code` | ficha de planta | 401, 404, 503 |
| `GET /api/v1/external/plants/{plant_code}/observations` | Recuperar historial | path y `limit` | lista cronológica | 401, 404, 422, 503 |
| `POST /api/v1/external/plants/{plant_code}/observations` | Registrar observación | JSON con `observed_at`, `title?`, `note?`, arrays estructurados, `source`, `metadata?`; cabecera idempotente | observación, 201 | 401, 403, 404, 409, 422, 503 |
| `POST /api/v1/external/plants/{plant_code}/photos` | Registrar original | multipart `photo`, `observed_at`, `note?`, arrays estructurados como JSON texto, `source`, `metadata?`; cabecera idempotente | foto, 201 | 401, 403, 404, 409, 422, 503 |
| `GET /api/v1/external/plants/{plant_code}/photos` | Listar fotos | path y `limit` | metadatos y `content_url` | 401, 404, 422, 503 |
| `GET /api/v1/external/plants/{plant_code}/photos/{photo_id}/content` | Descargar original | códigos de planta y foto | binario con MIME original | 401, 404, 503 |

El detalle completo de campos, formatos y respuestas está en `openapi.json`.

# 4. Autenticación

Cabecera exacta: `Authorization: Bearer <TOKEN>`. `ARGOS_EXTERNAL_API_READ_TOKEN` permite GET. `ARGOS_EXTERNAL_API_WRITE_TOKEN` permite GET y POST. Token ausente o desconocido devuelve 401; usar el token de lectura para escribir devuelve 403. Los secretos solo viven en configuración. Se comparan en tiempo constante y nunca se guardan; la auditoría conserva una huella SHA-256.

# 5. OpenAPI

FastAPI publica el contrato activo en `GET /openapi.json` y la exportación versionada está en la raíz del repositorio: `openapi.json`. Se regenera con `uv run python scripts/export_openapi.py`.

# 6. Ejemplo real de subida

```bash
curl -X POST "http://127.0.0.1:8080/api/v1/external/plants/3B/photos" \
  -H "Authorization: Bearer <WRITE_TOKEN>" \
  -H "Idempotency-Key: 7c50151e-2c49-4eb6-a59b-5f0f08d9b3f4" \
  -F "photo=@foto.jpg" \
  -F "observed_at=2026-09-20T11:30:00+02:00" \
  -F "source=chatgpt" \
  -F "note=Fotografía de seguimiento" \
  -F 'visual_observations=["Follaje mayoritariamente verde"]' \
  -F 'recommendations=["Revisar humedad del suelo"]' \
  -F 'actions_taken=[]' \
  -F 'metadata={"conversation_id":"example"}'
```

# 7. Ejemplo real de consulta

```bash
curl "http://127.0.0.1:8080/api/v1/external/plants/3B/observations?limit=100" \
  -H "Authorization: Bearer <READ_TOKEN>"
```

# 8. Modelo de datos

- `plant_units`: ejemplar e identidad pública única.
- `field_events`: fecha de observación, texto libre, tipo, procedencia, metadatos y arrays estructurados de observación agronómica.
- `field_event_plant_units`: asociación entre evento y ejemplar.
- `field_event_photos`: original, ruta, MIME, nombre, tamaño, SHA-256, fecha EXIF/inferida y metadatos.
- `external_api_requests`: huella de cliente, clave idempotente, operación/hash, respuesta y recurso auditado.

Las migraciones Alembic relacionadas son `20260920_0030` para metadatos/auditoría externa y `20260920_0031` para observaciones estructuradas.

# 9. Fotografías

Los originales se conservan bajo `data/processed/field-events/photos/<año>/<mes>/`. SQL guarda rutas portables, no expone el filesystem. La orientación EXIF se aplica al generar miniaturas de staging y durante análisis visual, sin reescribir el original. Las miniaturas actuales son derivadas en memoria y no activos persistentes independientes. `observed_at` es explícito; `taken_at` conserva la fecha EXIF/inferida y `created_at` representa alta. La API sirve el original mediante una ruta autenticada.

# 10. Identidad de árboles

`3B` se consulta por igualdad contra la restricción única `plant_units.public_code`. No se deduce de fila/columna ni de `plant_matrix_cells`. Aunque muchos códigos coinciden con posiciones, el contrato externo depende de la identidad persistente. La ruta usa `/external/plants/` para evitar colisión con el endpoint heredado `/{plant_id}` y con códigos numéricos como `11`.

# 11. Idempotencia y auditoría

Cada POST exige `Idempotency-Key`. ARGOS calcula SHA-256 de una representación canónica de campos y, para fotos, del original. La combinación huella de token/clave es única. Repetición idéntica devuelve la respuesta 201 guardada con `Idempotency-Replayed: true`; misma clave con otra petición devuelve 409. Cada escritura completada queda en `external_api_requests` enlazada al `field_event`, sin guardar el token.

# 12. Accesibilidad de ARGOS

La ejecución observada usa FastAPI en `0.0.0.0:8080` y la comprobación desde la LAN devuelve `200` en `/health`. El transporte actual es HTTP: no hay listener TLS. Esta implementación no cambia Cloudflare, DNS ni firewall. Para un cliente remoto habrá que autorizar y configurar transporte HTTPS, alcance de red y política de exposición.

# 13. Variables de entorno

- `ARGOS_EXTERNAL_API_READ_TOKEN`
- `ARGOS_EXTERNAL_API_WRITE_TOKEN`
- `ARGOS_ADMIN_TOKEN`
- `ECOWITT_INGEST_TOKEN`
- `DATABASE_URL`
- `ARGOS_DATA_DIR` y overrides de almacenamiento, si se usan

No se incluye ningún valor secreto.

# 14. Tests

`tests/test_external_plant_api.py` cubre scopes, autenticación, código público, creación y reintento de observaciones, conflicto idempotente, multipart válido/inválido, procedencia, fechas UTC, metadatos, asociación, descarga, historial normal y almacenamiento compartido. Se mantienen las suites existentes de diario, Plantación y lote. Validación local final: `305 passed, 2 skipped`; `ruff` sin errores; `mypy` focalizado sin errores y suite completa con deuda tipográfica preexistente; migración SQLite comprobada en upgrade, downgrade y nuevo upgrade.

# 15. Archivos modificados

- `src/argos/api/external_*.py`: errores, autenticación y rutas externas.
- `src/argos/schemas/external_plants.py`: contrato externo.
- `src/argos/models/field_event.py` y migración `0030`: metadatos/auditoría.
- `src/argos/services/field_event_photos.py`: metadatos en el pipeline compartido.
- `src/argos/domain/field_events.py`, dashboard y API de lote: procedencias explícitas.
- `src/argos/main.py`: router y errores estructurados.
- `pyproject.toml`, `uv.lock`: soporte multipart.
- `scripts/export_openapi.py`, `openapi.json`: contrato reproducible.
- `tests/test_external_plant_api.py` y prueba de procedencia web: cobertura.
- documentación de estado, configuración, API y ADR.

# 16. Decisiones pendientes

- Hostname HTTPS y mecanismo autorizado de exposición fuera del equipo local.
- Custodia, rotación y entrega segura de los tokens configurados a cada cliente autorizado.
- Rotación periódica y número de clientes/tokens cuando haya más de uno.
- Si se persistirán miniaturas como activos propios en una iteración posterior.
- Validación de despliegue contra hardware/campo; no es necesaria para probar este contrato de datos.

# 17. Información necesaria para integrar ChatGPT

Un cliente necesita la URL base HTTPS alcanzable, el `openapi.json`, un token con scope adecuado y códigos públicos válidos. Para consultar usa GET de planta, observaciones o fotos con Bearer. Para registrar observación envía JSON, `observed_at` con offset, `source=chatgpt`, los arrays estructurados que procedan y una clave idempotente nueva. Para subir foto usa multipart con el original y los mismos campos, enviando cada array como texto JSON. Para recuperar historial consulta `/observations`; para binarios consulta `/photos` y sigue cada `content_url`. El cliente debe conservar la clave hasta recibir respuesta definitiva y reutilizarla solo para reintentar exactamente la misma operación. La integración automática ChatGPT -> ARGOS sigue pendiente; lo validado es que ChatGPT prepare la información y un usuario/cliente autorizado ejecute la petición.
