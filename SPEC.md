# MultiagentContentCreation — SPEC v0.1

Estado: base para la Fase 0. Basado en el documento "MultiagentContentCreation version-7" y en las decisiones tomadas después de esa versión. Este archivo define contratos y estructura; los contratos ejecutables viven en `contracts/` y se comprueban con `python contracts/validate.py`.

Etiquetas: **[Decidido]**, **[Adoptado]** (recomendado, reversible hasta cerrar la Fase 1), **[Pendiente]**.

---

## 1. Qué es

Una plataforma de agentes que convierte una fuente (PDF, URL o documento técnico, y opcionalmente un tema) en un carrusel de Instagram listo para revisar. Los agentes deciden; un renderizador determinista, sin LLM, dibuja el diseño en vivo.

Diferenciador a demostrar: **revisor editorial explicable + fidelidad a la fuente**, medido contra un conjunto de prueba. La personalización amplia y "fuente a carrusel" son lo mínimo esperable, no el foso. Que ya existan verificadores de afirmaciones debilita un poco el "nadie hace esto"; lo defendible es la combinación: verificación integrada a un carrusel técnico en español y portugués, con puntaje explicable.

## 2. Decisiones

| Tema | Decisión | Estado |
| :--- | :------- | :----- |
| Objetivo | Portfolio con arquitectura de producto y alcance mínimo | Decidido |
| Red del MVP | Instagram, carrusel de 5 a 7 slides (incluye el slide de fuentes), 1080×1350 | Decidido |
| Arquitectura | Front-end React/Vite + backend Python/FastAPI. Sin Streamlit | Decidido |
| Canal de eventos | SSE | Adoptado |
| Animaciones | GSAP sobre SVG | Adoptado |
| Repositorio | Monorepo | Adoptado |
| Agentes | Estratega, Redactor, Director de arte, Revisor (LangGraph) | Decidido |
| Render | Plantillas HTML/SVG a PNG con Playwright | Decidido |
| Entrada | Documento (PDF, README), URL o tema | Decidido |
| Tema libre | En el portfolio solo si viene con una fuente (URL o PDF). Investigador autónomo en Fase 4 o 5 | Decidido |
| PDF | Se usa como contenido. PDF como manual de marca, Fase 5 | Decidido |
| Personalización | Cada parámetro es Auto o Fijo (sección 6) | Decidido |
| Tipografía | 8 a 10 combinaciones curadas. Fuentes propias, después | Decidido |
| "Trae tu plantilla" | Fase 5 | Decidido |
| Caso estrella | Guía de Scrum 2020, CC BY-SA 4.0 (atribución y compartir igual; ver `docs/licencias.md`) | Decidido |
| Identificadores | ASCII (`ajustar_tamano`) | Decidido |
| Versión del contrato | 0.x hasta cerrar la Fase 2 | Decidido |
| Idioma de salida | ES y PT-BR, nativo, no traducción | Decidido |
| Contratos | JSON Schema 2020-12 con `$comment` por bloque; fuente de verdad compartida | Decidido |
| Catálogo de eventos 0.1 | 17 eventos (ver `contracts/README.md`); `colocar_imagen` se sumó el 2026-11-25 y `rechazada` el 2026-11-26 | Decidido |
| Sello de revisión | Lo calcula código, nunca el LLM | Decidido |
| Destinos de edición (Penpot, Figma) | Exportación posterior a la aprobación vía DesignDoc y adaptadores; sin uso en vivo por los agentes; Fase 5, Penpot primero | Decidido (documentado) |

## 3. Alcance del portfolio

Dentro: una red, tres plantillas (lista de pasos, antes y después, comparativa), cuatro agentes, lienzo animado, revisor con conjunto de prueba, controles Auto/Fijo, foto de producto, PDF como contenido, slide final de fuentes y atribución, registro de las ediciones del humano.

Fuera por ahora: publicación, calendario, pagos, usuarios, LinkedIn, YouTube, video, bloques de código en slides (Fase 4), RAG de plantillas (solo con 10 o más), marca por usuario, plantillas subidas por usuarios, destinos de edición Penpot y Figma (Fase 5).

## 4. Estructura de carpetas

```
MultiagentContentCreation/
├── README.md
├── SPEC.md
├── requirements.txt
├── .gitignore
├── docs/                      # decisiones.md, roadmap.md, licencias.md
├── contracts/                 # fuente de verdad compartida backend/frontend
│   ├── validate.py            # valida esquemas, ejemplos, ficha, kit y secuencia grabada
│   ├── common.schema.json     # tipos compartidos
│   ├── events/                # sobre, despachador y un esquema por evento (15)
│   ├── input/                 # esquema de entrada y ejemplos (valido_* / invalido_*)
│   ├── template-card/         # esquema de la ficha de plantilla
│   ├── brand-kit/             # esquema del kit de marca
│   └── recordings/            # secuencias grabadas (origen "grabado") y su generador
├── templates/                 # catálogo, paletas, tipografías, estilos y kit de marca
├── backend/app/               # api, agents, graph, sources, rag, reviewer, render, events, resolution, adapters
├── frontend/src/              # canvas, timeline, controls, review, events, lib
├── eval/                      # evaluación del revisor (fuentes, piezas, etiquetas, resultados)
└── deploy/                    # nginx y oci
```

Regla de dependencia: `frontend` y `backend` solo se hablan a través de `contracts/`. El frontend no conoce a los agentes.

## 5. Contrato de eventos

