# API externa de seguimiento de plantas

Estado: Implementada, pendiente de despliegue y exposición de red autorizada
Contrato: `openapi.json` y `GET /openapi.json`

Todos los endpoints usan la identidad estable `plant_units.public_code` y están bajo `/api/v1/external/plants`. Las escrituras requieren `Authorization: Bearer ...` e `Idempotency-Key`; las lecturas requieren Bearer de lectura o escritura.

## Configuración

- `ARGOS_EXTERNAL_API_READ_TOKEN`: permite consultas.
- `ARGOS_EXTERNAL_API_WRITE_TOKEN`: permite consultas y escrituras.

Los valores deben ser aleatorios, largos y diferentes. No se versionan. Para revocar o rotar una credencial, sustituir su valor en `.env` y reiniciar FastAPI. El token anterior deja de ser válido tras el reinicio.

## Endpoints

- `GET /api/v1/external/plants/{plant_code}`: ficha del ejemplar.
- `GET /api/v1/external/plants/{plant_code}/observations`: historial normalizado.
- `POST /api/v1/external/plants/{plant_code}/observations`: nueva observación JSON.
- `POST /api/v1/external/plants/{plant_code}/photos`: foto original por `multipart/form-data`.
- `GET /api/v1/external/plants/{plant_code}/photos`: metadatos y URL de descarga.
- `GET /api/v1/external/plants/{plant_code}/photos/{photo_id}/content`: original autorizado.

`observed_at` debe incluir offset. ARGOS lo persiste y devuelve normalizado a UTC. `source` de escritura externa admite `api` o `chatgpt`. `metadata` es un objeto JSON en observaciones y un texto que contiene un objeto JSON en multipart.

## Ejemplo de foto

```bash
curl -X POST "http://127.0.0.1:8080/api/v1/external/plants/3B/photos" \
  -H "Authorization: Bearer <WRITE_TOKEN>" \
  -H "Idempotency-Key: <UUID>" \
  -F "photo=@foto.jpg" \
  -F "observed_at=2026-09-20T11:30:00+02:00" \
  -F "source=chatgpt" \
  -F "note=Fotografía de seguimiento"
```

Repetir exactamente la misma petición con la misma clave devuelve la respuesta inicial y `Idempotency-Replayed: true`. Reutilizar la clave con otro contenido devuelve `409`.

## Errores

Los errores propios de esta API usan `{"error":{"code":"...","message":"...","details":...}}`. Los códigos estables incluyen `plant_not_found`, `invalid_photo`, `missing_bearer_token`, `invalid_bearer_token`, `insufficient_scope`, `invalid_idempotency_key`, `idempotency_key_conflict`, `duplicate_photo` y `validation_error`.
