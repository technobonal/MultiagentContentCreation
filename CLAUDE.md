# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Proyecto en español: código, identificadores (ASCII, sin tildes: `ajustar_tamano`), comentarios, docstrings, commits y documentación van en español. Respondé en español.

## Qué es

Plataforma multiagente que convierte una fuente técnica en un carrusel de Instagram de 6 slides (1080×1350). Cuatro agentes (estratega, redactor, director de arte, revisor) emiten **eventos** que un lienzo SVG en React dibuja en vivo. El revisor verifica cada afirmación contra la fuente con una cita literal. Estado de las fases y tareas pendientes: `docs/roadmap.md` (fuente de verdad de en qué se está trabajando). Decisiones de diseño: `SPEC.md`.

## Comandos

Python usa el `.venv` de la raíz (Windows). Los tests del backend se corren **desde `backend/`** (`pytest.ini` pone `pythonpath = .` para importar `app`).

```powershell
# Contratos (desde la raíz)
python contracts\validate.py
python contracts\recordings\gen_grabacion.py   # regenera la grabación; nunca editar el JSON a mano

# Backend (desde backend/)
pytest                                          # suite completa
pytest tests/test_orquestador_real.py           # un archivo
pytest tests/test_sello.py::nombre_del_test     # un test
uvicorn app.main:app --reload --port 8000       # un solo worker siempre (runs en memoria)

# Frontend (desde frontend/)
npm run dev          # Vite en :5173; proxy /api -> 127.0.0.1:8000
npm test             # vitest run
npx vitest run src/timeline/reducer.test.ts     # un archivo
npx tsc --noEmit     # chequeo de tipos
```

`predev`/`prebuild` copian la plantilla SVG y las tipografías de `templates/` a `frontend/public/plantillas/` (`scripts/copiar-plantillas.mjs`). `templates/` es la única fuente de verdad: no editar las copias.

Variables de entorno (se leen en `backend/app/config.py`, que carga el `.env` de la raíz si está instalado `python-dotenv`): `MODO_RUN` (`relleno` por defecto, o `real`), `GROQ_API_KEY`, modelos y cascadas de fallback por rol (`GROQ_MODELO_*`, `GROQ_FALLBACK_*`), límites del limitador (`GROQ_TPM`, `GROQ_RPM`, `GROQ_TPM_POR_MODELO`) y `RUN_TIMEOUT_SEG`. `requirements.txt` no lista todo lo que usa el modo real (por ejemplo `groq` y `python-dotenv`).

## Arquitectura

**Regla de dependencia:** `frontend` y `backend` solo se comunican a través de `contracts/` (JSON Schema 2020-12, con `$comment` en cada bloque). Los dos validan cada evento contra `contracts/events/event.schema.json` (ajv en el frontend, `jsonschema` en `backend/app/events/validador.py`, con la misma carga de esquemas por `$id` que `contracts/validate.py`). Si cambiás un contrato, corré `validate.py` y las dos suites.

**Contrato de eventos** (`contracts/README.md`): 18 tipos con un sobre común (`run_id`, `seq` consecutivo desde 1, `origen` `real`/`grabado`, `agente`, `slide`, `causa`). Los eventos son inmutables: una corrección es un evento nuevo cuya `causa` apunta al `seq` original. Un evento inválido nunca se omite: produce un error visible y corta el flujo.

### Backend (`backend/app/`)

Flujo de un run: `POST /api/runs` (`api/rutas.py`) → `runs/registro.py` (registro en memoria con un buffer de eventos por run, una `Condition` despierta al SSE) → una corutina orquestadora → `GET /api/runs/{id}/eventos` (SSE con `id: <seq>`; se reanuda con `Last-Event-ID` o `?desde=`, ver `events/emisor.py`).

- El **modo** se decide una sola vez, en el lifespan de `main.py`: `app.state.contexto` es `None` en modo relleno y es un `ContextoReal` (cliente Groq y kit de marca, `runs/contexto_real.py`) en modo real. Las rutas solo miran si hay contexto.
- `runs/orquestador.py` + `runs/relleno.py`: guion simulado sin LLM (`origen: grabado`). `agentes/orquestador.py` es una copia idéntica que no usa nadie.
- `runs/orquestador_real.py`: estratega → redactor (slide por slide, en secuencia para aprovechar el caché por prefijo de Groq) → director de arte → `agentes/ciclo_correccion.py` (revisar → corregir → re-revisar, con un tope de 3 rondas) → `aprobacion_solicitada` → `run_finalizada`. Con `APROBACION_HUMANA` (encendida por defecto) el run espera la decisión de una persona (`POST /api/runs/{id}/aprobacion`, hasta `APROBACION_TIMEOUT_SEG`) y emite `editada`/`aprobada`, o `rechazada` (motivo obligatorio, estado final `rechazada`; se guarda en `backend/datos/rechazos.jsonl`, fuera de Git), antes de `run_finalizada`. `runs/semaforo.py` da verde o rojo por slide (`GET /api/runs/{id}/informe`); en rojo, aprobar exige `excepcion` con motivo y el run termina `aprobada_sin_visto_bueno` (también se guarda). Mientras espera, la persona puede re-verificar un slide sin cerrar el run (`POST /api/runs/{id}/reverificar`, A5): modo `edicion` (el revisor juzga el texto editado) o `agente` (el corrector reescribe y re-verifica); `_finalizar` es un lazo (`esperar_pedido`) con tope `REVERIF_MAX_RONDAS` (3). `runs/reverificacion.py` reconstruye los hallazgos abiertos y valida el pedido; reusa eventos existentes (sin cambios de contrato). El asesor (`agentes/asesor.py`, solo a pedido con `POST /api/runs/{id}/asesor`) usa Cloudflare Workers AI (Gemma 4 26B y Llama 3.3 70B de respaldo; solo modelos `@cf/`; `CLOUDFLARE_ACCOUNT_ID` y `CLOUDFLARE_API_KEY_TOKEN` en el `.env` de la raíz); sus alertas solo ponen en rojo y se acumulan.
- `agentes/ciclo_correccion.py` no conoce agentes ni a `Ejecucion`: todo entra por inyección. `agentes/adaptadores_ciclo.py` lo conecta con los agentes reales (`RevisorCarrusel`, `CorrectorCarrusel`). Solo el `redactor` corrige de verdad. Los otros responsables devuelven el **mismo objeto** de estado y así el ciclo detecta "sin cambios" y escala.
- `agentes/cliente_llm.py`: `ClienteGroq` con un limitador de TPM/RPM, cascada de modelos por rol y memoria del modo JSON por modelo. El fallback salta **solo por fallas técnicas** (429, 413, 5xx, timeout), nunca por una respuesta que no guste. El revisor usa su propia cadena (gpt-oss) y nunca cae al modelo del redactor. Los tests usan un cliente falso con la misma interfaz `completar`.
- `agentes/comun.py`: `AgenteError`, `cargar_prompt` (los prompts en `agentes/prompts/*.md` deben quedar idénticos byte a byte entre llamadas para el caché) y `pedir_json` (valida y reintenta).

