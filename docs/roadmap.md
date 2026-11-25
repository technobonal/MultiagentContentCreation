# Roadmap por fases

Tope para la Fase 0: **3 días**. Más papel no baja el riesgo; ejecutar sí.

| Fase | Contenido | Criterio de salida | Estado |
| ---- | --------- | ------------------ | ------ |
| 0. Fundamentos | Contratos mínimos (15 eventos), esquema de entrada, ficha de plantilla, kit de marca, secuencia grabada, validador | `python contracts/validate.py` pasa sin fallas | Cerrada (2026-11-13) |
| 1. Lienzo | Lienzo SVG que reproduce la secuencia grabada (marcada como desarrollo) y línea de tiempo | Se puede grabar un video del lienzo | Cerrada (2026-11-17) |
| 2. Agentes reales | Backend con SSE; estratega, redactor, director de arte y revisor con corrección visible | Un carrusel de punta a punta desde una fuente real | En curso (1er run real ~8 min el 2026-11-22; `run_6367a164` en 80.6 s el 2026-11-23; faltan velocidad estable, PDFs y fotos) |
| 3. Portfolio | 3 plantillas, caso estrella, README con demo en video y ejemplos antes y después, despliegue en OCI con HTTPS | Demo pública estable | Pendiente |
| 4. Catálogo y segunda red | 10 a 15 plantillas, RAG con Chroma y Cohere, LinkedIn como configuración, bloques de código, PDF para LinkedIn | Panel de candidatas funcionando | Pendiente |
| 5. Producto | Kit de marca por usuario, "trae tu plantilla", exportación a Penpot, publicación como borrador vía intermediario | Señales de validación positivas | Pendiente |
| 6. Ciclo cerrado | Analítica de vuelta al estratega, programación, más redes, aprendizaje desde las ediciones del humano | Uso y pago medidos | Pendiente |

## Principio: el LLM solo donde hace falta juicio de lenguaje (2026-11-23)

Todo lo que no requiera un LLM se resuelve con código; así bajan las llamadas y la espera del limitador, que en el run medido era cerca del 93 % del tiempo total (y en `run_6367a164` representó 52.2 s de 80.6 s).

- **Solo código:** carga de fuentes, extracción de PDF, OCR, fragmentado, director de arte (plantilla, fondo, ajuste de texto), `verificar_hechos`, `revisor_codigo` (citas literales y cifras), orquestador, eventos, límites, sello y render.
- **Con LLM:** estratega (qué ideas y qué gancho por slide), redactor (textos cortos con cita literal), revisor de fidelidad (solo los casos que `revisor_codigo` no puede decidir), reescritura del ciclo de corrección. Opcional: visión para desempatar qué foto va a qué slide.
- **Cascada de modelos Groq:** `openai/gpt-oss-120b` → `openai/gpt-oss-20b` → `qwen/qwen3.8-27b` (qwen al final y con log de cualquier falla de modo JSON; ya verificado con `json=True` y `finish=stop` en `run_6367a164`). Decisión pendiente de Frank: si el revisor puede saltar de modelo solo cuando el suyo no tiene cupo (queda en el log con `fallback=True` y el modelo que verificó) o se mantiene sin fallback como en el spike v3b.
- **Ciclo de corrección y chequeo de cifras:** cada corrección reescribe el slide completo reutilizando `redactor.md` (~3.4k tokens por slide corregido entre redacción/corrección y re-revisión). Revisar falsos positivos de cifras (`mayor` en `revisor_fidelidad.py`) y hallazgos persistentes entre rondas (`h4` en `run_6367a164`) para evitar rondas extra.
- La mejora de velocidad (de ~365 s a 30-60 s) es una **estimación** hasta medirla con el log de tiempos; el techo real lo fija el TPM de la cuenta de Groq.

## LangGraph: cuándo entra

