# Registro de decisiones

Una línea por decisión, con fecha. Lo más reciente al final.

- 2026-11-10: Penpot y Figma son destinos de exportación (DesignDoc → adaptadores), no parte del motor; los agentes no los manejan en vivo; documentado para Fase 5, Penpot primero; spike de una slide antes de implementar.
- 2026-11-10: Arquitectura sin Streamlit: front-end React/Vite + backend Python/FastAPI. Canal de eventos SSE, animaciones GSAP, monorepo.
- 2026-11-10: Entrada admite documento, URL o tema; en el portfolio el tema exige una fuente asociada. Investigador autónomo en Fase 4 o 5.
- 2026-11-11: Spike v3b válido. Ambos revisores cumplen criterios (a: 5/5 defectos, 0 flags; b: 5/5, 1 flag) con reasoning_effort=low y max_completion_tokens=4000, sin truncados. finish_reason=length y slides sin cobertura son error técnico. v3a archivada y no cuenta. Limitaciones: fuente sintética corta, defectos contradichos explícitamente, corridas casi réplicas. Pendiente v4: defectos S1 a S8 y segunda fuente.
- 2026-11-11: Contratos en JSON Schema 2020-12 con `$comment` en cada bloque; catálogo de eventos 0.1 con 15 eventos; el sello de revisión lo calcula código, nunca el LLM.
- 2026-11-11: `num_slides` cuenta el slide final de fuentes y atribución (el carrusel de 6 slides incluye ese slide).