**Principio:** el LLM se usa solo donde hace falta juicio de lenguaje (estratega, redactor, revisor de fidelidad y reescritura). Todo lo demás es código determinista: carga y fragmentado de la fuente (`fuentes/cargador_fuente.py`), director de arte, `verificar_hechos.py`, `revisor_codigo.py` (contraste WCAG, longitudes, estructura, atribución) y el **sello**.

**Invariantes de fidelidad:**
- El texto normalizado de la fuente es la única referencia: se cumple siempre `fuente.texto[inicio:fin] == cita`. Las citas se ubican con `ubicar_hecho`, que es literal pero tolera diferencias de espacios.
- Una cita no literal convierte un veredicto que respalda en `no_verificada`, que nunca abre un hallazgo.
- El sello, los hallazgos abiertos y el estado final los calcula `runs/sello.py` a partir de los eventos emitidos, **nunca el LLM**.
- Sin fuente verificada, el run sale `sin_fuente_verificada` y pasa por una persona. No se simula verificación.

`resolution.py` aplica las reglas cruzadas de la entrada (SPEC §7), las mismas que `contracts/validate.py`. Un test recorre `contracts/input/examples` para que las dos implementaciones no se separen. Las carpetas con solo `.gitkeep` (`graph`, `rag`, `render`, `reviewer`, `sources`, `adapters`) son espacio reservado para fases futuras.

Hoy las fuentes son archivos `.md`, `.txt` y `.pdf` de `backend/fuentes/`. Un PDF sin capa de texto se lee con OCR local (`fuentes/ocr_pdf.py`, `PDF_OCR=0` lo apaga); del PDF se quitan encabezados y pies repetidos. URL y tema responden 422.

### Frontend (`frontend/src/`)

- `timeline/`: lógica pura, sin React. `reducer.ts` es un reductor inmutable, idempotente por `seq` y estricto (`seq = ultimoSeq + 1`). `ordenador.ts` detecta huecos, duplicados y runs mezclados. `reproductor.ts` reproduce grabaciones (pausa, 1x/2x, salto). `fuenteEnVivo.ts` consume el SSE con la **misma interfaz que Reproductor**: ante un hueco reconecta con `?desde=`, y `run_error` o demasiadas reconexiones sin progreso cortan la conexión con un error.
- `lib/`: validación ajv contra los contratos y carga de las grabaciones de `contracts/recordings` (con `import.meta.glob`; por eso Vite tiene `fs.allow: [".."]`).
- `lienzo/`: componentes React y GSAP sobre la plantilla SVG. `App.tsx` elige entre la grabación local y el modo Servidor, y `Lienzo` no cambia entre las dos fuentes. Los campos calculados (atribución, licencia, sello) los dibuja el lienzo: el backend no los emite como `escribir_texto`.

## Convenciones

- Los agentes y módulos reciben sus dependencias por inyección (cliente LLM, `dormir`, funciones del revisor) para probarlos sin red ni esperas reales. Seguí ese patrón.
- El trabajo se organiza en "tandas" (8A, 9B-2, 10A…) registradas en `docs/roadmap.md`. Al cerrar una, actualizá su checklist.
- `.gitignore` ignora `*.txt`: una fuente nueva en `backend/fuentes/` hay que agregarla con `git add -f`. Los `.txt` sueltos de `backend/` (logs, dumps de firmas y contexto) son notas de trabajo y no se versionan.

## Instrucciones de Frank.

- Hacé cambios chicos, de una tanda por vez para ahorrar tokens
- utilza tus comandos para no revisar y rehacer todo el codigo como:
- Glob busca archivos por nombre o patrón, por ejemplo **/*.py o tests/test_*.py.
- Grep busca texto dentro de los archivos, por ejemplo dónde se usa pedir_json.
- cuando hagas los archivo a partir de ahora archivos o pruebas de esos archivos solo generas dos o tres archivos en cada intento y    - despues seguir generando para ahorrar token
- utiliza concise para responder breve
- En codigo siempre vas a tener el role Senior Software Engineer (optimizacion, arquitectura y eficiencia en codigo) y lo vas combinar con el foco del proyecto del momento, por ejemplo - - en este proyecto tambien sos especialista en creador de plataformas para creacion de contenido.
- compactar siempre el historial cuando el contexto se vuelve largo para ahorrar token