LangGraph entra en la **Fase 2, después de que existan el revisor y el ciclo de corrección**, y no antes: mientras el flujo es lineal (estratega, redactor, director de arte) un grafo solo añade capas. Reemplaza únicamente el pegamento del orquestador: cada agente actual (`generar_brief`, `redactar_slide`, `componer_carrusel`, revisor) se envuelve como un nodo, y el ciclo revisar, corregir y re-revisar pasa a ser una arista condicional con tope de 3 rondas. El contrato de eventos, `ClienteLLM` (limitador y fallback), el emisor SSE y los tests existentes no cambian, y solo se agrega la dependencia `langgraph`. Se activa con `ORQUESTADOR=grafo`, con `lineal` como valor por defecto, y se da por válido cuando una prueba de paridad con cliente falso produce la misma secuencia de eventos en ambos modos.

**Estado (2026-11-22):** el revisor y el ciclo de corrección ya existen en el orquestador lineal (`orquestador_real.py`), así que la condición de entrada se cumple. Todavía no se empezó `grafo.py`. Decisión pendiente: hacerlo ahora o esperar al HITL real, porque hoy `aprobacion_solicitada` no pausa nada y el grafo aportaría poco sin esa pausa (el grafo sí se justifica con la espera de la persona, vía interrupt).

## Checklist de la Fase 0

- [x] Esquema de entrada en `contracts/input` con ejemplos válidos e inválidos
- [x] Sobre de eventos y catálogo 0.1 (15 eventos)
- [x] Secuencia grabada válida contra el esquema
- [x] Ficha de plantilla definida (`card.json` de la plantilla de pasos)
- [x] Kit de marca del MVP definido
- [x] `template.svg` renderizable de la plantilla de pasos
- [x] Reglas del canal acordadas: SSE, reanudación por `seq`, validación (pruebas de reanudación e idempotencia diferidas al reductor del frontend, Fase 1)
- [x] Caso estrella elegido y licencia confirmada (Scrum Guide 2020, CC BY-SA 4.0; ver `docs/licencias.md`)

## Checklist de la Fase 1

- [x] Paso 1: tipos, estado y reductor (`frontend/src/timeline`)
- [x] Paso 2: validación con ajv y carga de la grabación (`frontend/src/lib`)
- [x] Paso 3: ordenador por `seq`, reloj inyectable y reproductor
- [x] Paso 4a: ajuste de texto, fondo, sello, carga de plantilla, componente `Lienzo`, avatares vivos y mesa de agentes
- [x] Grabación `b5_cifra_inventada` con 24 eventos (un `colocar_fondo` por slide, fondo `#1E1B4B`) y pruebas alineadas
- [x] Tarjeta de hallazgos del revisor montada y verificada en pantalla
- [x] Paso 4b: controles definitivos (reproducir/pausar, reiniciar, velocidad 1x/2x/3x, seek) y tira de miniaturas (clic en la miniatura salta al primer evento que le da contenido a ese slide; slides sin contenido, ni eventos ni campos calculados, atenuados y no clicables)
- [x] Slide de fuentes y sello accesible a mano (2026-11-18): la miniatura se habilita con campos calculados (atribución, licencia, sello) aunque ningún evento la active; la selección se suelta al llegar un evento nuevo, al reiniciar o al mover el tiempo (`slideManual.ts`)
- [x] Retoques visuales: margen entre la tarjeta de hallazgos y el indicador de progreso; texto legible en la burbuja del revisor
- [x] Segunda grabación, más completa, para el video (cerrada: el video de demostración ya está hecho con `b5_cifra_inventada`)
- [x] Criterio de salida: grabar el video del lienzo

## Checklist de la Fase 2

### Hecho

