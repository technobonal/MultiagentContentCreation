# frontend/

React + Vite, lienzo en SVG y animaciones con GSAP. **Vacío en la Fase 0**: la Fase 1 construye el lienzo reproduciendo `contracts/recordings/b5_cifra_inventada.json` sin backend.

Carpetas de `src/`: `canvas` (solo dibuja eventos), `timeline` (estado y decisión por agente), `controls` (selectores Auto/Fijo, subida de PDF y foto), `review` (puntajes, hallazgos, evidencia de la fuente), `events` (cliente SSE, orden por `seq`, reproducción), `lib`.

Reglas: el frontend no conoce a los agentes; aplica eventos estrictamente por `seq`, valida cada uno contra el esquema y muestra una marca visible cuando el origen es `grabado`.