El catálogo 0.1 tiene 15 eventos. El detalle (sobre, payloads, reglas del canal) está en `contracts/README.md` y en los esquemas de `contracts/events/`. Quedan para 0.x: `entrada_validada`, `conflicto_detectado`, `plantillas_candidatas`, `reintento_iniciado`, `rechazada` y los `exportacion_*` de la Fase 5.

## 6. Esquema de entrada (`contracts/input`)

Cada parámetro de diseño tiene `modo`: `auto` (decide el agente y explica por qué) o `fijo` (lo eligió el usuario; los agentes no lo tocan). El valor elegido viaja en `valor`.

### 6.1 Fuente

| Campo | Valores | Notas |
| :---- | :------ | :---- |
| `fuente.tipo` | `documento`, `url`, `tema` | `tema` exige también `fuente.tema` y una fuente asociada en `referencia` |
| `fuente.referencia` | archivo (`.pdf`, `.md`, `.txt`) o URL | Siempre obligatoria en el portfolio |
| `fuente.tema` | texto libre | Orienta el ángulo, no reemplaza la fuente |
| `fuente.idioma_salida` | `es`, `pt-BR` | |
| `fuente.atribucion` | texto | Obligatoria; alimenta el slide final de fuentes |
| `fuente.licencia` | texto | Obligatoria; alimenta el slide final de fuentes |
| `fuente.verificacion` | `verificada`, `sin_fuente_verificada` | La fija el sistema (viaja en `run_iniciada`); la entrada del usuario no puede incluirla |

### 6.2 Destino

| Campo | Valores |
| :---- | :------ |
| `destino.red` | `instagram` |
| `destino.formato` | `carrusel_1080x1350` |
| `destino.num_slides` | `{modo, valor}`, valor entre 5 y 7 |

### 6.3 Diseño

| Campo | Estructura |
| :---- | :--------- |
| `diseno.plantilla` | `{modo, valor}` con el id de la plantilla |
| `diseno.paleta` | `{modo, valor}` con un preset o con `{fondo, texto, acento, texto_sobre_acento}` |
| `diseno.tipografia` | `{modo, valor}` (solo combinaciones curadas) |
| `diseno.estilo` | `{modo, valor}` con un preset |

### 6.4 Recursos del usuario

`recursos.imagenes[]`: `{archivo, rol, licencia}`. `rol` apunta a un campo de imagen de la plantilla. Licencia por defecto: `usuario` (declara tener derechos).

## 7. Reglas de resolución

1. **Fijo gana sobre auto.** El Director de arte completa solo lo que está en auto.
2. **Fijo contra fijo que choca no se bloquea.** Se avisa y se propone una corrección. Ejemplo: paleta de bajo contraste sobre plantilla oscura genera un hallazgo del revisor (contraste, gravedad mayor). El usuario decide.
3. **Los imposibles se rechazan antes de empezar.** Ejemplo: plantilla fija de 6 slides con `num_slides` fijo en 5. Error de validación visible, nunca silencioso.
4. **Tema sin fuente** (portfolio): se rechaza con mensaje claro.
5. **Sin fuente verificada:** el pack se marca `sin_fuente_verificada` y siempre pasa por aprobación humana. No se simula verificación.
6. **Límites de entrada** (tamaño de PDF, páginas, imagen): se fijan al implementar y se validan en el borde.
7. **Foto de producto:** entra solo por un campo de imagen declarado en la ficha. Si la plantilla no tiene campo de imagen, el sistema lo informa.
8. Todo `modo: auto` resuelto emite un evento con el motivo de la decisión.

`contracts/validate.py` implementa hoy las reglas 3 (plantilla fija contra `num_slides` fijo y plantilla inexistente), 4 (tema sin fuente) y 7 (imagen sin campo declarado) como ejemplos de entrada inválidos. El resto se implementa en `backend/app/resolution/`.

## 8. Ficha de plantilla (`contracts/template-card`)

Roles de slide: `gancho`, `segundo_gancho`, `desarrollo`, `cierre` y `fuentes` (el último slide). Cada campo declara `origen_valor`: `llm` (lo redacta el modelo), `usuario` (viene de la entrada) o `calculado` (lo calcula código, como el sello de revisión). La zona segura (margen superior e inferior) es un límite blando que se calibra con el render real. `longitud_max` es una aproximación: la verdad es la medición sobre el render de Playwright.

## 9. Criterios para cerrar la Fase 0

Ver el estado en `docs/roadmap.md`.

- [x] Esquema de entrada en `contracts/input` con ejemplos válidos e inválidos
- [x] Sobre de eventos y catálogo congelados en 0.1
- [x] Secuencia grabada en `contracts/recordings`, válida contra el esquema
- [x] Ficha de plantilla definida
- [x] Kit de marca del MVP definido
- [x] Plantilla de Instagram completa y renderizable (`template.svg`)
- [x] Reglas del canal acordadas: SSE, reanudación por `seq`, validación (pruebas de reanudación e idempotencia diferidas al reductor del frontend, Fase 1)   
- [x] Caso estrella elegido y licencia confirmada (Scrum Guide 2020, CC BY-SA 4.0; ver `docs/licencias.md`)

## 10. Pendientes abiertos

Del revisor: escala de puntaje 0 a 5 o 0 a 3; mismo modelo o distinto del redactor; quién etiqueta el conjunto de prueba; umbrales definitivos; fidelidad por slide o sobre el pack completo.

De validación: V1 (entrevistas, reducidas a 5 o 10 personas técnicas tras publicar la demo) y V10 (licencias de imágenes y fuentes). Las demás verificaciones no bloquean el portfolio.

Del spike de fidelidad: v4 con defectos sutiles S1 a S8 y una segunda fuente.
