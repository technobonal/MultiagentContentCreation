# MultiagentContentCreation

**ES** · Plataforma de agentes que convierte una fuente técnica (PDF, URL, documento) en un carrusel de Instagram, con un revisor editorial explicable que verifica la fidelidad a la fuente. Un renderizador determinista dibuja el diseño en vivo mientras los agentes trabajan. · [English below](#english)

**EN** · An agent platform that turns a technical source (PDF, URL, document) into an Instagram carousel, with an explainable editorial reviewer that checks fidelity to the source. A deterministic renderer draws the design live while the agents work.

---

## Español

### Qué es

Cuatro agentes colaboran en un carrusel de 6 slides a partir de un documento fuente:

- **Estratega:** define el ángulo, el tono y el rol de cada slide.
- **Redactor:** escribe el texto de cada slide.
- **Director de arte:** elige la plantilla, pinta los fondos y escribe los textos en el lienzo.
- **Revisor:** verifica cada afirmación contra la fuente con una cita literal.

Al final, una persona edita y aprueba.

### Lo destacado

- **Revisor de fidelidad que atrapa cifras inventadas.** En la escena de la demo, el redactor dice que el Daily Scrum dura 30 minutos y la fuente dice 15. El revisor lo marca con la cita exacta, el texto se corrige en pantalla, se vuelve a verificar y la ejecución queda sellada (2 de 2 afirmaciones respaldadas).
- **Lienzo en vivo con avatares.** Cada agente tiene un avatar que se mueve a donde trabaja y muestra lo que hace.
- **Contrato de eventos con validación.** Todo es un evento con un sobre común, validado con JSON Schema (ajv en el frontend, Python en `contracts/validate.py`), con pruebas negativas que deben rechazarse.
- **Línea de tiempo determinista.** Un reductor puro convierte eventos en estado; un ordenador detecta huecos, duplicados y runs mezclados; un reproductor permite pausa, velocidad 1x/2x y salto.

### Estado

- **Fase 0 (Fundamentos):** cerrada. Contratos, esquemas, plantilla, kit de marca y validador.
- **Fase 1 (Lienzo):** en curso. El frontend ya reproduce una secuencia grabada de 24 eventos (`contracts/recordings/b5_cifra_inventada.json`) con agentes animados, corrección visible del revisor y tarjeta de hallazgos. Faltan los controles definitivos, las miniaturas y el video de demostración.
- **Fase 2 (Agentes reales):** pendiente. Hoy el backend solo tiene el esqueleto de carpetas.

Ver `SPEC.md` para decisiones, esquema de entrada y estructura de carpetas, y `docs/roadmap.md` para las fases.

### Estructura

* `contracts/`: esquemas compartidos (eventos, entrada, ficha de plantilla, kit de marca), secuencias grabadas y `validate.py`
* `templates/`: plantillas, paletas, tipografías (Inter y JetBrains Mono, ambas OFL), estilos y kit de marca
* `frontend/`: app Vite + React + TypeScript (lienzo, avatares, línea de tiempo)
* `backend/`: esqueleto para API, agentes, grafo, fuentes, RAG, revisor y render (aún sin código)
* `eval/`: conjunto de prueba del revisor y resultados (estructura lista, sin datos aún)
* `deploy/`: Nginx y OCI (estructura lista, sin configuración aún)
* `docs/`: decisiones, roadmap y licencias
* `tools/`: herramientas de apoyo (`render_spike.py`, experimento de renderizado)

### Regla de dependencia

`frontend` y `backend` solo se comunican a través de `contracts/`.

### Cómo correrlo

```powershell
# Valida los contratos (desde la raíz del repo)
pip install -r requirements.txt
python contracts\validate.py

# Frontend
cd frontend
npm install
npm run dev      # servidor de desarrollo (Vite, normalmente http://localhost:5173)
npm test         # 195 pruebas
npx tsc --noEmit # chequeo de tipos
```

El validador comprueba: esquemas JSON Schema 2020-12 bien formados, `$comment` en cada bloque, ejemplos de entrada válidos e inválidos, ficha de plantilla, kit de marca (con contrastes recalculados) y la secuencia grabada (orden por `seq`, causas, citas literales contra la fuente y sello de revisión).

### Regenerar la grabación

La grabación se genera, no se edita a mano:

```powershell
python contracts\recordings\gen_grabacion.py
python contracts\validate.py
```

### Licencia

MIT. Las fuentes conservan su propia licencia OFL (ver `templates/typography/` y `docs/licencias.md`).

---

## English

### What it is

Four agents collaborate on a 6-slide carousel from a source document:

- **Strategist:** defines the angle, tone and role of each slide.
- **Writer:** drafts the text for each slide.
- **Art director:** picks the template, paints backgrounds and writes text on the canvas.
- **Reviewer:** checks each claim against the source with a literal quote.

A human edits and approves at the end.

### Highlights

- **Fidelity reviewer that catches invented figures.** In the demo scene, the writer says the Daily Scrum lasts 30 minutes, while the source says 15. The reviewer flags it with the exact quote, the text is corrected on screen, the claim is re-verified, and the run is sealed (2 of 2 claims backed).
- **Live canvas with avatars.** Each agent has an avatar that moves to where it works and shows what it is doing.
- **Event contract with validation.** Everything is an event with a common envelope, validated with JSON Schema (ajv in the frontend, Python in `contracts/validate.py`), including negative tests that must be rejected.
- **Deterministic timeline.** A pure reducer turns events into state; an orderer detects gaps, duplicates and mixed runs; a player supports pause, 1x/2x speed and seek.

### Status

- **Phase 0 (Foundations):** closed. Contracts, schemas, template, brand kit and validator.
- **Phase 1 (Canvas):** in progress. The frontend already replays a recorded 24-event sequence (`contracts/recordings/b5_cifra_inventada.json`) with animated agents, a visible reviewer correction and a findings card. Final controls, thumbnails and the demo video are still missing.
- **Phase 2 (Real agents):** pending. The backend currently has only the folder skeleton.

See `SPEC.md` for decisions, input schema and folder structure, and `docs/roadmap.md` for the phases.

### Structure

* `contracts/`: shared schemas (events, input, template sheet, brand kit), recorded sequences and `validate.py`
* `templates/`: templates, palettes, typography (Inter and JetBrains Mono, both OFL), styles and brand kit
* `frontend/`: Vite + React + TypeScript app (canvas, avatars, timeline)
* `backend/`: skeleton for API, agents, graph, sources, RAG, reviewer and render (no code yet)
* `eval/`: reviewer test set and results (structure ready, no data yet)
* `deploy/`: Nginx and OCI (structure ready, no configuration yet)
* `docs/`: decisions, roadmap and licenses
* `tools/`: support tools (`render_spike.py`, a rendering experiment)

### Dependency rule

`frontend` and `backend` communicate only through `contracts/`.

### Run it

```bash
# Validate the contracts (from the repo root)
pip install -r requirements.txt
python contracts/validate.py

# Frontend
cd frontend
npm install
npm run dev      # dev server (Vite, usually http://localhost:5173)
npm test         # 195 tests
npx tsc --noEmit # type check
```

The validator checks: well-formed JSON Schema 2020-12 files, `$comment` in every block, valid and invalid input examples, template sheet, brand kit (with recomputed contrasts) and the recorded sequence (order by `seq`, causes, literal quotes against the source, and review seal).

### Regenerate the recording

The recording is generated, not edited by hand:

```bash
python contracts/recordings/gen_grabacion.py
python contracts/validate.py
```

### License

MIT. Fonts keep their own OFL license (see `templates/typography/` and `docs/licencias.md`).

