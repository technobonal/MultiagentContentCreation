# backend/

Python + FastAPI. Un solo worker: los runs viven en memoria.

## Qué hay

- `app/api`: endpoints (`POST /api/runs`, `GET /api/runs/{id}/eventos` por SSE con `Last-Event-ID`, `?desde=` y `?ritmo=1|2|3`, `POST /api/runs/{id}/aprobacion`).
- `app/runs`: registro de ejecuciones, orquestador de relleno (sin LLM) y orquestador real, aprobación humana y sello.
- `app/agentes`: estratega, redactor, director de arte, revisor de fidelidad, ciclo de corrección y cliente Groq con limitador y cascada de modelos.
- `app/fuentes`: carga y fragmentado de fuentes `.md`, `.txt` y `.pdf` con texto (los PDF escaneados se rechazan hasta tener OCR).
- `app/events`: emisor SSE y validación de cada evento contra `contracts/`.
- Carpetas reservadas para fases futuras (solo `.gitkeep`): `graph`, `rag`, `render`, `reviewer`, `sources`, `adapters`.

## Correrlo

```powershell
# Desde backend/
pytest                                   # 883 tests
uvicorn app.main:app --reload --port 8000
```

Modo `relleno` (por defecto): guion simulado, sin red. Modo `real`: `MODO_RUN=real` y `GROQ_API_KEY` en el `.env` de la raíz. Variables, modelos y límites: ver `app/config.py`.

## Aprobación humana

En modo real, tras `aprobacion_solicitada` el run espera la decisión de una persona (hasta `APROBACION_TIMEOUT_SEG`, 900 s; si vence cierra en `requiere_humano`). `APROBACION_HUMANA=0` la apaga. Las ediciones no se vuelven a verificar contra la fuente.

## Reglas

El backend emite eventos que cumplen `contracts/events/event.schema.json`; el sello de revisión, los hallazgos y el estado final los calcula código, nunca el LLM; sin fuente verificada el run pasa por una persona.