- [x] Modo Servidor en el lienzo (2026-11-18): conexión por SSE a `/api/runs/{run_id}/eventos`, estado de la conexión visible y error claro si el run no existe
- [x] Verificado a mano en pantalla (2026-11-18), con servidor y con grabación local: sello 2 de 2 en el slide de fuentes, reiniciar con el flujo terminado, pausar con el flujo en curso (el contador se detiene y el total sigue creciendo) y run inexistente
- [x] Paso 1: orquestador, POST /api/runs, SSE en vivo y run_error (19 nov, 254 tests)
- [x] Paso 2, tramo 1: cargador de fuentes con OCR
- [x] Paso 2, tramo 2: cliente Groq con fallback y limitador de tokens (75 passed, 1 skipped)
- [x] Paso 2, tramo 3 (tandas 8A a 8D): estratega, redactor, director de arte y revisor (código y fidelidad) reales, con el ciclo de corrección y el sello calculado por código (`orquestador_real.py`, `sello.py`); probados con agentes falsos
- [x] Tanda 8E-1: contexto del modo real (`MODO_RUN`, `contexto_real.py`: cliente Groq y kit de marca construidos una vez al arrancar)
- [x] Tanda 8E-2 (2026-11-22): `POST /api/runs` despacha relleno o real, lifespan en `main.py` con cierre ordenado, `test_rutas_modo_real.py` y `test_lifespan_modo_real.py` (6 passed)
- [x] Tanda 8F (2026-11-22): tope global por run (`RUN_TIMEOUT_SEG`, 600 s, corta con `run_error`) y `aprobacion_solicitada` emitida siempre antes de `run_finalizada` (el run no espera a la persona); `test_orquestador_real.py` 21 passed
- [x] Tandas 9A y 9B-1/9B-2 (2026-11-22): reintento del redactor y memoria del modo JSON por modelo; `run_error` corta el SSE con tope de 20 reconexiones; fichas de agentes a "Terminado" o "Sin intervención" al cerrar el run (verificado en pantalla)
- [x] Arreglo de citas del redactor (2026-11-22, commit 30774b1): regla de copia exacta en `redactor.md`, `validar_ultimo` en `pedir_json` y descarte de citas no literales en el último intento
- [x] Frontend 9B-3 (2026-11-22): cierre de avatares (burbuja de cierre 3 s y vuelta a reposo) y `runFallido` conectado a `conexion === "error"`; `tsc` limpio, 247 tests
- [x] Primer run real de punta a punta (2026-11-22, `guia_scrum_sintetica.txt`, Groq): 82 eventos con ciclo de corrección, pero ~8 min (cerca del tope de 600 s); suite 745 passed, 1 skipped
- [x] Tanda 10A (2026-11-22): medición de tiempos por agente y por llamada a Groq (`cliente_llm.py`, `orquestador_real.py`, `test_medicion_tiempos.py`); 751 passed, 1 skipped. Hallazgo: las llamadas duran 1 a 5 s, pero casi todo el run es espera de cupo del limitador, y estratega y redactor caen en `fallback=True`
- [x] Prueba de `qwen/qwen3.8-27b` en modo JSON y diagnóstico de rondas en `run_6367a164` (2026-11-23): respuestas `json=True` / `finish=stop` confirmadas; detectados 52.2 s de espera de cupo (`corrector_3` y `revisor_2`), ~3.4k tokens por slide corregido y persistencia de hallazgo de cifra `h4` en slide 4

### En curso: tanda 2 (velocidad)

