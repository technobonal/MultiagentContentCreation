# MultiagentContentCreation

Plataforma de agentes que convierte una fuente técnica (PDF, URL, documento) en un carrusel de Instagram, con un revisor editorial explicable que verifica la fidelidad a la fuente. Un renderizador determinista dibuja el diseño en vivo mientras los agentes trabajan.

Estado: **Fase 0 (fundamentos)**. Ver `SPEC.md` para decisiones, esquema de entrada y estructura de carpetas, y `docs/roadmap.md` para las fases.

## Estructura

* `contracts/`: esquemas compartidos (eventos, entrada, ficha de plantilla, kit de marca), secuencias grabadas y `validate.py`
* `templates/`: plantillas, paletas, tipografías, estilos y kit de marca
* `backend/`: API, agentes, grafo, fuentes, revisor, render (aún vacío; Fase 1 en adelante)
* `frontend/`: lienzo, línea de tiempo, controles, panel de revisión (aún vacío)
* `eval/`: conjunto de prueba del revisor y resultados
* `deploy/`: Nginx y OCI
* `docs/`: decisiones, roadmap y licencias

## Regla de dependencia

`frontend` y `backend` solo se comunican a través de `contracts/`.

## Validar los contratos

```
pip install -r requirements.txt
python contracts/validate.py
```

El validador comprueba: esquemas JSON Schema 2020-12 bien formados, `$comment` en cada bloque, ejemplos de entrada válidos e inválidos, ficha de plantilla, kit de marca (con contrastes recalculados) y la secuencia grabada (orden por `seq`, causas, citas literales contra la fuente y sello de revisión).


# MultiagentContentCreation

