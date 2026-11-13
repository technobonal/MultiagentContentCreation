# Roadmap por fases

Tope para la Fase 0: **3 días**. Más papel no baja el riesgo; ejecutar sí.

| Fase | Contenido | Criterio de salida | Estado |
| ---- | --------- | ------------------ | ------ |
| 0. Fundamentos | Contratos mínimos (15 eventos), esquema de entrada, ficha de plantilla, kit de marca, secuencia grabada, validador | `python contracts/validate.py` pasa sin fallas | Cerrada (2026-11-13) |
| 1. Lienzo | Lienzo SVG que reproduce la secuencia grabada (marcada como desarrollo) y línea de tiempo | Se puede grabar un video del lienzo | Pendiente |
| 2. Agentes reales | Backend con SSE; estratega, redactor, director de arte y revisor con corrección visible | Un carrusel de punta a punta desde una fuente real | Pendiente |
| 3. Portfolio | 3 plantillas, caso estrella, README con demo en video y ejemplos antes y después, despliegue en OCI con HTTPS | Demo pública estable | Pendiente |
| 4. Catálogo y segunda red | 10 a 15 plantillas, RAG con Chroma y Cohere, LinkedIn como configuración, bloques de código, PDF para LinkedIn | Panel de candidatas funcionando | Pendiente |
| 5. Producto | Kit de marca por usuario, "trae tu plantilla", exportación a Penpot, publicación como borrador vía intermediario | Señales de validación positivas | Pendiente |
| 6. Ciclo cerrado | Analítica de vuelta al estratega, programación, más redes, aprendizaje desde las ediciones del humano | Uso y pago medidos | Pendiente |

## Checklist de la Fase 0

- [x] Esquema de entrada en `contracts/input` con ejemplos válidos e inválidos
- [x] Sobre de eventos y catálogo 0.1 (15 eventos)
- [x] Secuencia grabada válida contra el esquema
- [x] Ficha de plantilla definida (`card.json` de la plantilla de pasos)
- [x] Kit de marca del MVP definido
- [x] `template.svg` renderizable de la plantilla de pasos
- [x] Reglas del canal acordadas: SSE, reanudación por `seq`, validación (pruebas de reanudación e idempotencia diferidas al reductor del frontend, Fase 1)
- [x] Caso estrella elegido y licencia confirmada (Scrum Guide 2020, CC BY-SA 4.0; ver `docs/licencias.md`)

## Spike de fidelidad (en paralelo)

- v3b válido (ver `decisiones.md`).
- Pendiente v4: defectos sutiles S1 a S8 (criterio propuesto ≥ 6 de 8, con recall de las "no dice" S1, S2, S5 por separado) y una segunda fuente.