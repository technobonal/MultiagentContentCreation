# backend/

Python + FastAPI + LangGraph. **Vacío en la Fase 0**: se implementa desde la Fase 1 (reproducción de la grabación) y la Fase 2 (agentes reales).

Carpetas de `app/`: `api` (endpoints, SSE, subida), `agents` (estratega, redactor, director de arte, revisor), `graph` (LangGraph, checkpointer, `interrupt` humano), `sources` (lectores y indexado con posición), `rag` (Chroma + embeddings), `reviewer` (chequeos por código y evaluaciones LLM), `render` (Playwright), `events` (emisor, validación contra `contracts/`, reanudación por `seq`), `resolution` (reglas Auto/Fijo), `adapters` (modelo, banco de imágenes, exportadores).

Reglas: el backend emite eventos que cumplen `contracts/events/event.schema.json`; el sello de revisión lo calcula código; los efectos secundarios (publicar, exportar) van después del `interrupt` y deben ser idempotentes.