- [ ] Reserva de tokens realista por rol en el limitador (revisor ~1.700, redactor ~2.700) en lugar de entrada + `max_tokens` completo
- [ ] Revisar `GROQ_TPM` en `config.py` contra el límite real de la cuenta
- [ ] Cascada de tres modelos con ventana propia por modelo (ver principio arriba); decidir si el revisor puede saltar de modelo
- [x] Probar `qwen/qwen3.8-27b` con una llamada real en modo JSON antes de confiar en él como tercer escalón (verificado en `run_6367a164`)
- [ ] Prefiltro del revisor en código: el LLM solo ve los casos que `revisor_codigo` / `verificar_hechos` no pueden decidir
- [ ] Evaluar el chequeo de cifras (`mayor` en `revisor_fidelidad.py`) y el disparo/agrupación en `ciclo_correccion.py` / `redactor.md` para reducir falsos positivos y rondas extra
- [x] `reasoning_effort` bajo en los modelos gpt-oss (ya aplicado en `config.py` y `EXTRA_REVISOR`; verificado el 2026-11-25)
- [ ] Loguear por qué estratega y redactor caen en `fallback=True`
- [ ] Mejorar los estados de espera en el lienzo (hoy Estratega "Planificando…" y Revisor "En espera" quedan desactualizados durante la espera de cupo)
- [x] Límites de Groq verificados en la consola (2026-11-25): 8K TPM, 30 RPM y 200K tokens por día en `qwen/qwen3.8-27b`, `gpt-oss-120b` y `gpt-oss-20b`; `GROQ_TPM=8000` es correcto, así que la espera de cupo es real y el único camino es gastar menos tokens por run (~27K en `run_d95dcd67`, unos 7 runs completos por día y modelo)
- [x] Medición de dos runs reales (2026-11-25): `run_d95dcd67` en 71.7 s (51 s de espera de cupo, 45 s solo en `qwen` con el 20b también lleno) y `run_a3f9cf5c` en 14.8 s (sin espera, una sola ronda de corrección; no es comparable). Sin esperas un run cuesta unos 15 s de trabajo real
- [x] Cadena del redactor `qwen → gpt-oss-20b → gpt-oss-120b` (commit `a0f1daf`): el 120b entra solo si los otros dos no tienen cupo, y rompe la independencia con el revisor solo en ese caso (log con `fallback=True`). Se quita con `GROQ_FALLBACK_REDACTOR`. Falta confirmarlo con 2 o 3 runs seguidos que saturen la ventana
- [x] Repetición animada de un run guardado (2026-11-25): un run terminado se abría de golpe, sin animación. `GET /api/runs/{id}/eventos?ritmo=1|2|3` reenvía los eventos guardados con su brecha original (tope `BRECHA_MAX_SEG`) dividida por el ritmo; sin el parámetro nada cambia. En modo Servidor los botones 1x/2x/3x reconectan pidiendo ese ritmo (`emisor.py`, `rutas.py`, `fuenteEnVivo.ts`, `App.tsx`; 793 tests del backend y `fuenteEnVivo.test.ts` 21 passed)
- [x] Diagnóstico de la espera (2026-11-25, `run_480b9626` y `run_3f203c23`): la espera de ~50 s cae en `revisor_2` porque los tres modelos se llenan a la vez (la primera pasada del revisor usa ~8.3K tokens y los correctores saltan al 20b). Un run gastaba ~27K tokens y los tres modelos permiten ~21.6K por minuto con `GROQ_MARGEN=0.9`: un run entero no entraba en un minuto. Subir el margen a 0.95 no ayudó (68.9 s) y se descartó; el `.env` sigue en 0.9
- [x] Caché de Groq verificado (2026-11-25): la documentación dice que los tokens cacheados no cuentan contra el TPM, pero con esta cuenta los tres modelos devuelven `cached_tokens` vacío, así que el limitador cuenta bien. El prompt fijo pesa ~813 de los ~1.100 tokens de entrada de cada llamada, y el supuesto de que el redactor «aprovecha el caché» yendo slide por slide hoy no se cumple
- [x] Revisor agrupado (2026-11-25): `LLM_REVISOR_SLIDES_POR_LLAMADA=3` revisa varios slides en una llamada con formato `{"slides": [...]}`; cada slide conserva sus fragmentos y su cita se ubica solo en ellos. Un slide omitido o ilegible se revisa solo en otra llamada (nunca tumba el run). Primera pasada: de 5 llamadas y ~8.3K tokens a 2 llamadas y ~5.8K. `run_93613b0a`: **13.2 s** sin espera (~17.4K tokens por run). Un run lanzado segundos después de otro (`run_f65997ee`) sigue esperando ~52 s: con 8K TPM por modelo entra un run por minuto, y eso es un límite de la cuenta, no del código
- [ ] Prefiltro del revisor en código y recorte de `redactor.md`/`revisor.md`: solo si hace falta más de un run por minuto o el run con 3 rondas de corrección vuelve a pasar los ~21K tokens
- [ ] Medir el run completo con el log de tiempos y comparar con el objetivo (30-60 s, estimado)

