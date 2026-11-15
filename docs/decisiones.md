# Registro de decisiones

Una línea por decisión, con fecha. Lo más reciente al final.

- 2026-11-10: Penpot y Figma son destinos de exportación (DesignDoc → adaptadores), no parte del motor; los agentes no los manejan en vivo; documentado para Fase 5, Penpot primero; spike de una slide antes de implementar.
- 2026-11-10: Arquitectura sin Streamlit: front-end React/Vite + backend Python/FastAPI. Canal de eventos SSE, animaciones GSAP, monorepo.
- 2026-11-10: Entrada admite documento, URL o tema; en el portfolio el tema exige una fuente asociada. Investigador autónomo en Fase 4 o 5.
- 2026-11-11: Spike v3b válido. Ambos revisores cumplen criterios (a: 5/5 defectos, 0 flags; b: 5/5, 1 flag) con reasoning_effort=low y max_completion_tokens=4000, sin truncados. finish_reason=length y slides sin cobertura son error técnico. v3a archivada y no cuenta. Limitaciones: fuente sintética corta, defectos contradichos explícitamente, corridas casi réplicas. Pendiente v4: defectos S1 a S8 y segunda fuente.
- 2026-11-11: Contratos en JSON Schema 2020-12 con `$comment` en cada bloque; catálogo de eventos 0.1 con 15 eventos; el sello de revisión lo calcula código, nunca el LLM.
- 2026-11-11: `num_slides` cuenta el slide final de fuentes y atribución (el carrusel de 6 slides incluye ese slide).
- 2026-11-12: Caso estrella = The Scrum Guide 2020 (Schwaber y Sutherland), CC BY-SA 4.0. El carrusel es obra derivada y se publica bajo la misma licencia, con atribución en el slide de fuentes (ver `docs/licencias.md`).
- 2026-11-12: Reglas del canal acordadas: SSE, orden estricto por `seq`, validación contra `contracts/` y eventos inmutables. Las pruebas de reanudación e idempotencia se escriben con el reductor del frontend en la Fase 1.
- 2026-11-15: Imágenes: las de un PDF fuente sin licencia clara se bloquean por defecto y se liberan solo si el cliente confirma que tiene permiso (queda en el registro de ediciones y en el slide de fuentes); las fotos del cliente son opcionales en toda plantilla; las figuras con cifras se insertan recortadas, nunca redibujadas. Se implementa en una fase posterior.
- 2026-11-15: Reproductor (Fase 1, paso 3): controles play, pausa, reiniciar, 1x/2x y seek por índice de evento; el ordenador descarta repetidos idénticos y reporta como error los repetidos distintos, los huecos y el inicio distinto de 1; reloj inyectable (falso en pruebas, setTimeout al próximo evento en producción); espera máxima de 3000 ms entre eventos; reiniciar vuelve al inicio en pausa.
- 2026-11-15: El tope de 400 caracteres de `texto` es solo de transporte; el límite real de cada campo sale de su ficha (líneas máximas y fuente mínima). El presupuesto de caracteres por campo se entrega al redactor en la Fase 2; el lienzo muestra el desborde y no lo corrige.
