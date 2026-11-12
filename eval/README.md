# eval/

Evaluación del revisor. Sin esta medición, el revisor es una afirmación de marketing.

- `sources/`: fuentes técnicas reales usadas (con licencia registrada en `docs/licencias.md`).
- `pieces/`: 30 piezas generadas por el sistema + 20 con defectos inyectados.
- `labels/`: etiquetado a mano, idealmente dos personas por separado.
- `results/`: tabla de precisión y recall por dimensión para el README.

## Estado del spike de fidelidad

v3b válido (ver `docs/decisiones.md`). Pendiente v4: defectos sutiles S1 a S8 (criterio propuesto ≥ 6 de 8; recall de las "no dice" S1, S2 y S5 por separado) y una segunda fuente.

Atrapado = veredicto `no_respaldada`, `parcialmente_respaldada` o `contradice` sobre la afirmación inyectada; `no_verificada` por cita no literal no cuenta.