### Pendiente

- [ ] Un carrusel de punta a punta desde una fuente real con tiempos aceptables: backend con `MODO_RUN=real` y `GROQ_API_KEY`, frontend en modo Servidor, fuente `.md` o `.txt`
- [x] Fuentes en PDF con texto (2026-11-25): `cargador_fuente.py` lee `.pdf` con PyMuPDF (texto plano, un párrafo por bloque separado por línea en blanco, une palabras cortadas por el ajuste de línea). El texto extraído es la referencia de las citas, igual que en `.md` y `.txt`. Topes propios: `PDF_MAX_BYTES` (10 MB, del archivo), `PDF_MAX_PAGINAS` (40) y el tope de texto de siempre (`FUENTE_MAX_BYTES`). Rechaza con código estable: `pdf_invalido`, `pdf_protegido`, `pdf_demasiadas_paginas`, `pdf_sin_texto`. Probado con PDF generados en los tests y con un PDF real de 12 páginas (publicación de la CNDH sobre el derecho a la salud, 24.851 caracteres, 30 fragmentos): `run_31c5bf86` terminó completo en 15.5 s. Hallazgos de esa prueba: (1) con una fuente larga el redactor copia pasajes de más de 300 caracteres; ahora la cita larga se descarta en el último intento en vez de abortar el run (mismo criterio que las citas no literales); (2) sello 14 de 26 afirmaciones respaldadas, bastante peor que con la guía sintética, probablemente por el ruido del PDF (palabras partidas como «dolen cia», títulos cortados en dos bloques, pie de página repetido) y por fragmentos largos; pendiente limpiar el texto extraído (encabezados y pies repetidos, números de página) y revisar por qué el revisor marca tantas como no respaldadas. Falta probar con la Guía de Scrum 2020
- [ ] Fuentes en PDF escaneado: conectar el OCR (`rapidocr`) en el mismo punto donde hoy se lanza `pdf_sin_texto`, script de prueba con las 16 cifras de `CTRL_BROCHURE_muestra.pdf` (páginas 3 y 4) y definir el fragmentado (prueba privada, licencia sin confirmar). Verificado el 2026-11-25: el archivo tiene 8 páginas, cada una es una sola imagen sin capa de texto, así que el cargador lo rechaza con `pdf_sin_texto` hasta que el OCR esté conectado
- [ ] Fuentes por URL y por tema (hoy el modo real responde 422 con mensaje explícito)
- [ ] Fotos de la fuente, todo en código y después del texto: `extraer_imagenes.py`, `filtrar_imagenes.py`, `asignar_fotos.py`, `licencia_imagen.py` (bloqueo por defecto y liberación solo con confirmación del cliente, con registro en ediciones y slide de fuentes), `recorte.py` (tipo "cover" en el hueco de la plantilla y zona segura; las figuras con cifras se insertan recortadas tal cual, nunca redibujadas) y enganche en `director_arte.py` (sin foto, la plantilla sale solo con texto)
- [ ] HITL real: endpoint de aprobación (aprobar o editar) y espera del run tras `aprobacion_solicitada`
- [ ] Letrero y avatares con el slide real del evento (hoy dicen el slide elegido a mano, por ejemplo "Editando slide 6..." en el evento 22)
- [ ] Verificar la tarjeta del revisor al mirar un slide a mano entre los eventos 14 y 19
- [ ] Test del temporizador de `AvataresVivos` (fake timers) y CSS de la burbuja de fallo sobre un avatar en reposo
- [ ] `grafo.py` con LangGraph y prueba de paridad (ver la sección de LangGraph)

## Spike de fidelidad (en paralelo)

- v3b válido (ver `decisiones.md`).
- Pendiente v4: defectos sutiles S1 a S8 (criterio propuesto ≥ 6 de 8, con recall de las "no dice" S1, S2, S5 por separado) y una segunda fuente.