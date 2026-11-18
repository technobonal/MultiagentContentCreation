# Roadmap por fases

Tope para la Fase 0: **3 días**. Más papel no baja el riesgo; ejecutar sí.

| Fase | Contenido | Criterio de salida | Estado |
| ---- | --------- | ------------------ | ------ |
| 0. Fundamentos | Contratos mínimos (15 eventos), esquema de entrada, ficha de plantilla, kit de marca, secuencia grabada, validador | `python contracts/validate.py` pasa sin fallas | Cerrada (2026-11-13) |
| 1. Lienzo | Lienzo SVG que reproduce la secuencia grabada (marcada como desarrollo) y línea de tiempo | Se puede grabar un video del lienzo | Cerrada (2026-11-17) |
| 2. Agentes reales | Backend con SSE; estratega, redactor, director de arte y revisor con corrección visible | Un carrusel de punta a punta desde una fuente real | En curso |
| 3. Portfolio | 3 plantillas, caso estrella, README con demo en video y ejemplos antes y después, despliegue en OCI conHTTPS | Demo pública estable | Pendiente |
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

- [x] Modo Servidor en el lienzo (2026-11-18): conexión por SSE a `/api/runs/{run_id}/eventos`, estado de la conexión visible y error claro si el run no existe
- [x] Verificado a mano en pantalla (2026-11-18), con servidor y con grabación local: sello 2 de 2 en el slide de fuentes, reiniciar con el flujo terminado, pausar con el flujo en curso (el contador se detiene y el total sigue creciendo) y run inexistente
- [ ] Letrero y avatares con el slide real del evento (hoy dicen el slide elegido a mano, por ejemplo "Editando slide 6..." en el evento 22)
- [ ] Verificar la tarjeta del revisor al mirar un slide a mano entre los eventos 14 y 19
- [ ] Completar la grabación demo para que escriba los 6 slides (hoy los slides 2 y 5 quedan vacíos y atenuados)
- [ ] Estratega, redactor, director de arte y revisor reales, con corrección visible
- [ ] Un carrusel de punta a punta desde una fuente real

## Spike de fidelidad (en paralelo)

- v3b válido (ver `decisiones.md`).
- Pendiente v4: defectos sutiles S1 a S8 (criterio propuesto ≥ 6 de 8, con recall de las "no dice" S1, S2, S5 por separado) y una segunda fuente.