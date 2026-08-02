# Operacion manual de riego

Estado: Vigente
Tipo: Manual operativo
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-02
Responsable logico: Operador ARGOS
Revision: 1

## 1. Alcance

Este manual cubre el modo manual supervisado actualmente deseado:

- abrir la valvula maestra desde el boton existente del dashboard;
- cerrar la valvula maestra desde el boton existente;
- observar estado de `argos-node`, valvula y caudalimetro;
- recuperar la operacion ante fallos basicos.

No cubre riego autonomo, programacion automatica, decisiones agronomicas automaticas ni operacion desatendida.

## 2. Requisitos previos

| Requisito | Estado confirmado |
|---|---|
| PC encendido | Requerido |
| Repositorio | `C:\Users\Fizico\Documents\github\argos` |
| API FastAPI | Confirmada en `http://127.0.0.1:8080` |
| Dashboard | Confirmado en `http://127.0.0.1:8501` |
| `argos-node` | Confirmado en `http://192.168.1.42` |
| Red PC-controlador | Confirmada por `GET /status` |
| Alimentacion del controlador | No confirmado |
| Valvula conectada | Pendiente de validacion operativa |
| Token admin | Necesario para acciones admin; no necesario para boton directo de `argos-node` observado en el dashboard |

## 3. Arranque

Desde PowerShell en `C:\Users\Fizico\Documents\github\argos`:

```powershell
uv run alembic current
uv run uvicorn argos.main:app --host 127.0.0.1 --port 8080
```

En otra terminal:

```powershell
uv run streamlit run src/argos/dashboard/app.py --server.port 8501 --server.headless true
```

No hay arranque automatico de Windows confirmado.

## 4. Comprobacion previa

Antes de abrir la valvula:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8501
Invoke-RestMethod http://192.168.1.42/status
Invoke-RestMethod http://192.168.1.42/valves/8
uv run argos ecowitt status
```

Condiciones minimas:

- API responde `status: ok`.
- Dashboard carga.
- `argos-node` responde.
- `GET /valves/8` devuelve `state: closed` antes de abrir.
- No hay error visible en la vista `Valvulas`.
- Si el caudalimetro muestra caudal antes de abrir, detener la operacion y revisar en campo.

## 5. Apertura

1. Abrir `http://127.0.0.1:8501`.
2. Ir a la vista `Valvulas`.
3. Confirmar que la tarjeta muestra estado `Closed` o equivalente.
4. Pulsar `Open valve`.
5. El dashboard pasa por `Sending open command...` y despues `Opening...`.
6. ARGOS estima la finalizacion con el parametro de duracion de apertura configurado en la barra lateral.
7. Confirmar aceptacion con ausencia de error y respuesta cruda de `argos-node` si se muestra.
8. Confirmar apertura fisica en campo o mediante caudal. Esta confirmacion esta pendiente de validacion operativa.

Latencias verificadas: no hay latencia fisica de campo confirmada. El dashboard registra `request_elapsed_ms`, pero no observa el instante real del rele ni final de carrera.

## 6. Cierre

1. En la vista `Valvulas`, confirmar estado `Open` o apertura estimada.
2. Pulsar `Close valve`.
3. El dashboard pasa por `Sending close command...` y despues `Closing...`.
4. ARGOS estima la finalizacion con el parametro de duracion de cierre configurado en la barra lateral.
5. Confirmar que el estado vuelve a `Closed`.
6. Confirmar cierre fisico y ausencia de caudal si el caudalimetro esta disponible.

## 7. Estados de la interfaz

Estados usados por el codigo:

- `closed`
- `sending_open_command`
- `opening`
- `open`
- `sending_close_command`
- `closing`
- `error`
- `unknown`

El estado `disconnected` no aparece como fase propia; una desconexion se representa como `error` con mensaje de `ArgosNodeError`.

## 8. Incidencias

| Incidencia | Diagnostico | Accion segura | Detener operacion cuando |
|---|---|---|---|
| Boton no responde | Dashboard bloqueado o estado no accionable | Recargar dashboard y comprobar `http://192.168.1.42/valves/8` | No se puede confirmar estado real |
| `argos-node` desconectado | `GET /status` falla o timeout | No abrir; revisar red/alimentacion/controlador | La valvula no esta cerrada fisicamente |
| Estado bloqueado en `opening`/`closing` | Estimacion UI sin confirmacion independiente | Consultar `GET /valves/8` y verificar en campo | Hay discrepancia entre UI y campo |
| Rele cambia pero valvula no | Problema electrico/hidraulico | Cerrar desde boton si es posible y cortar operacion en campo | No se puede cerrar de forma fiable |
| Valvula abierta sin confirmacion | Riesgo de riego no supervisado | Ejecutar cierre, verificar fisicamente | Persiste caudal o estado desconocido |
| Perdida de red | PC no alcanza `192.168.1.42` | No enviar mas ordenes; actuar localmente en controlador si procede | La valvula podria estar abierta |
| API caida | `/health` no responde | La valvula puede seguir controlandose desde dashboard solo si `argos-node` responde; registrar incidencia | Se pierde registro/observabilidad necesaria |
| Dashboard caido | `8501` no responde | No operar desde UI; reiniciar dashboard | No hay interfaz fiable |

## 9. Cierre seguro

1. Pulsar `Close valve` si estaba abierta.
2. Confirmar `GET /valves/8` con `state: closed`.
3. Confirmar ausencia de caudal si el caudalimetro lo permite.
4. Registrar incidencia en diario de campo si hubo discrepancias.
5. Detener servicios solo despues de confirmar cierre.

## 10. Limitaciones de seguridad

- Sin sensor independiente de posicion confirmado.
- Sin cierre automatico ante perdida de red confirmado.
- Sin cierre automatico por caudal anomalo confirmado.
- Sin enclavamiento fisico documentado en este repositorio.
- Sin operacion desatendida declarada.
