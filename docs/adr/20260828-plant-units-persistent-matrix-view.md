# ADR: Los ejemplares vegetales son entidades persistentes y la matriz 12x12 es una vista derivada

Estado: Aceptada
Fecha: 2026-08-28

## Contexto

ARGOS necesita representar árboles etiquetados de la finca como parte del gemelo digital. La plantilla visual existente usa una matriz 12x12 con coordenadas de `11` a `CC`, especies abreviadas y algunos elementos no vegetales.

## Decisión

Cada ejemplar vegetal se persiste como entidad propia en `plant_units`, con identificador interno, código visible único, especie, parcela, posición de matriz, estado, datos de riego opcionales, coordenadas opcionales y notas.

La matriz se persiste en `plant_matrix_cells` como geometría semántica: celdas vacías, celdas con ejemplar vegetal y celdas de infraestructura. La interfaz renderiza la matriz desde la API, no desde una imagen ráster pulsable.

El diario de campo se mantiene como fuente de actuaciones cualitativas y se amplía con la relación `field_event_plant_units` para asociar eventos a árboles reales sin eliminar `tree_reference`.

## Consecuencias

- El código visible de una tablilla no es clave primaria.
- Las celdas vacías existen como posición espacial, pero no crean árboles ficticios.
- Los elementos `Bidón` y `Rampa` no se cargan como plantas.
- Los riegos sectoriales pueden mostrarse como asociados por sector, no como medición individual por árbol.
- La plantilla original queda transcrita en `docs/reference/plantation_matrix_12x12.csv`; el símbolo `M` de `2B#` corresponde a Mango.
