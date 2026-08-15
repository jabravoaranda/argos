# Checklist de aceptacion de operacion manual

Estado: Vigente
Tipo: Checklist operativo
Fuente de verdad: `docs/00-estado-del-proyecto.md`
Ultima actualizacion: 2026-08-15
Responsable logico: Operador ARGOS
Revision: 2

## Datos de prueba

| Campo | Valor |
|---|---|
| Fecha | |
| Operador | |
| Version/commit | |
| Ubicacion | |
| Incidencias | |

## Plataforma

- [ ] API responde `GET /health`.
- [ ] Dashboard responde en `http://127.0.0.1:8501`.
- [ ] Base integra (`PRAGMA integrity_check=ok`).
- [ ] Espacio disponible suficiente.
- [ ] Backup reciente verificado.

## Fuentes

- [ ] Ecowitt reciente o estado offline explicado.
- [ ] Gateway accesible.
- [ ] AEMET sin error critico.
- [ ] Satelite sin error critico.

## Control

- [ ] `argos-node` accesible en `/status`.
- [ ] `/valves` lista General EV8, Sector I EV6 y Sector II EV7.
- [ ] Estado de la electroválvula seleccionada conocido antes de operar.
- [ ] Apertura individual desde boton `Open valve`.
- [ ] Confirmacion de apertura en UI.
- [ ] Confirmacion fisica de apertura o caudal.
- [ ] Cierre individual desde boton `Close valve`.
- [ ] Confirmacion de cierre en UI.
- [ ] Cierre global desde boton `Cerrar todo`.
- [ ] Confirmacion en UI de cierre global sin fallo parcial.
- [ ] Confirmacion fisica de cierre y ausencia de caudal.
- [ ] Reinicio de ARGOS y repeticion del ciclo.

## Resultado

Marcar una:

- [ ] Apto para operacion manual supervisada.
- [ ] Apto con observaciones.
- [ ] No apto.

## Decision final

| Campo | Valor |
|---|---|
| Decision | |
| Observaciones | |
| Acciones correctivas | |
| Firma operador | |