**EN** · A multi-agent system that turns a source document into a social-media carousel, **verifies every claim against the source**, and lets you watch the whole process live on a canvas. · **ES** · [Ir a español](#español)

## English

### What it is

Four agents collaborate on a 6-slide Instagram carousel:

- **Strategist** defines the angle, tone and slide roles.
- **Writer** drafts the text for each slide.
- **Art director** picks the template, paints backgrounds and writes text on the canvas.
- **Reviewer** checks each claim against the source with a literal quote.

A human edits and approves at the end.

### Highlights

- **Fidelity reviewer that catches invented figures.** The demo scene: the writer says the Daily Scrum lasts 30 minutes, the source says 15. The reviewer flags it with the exact quote, the text is corrected on screen, the claim is re-verified, and the run is sealed (2 of 2 claims backed).
- **Live canvas with avatars.** Each agent has an avatar that moves to where it works (a text field, a background corner, an underlined claim) and shows what it is doing.
- **Event contract with validation.** Everything is an event with a common envelope, validated with JSON Schema (ajv in the frontend, Python in `contracts/validate.py`), including negative tests that must be rejected.
- **Deterministic timeline.** A pure reducer turns events into state; an orderer detects gaps, duplicates and mixed runs; a player supports pause, 1x/2x speed and seek.

### Status

Phase 1 is complete: the frontend replays a recorded 24-event sequence (`contracts/recordings/b5_cifra_inventada.json`). Live agent streaming is not connected yet.

### Structure

| Folder | Contents |
|---|---|
| `contracts/` | JSON Schemas, event catalog, recordings, validator |
| `frontend/` | Vite + React + TypeScript app (canvas, avatars, timeline) |
| `templates/` | Slide templates and typography (Inter, JetBrains Mono, both OFL) |

### Run it

```bash
# Validate the contract (from the repo root)
python contracts/validate.py

# Frontend
cd frontend
npm install
npm run dev      # dev server (Vite, usually http://localhost:5173)
npm test         # 195 tests
npx tsc --noEmit # type check
```

### Regenerate the recording

The recording is generated, not edited by hand:

```bash
python contracts/recordings/gen_grabacion.py
python contracts/validate.py
```

### License

MIT. Fonts keep their own OFL license (see `templates/typography/`).

---

## Español

### Qué es

Cuatro agentes colaboran en un carrusel de Instagram de 6 slides a partir de un documento fuente:

- **Estratega:** define el ángulo, el tono y el rol de cada slide.
- **Redactor:** escribe el texto de cada slide.
- **Director de arte:** elige la plantilla, pinta los fondos y escribe los textos en el lienzo.
- **Revisor:** verifica cada afirmación contra la fuente con una cita literal.

Al final, una persona edita y aprueba.

### Lo destacado

- **Revisor de fidelidad que atrapa cifras inventadas.** La escena de la demo: el redactor dice que el Daily Scrum dura 30 minutos y la fuente dice 15. El revisor lo marca con la cita exacta, el texto se corrige en pantalla, se vuelve a verificar y la ejecución queda sellada (2 de 2 afirmaciones respaldadas).
- **Lienzo en vivo con avatares.** Cada agente tiene un avatar que se mueve a donde trabaja (un campo de texto, una esquina del fondo, una afirmación subrayada) y muestra lo que hace.
- **Contrato de eventos con validación.** Todo es un evento con un sobre común, validado con JSON Schema (ajv en el frontend, Python en `contracts/validate.py`), con pruebas negativas que deben rechazarse.
- **Línea de tiempo determinista.** Un reductor puro convierte eventos en estado; un ordenador detecta huecos, duplicados y runs mezclados; un reproductor permite pausa, velocidad 1x/2x y salto.

### Estado

La Fase 1 está completa: el frontend reproduce una secuencia grabada de 24 eventos (`contracts/recordings/b5_cifra_inventada.json`). Aún no está conectado el flujo en vivo de los agentes.

### Estructura

| Carpeta | Contenido |
|---|---|
| `contracts/` | Esquemas JSON, catálogo de eventos, grabaciones, validador |
| `frontend/` | App Vite + React + TypeScript (lienzo, avatares, línea de tiempo) |
| `templates/` | Plantillas de slides y tipografía (Inter, JetBrains Mono, ambas OFL) |

### Cómo correrlo

```powershell
# Valida el contrato (desde la raíz del repo)
python contracts\validate.py

# Frontend
cd frontend
npm install
npm run dev      # servidor de desarrollo (Vite, normalmente http://localhost:5173)
npm test         # 195 pruebas
npx tsc --noEmit # chequeo de tipos
```

### Regenerar la grabación

La grabación se genera, no se edita a mano:

```powershell
python contracts\recordings\gen_grabacion.py
python contracts\validate.py
```

### Licencia

MIT. Las fuentes conservan su propia licencia OFL (ver `templates/typography/`).

# MultiagentContentCreation

**EN** · A multi-agent system that turns a source document into a social-media carousel, **verifies every claim against the source**, and lets you watch the whole process live on a canvas. · **ES** · [Ir a español](#español)

## English

### What it is

Four agents collaborate on a 6-slide Instagram carousel:

- **Strategist** defines the angle, tone and slide roles.
- **Writer** drafts the text for each slide.
- **Art director** picks the template, paints backgrounds and writes text on the canvas.
- **Reviewer** checks each claim against the source with a literal quote.

A human edits and approves at the end.

### Highlights

- **Fidelity reviewer that catches invented figures.** The demo scene: the writer says the Daily Scrum lasts 30 minutes, the source says 15. The reviewer flags it with the exact quote, the text is corrected on screen, the claim is re-verified, and the run is sealed (2 of 2 claims backed).
- **Live canvas with avatars.** Each agent has an avatar that moves to where it works (a text field, a background corner, an underlined claim) and shows what it is doing.
- **Event contract with validation.** Everything is an event with a common envelope, validated with JSON Schema (ajv in the frontend, Python in `contracts/validate.py`), including negative tests that must be rejected.
- **Deterministic timeline.** A pure reducer turns events into state; an orderer detects gaps, duplicates and mixed runs; a player supports pause, 1x/2x speed and seek.

### Status

Phase 1 is complete: the frontend replays a recorded 24-event sequence (`contracts/recordings/b5_cifra_inventada.json`). Live agent streaming is not connected yet.

### Structure

| Folder | Contents |
|---|---|
| `contracts/` | JSON Schemas, event catalog, recordings, validator |
| `frontend/` | Vite + React + TypeScript app (canvas, avatars, timeline) |
| `templates/` | Slide templates and typography (Inter, JetBrains Mono, both OFL) |

### Run it

```bash
# Validate the contract (from the repo root)
python contracts/validate.py

# Frontend
cd frontend
npm install
npm run dev      # dev server (Vite, usually http://localhost:5173)
npm test         # 195 tests
npx tsc --noEmit # type check
```

### Regenerate the recording

The recording is generated, not edited by hand:

```bash
python contracts/recordings/gen_grabacion.py
python contracts/validate.py
```

### License

MIT. Fonts keep their own OFL license (see `templates/typography/`).

---

## Español

### Qué es

Cuatro agentes colaboran en un carrusel de Instagram de 6 slides a partir de un documento fuente:

- **Estratega:** define el ángulo, el tono y el rol de cada slide.
- **Redactor:** escribe el texto de cada slide.
- **Director de arte:** elige la plantilla, pinta los fondos y escribe los textos en el lienzo.
- **Revisor:** verifica cada afirmación contra la fuente con una cita literal.

Al final, una persona edita y aprueba.

### Lo destacado

- **Revisor de fidelidad que atrapa cifras inventadas.** La escena de la demo: el redactor dice que el Daily Scrum dura 30 minutos y la fuente dice 15. El revisor lo marca con la cita exacta, el texto se corrige en pantalla, se vuelve a verificar y la ejecución queda sellada (2 de 2 afirmaciones respaldadas).
- **Lienzo en vivo con avatares.** Cada agente tiene un avatar que se mueve a donde trabaja (un campo de texto, una esquina del fondo, una afirmación subrayada) y muestra lo que hace.
- **Contrato de eventos con validación.** Todo es un evento con un sobre común, validado con JSON Schema (ajv en el frontend, Python en `contracts/validate.py`), con pruebas negativas que deben rechazarse.
- **Línea de tiempo determinista.** Un reductor puro convierte eventos en estado; un ordenador detecta huecos, duplicados y runs mezclados; un reproductor permite pausa, velocidad 1x/2x y salto.

### Estado

La Fase 1 está completa: el frontend reproduce una secuencia grabada de 24 eventos (`contracts/recordings/b5_cifra_inventada.json`). Aún no está conectado el flujo en vivo de los agentes.

### Estructura

| Carpeta | Contenido |
|---|---|
| `contracts/` | Esquemas JSON, catálogo de eventos, grabaciones, validador |
| `frontend/` | App Vite + React + TypeScript (lienzo, avatares, línea de tiempo) |
| `templates/` | Plantillas de slides y tipografía (Inter, JetBrains Mono, ambas OFL) |

### Cómo correrlo

```powershell
# Valida el contrato (desde la raíz del repo)
python contracts\validate.py

# Frontend
cd frontend
npm install
npm run dev      # servidor de desarrollo (Vite, normalmente http://localhost:5173)
npm test         # 195 pruebas
npx tsc --noEmit # chequeo de tipos
```

### Regenerar la grabación

La grabación se genera, no se edita a mano:

```powershell
python contracts\recordings\gen_grabacion.py
python contracts\validate.py
```

### Licencia

MIT. Las fuentes conservan su propia licencia OFL (ver `templates/typography/`).