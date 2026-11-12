# contracts/

Fuente de verdad compartida entre `backend` y `frontend`. Todo es JSON Schema 2020-12 con `$comment` en cada bloque (explica qué hace). Versión del contrato: **0.1** (0.x hasta cerrar la Fase 2).

```
python contracts/validate.py
```

## Archivos

| Ruta | Qué contiene |
| ---- | ------------ |
| `common.schema.json` | Tipos compartidos: ids, seq, agentes, veredictos, gravedad, dimensiones, colores, cita, sello |
| `events/envelope.schema.json` | Sobre común de todo evento |
| `events/event.schema.json` | Despachador: sobre + esquema propio según `tipo` |
| `events/<evento>.schema.json` | Un esquema por evento (15) |
| `input/input.schema.json` | Esquema de entrada con modos Auto/Fijo |
| `input/examples/` | Ejemplos `valido_*` (deben pasar) e `invalido_*` (deben rechazarse) |
| `template-card/card.schema.json` | Ficha de plantilla |
| `brand-kit/kit.schema.json` | Kit de marca |
| `recordings/` | Secuencias grabadas (`origen: grabado`), su fuente de texto y `gen_grabacion.py` |
| `validate.py` | Validador de todo lo anterior |

## Sobre del evento

| Campo | Descripción |
| ----- | ----------- |
| `version` | Versión del contrato (`0.1`) |
| `run_id` | Identificador de la ejecución |
| `seq` | Secuencia creciente dentro de la ejecución (desde 1) |
| `timestamp` | Momento de emisión (ISO 8601) |
| `origen` | `real` o `grabado` (el lienzo muestra marca visible si es grabado) |
| `agente` | `estratega`, `redactor`, `director_arte`, `revisor`, `sistema`, `humano` |
| `tipo` | Nombre del evento (catálogo siguiente) |
| `slide` | Slide afectado (obligatorio en los eventos de slide) |
| `causa` | `seq` del evento que originó este (obligatorio en correcciones) |
| `payload` | Datos propios de cada tipo |

## Catálogo 0.1 (15 eventos)

| Evento | Emisor | Datos clave | Notas |
| ------ | ------ | ----------- | ----- |
| `run_iniciada` | sistema | Entrada resuelta, verificación, atribución y licencia | La verificación la fija el sistema |
| `fuente_indexada` | sistema | Fragmentos, caracteres, sha256 | Huella de la fuente congelada |
| `brief_emitido` | estratega | Ángulo, tono, slides, tipo de mensaje, roles | Último rol siempre `fuentes` |
| `plantilla_elegida` | director_arte | Id, modo, motivo, confianza | |
| `texto_propuesto` | redactor | Slide, campo, texto | Una reescritura lleva `causa` = hallazgo |
| `colocar_fondo` | director_arte | Slide, color o imagen con licencia | |
| `escribir_texto` | director_arte | Slide, campo, texto | |
| `verificacion_fidelidad` | revisor | Afirmación, clasificación, veredicto, cita | Base del fact ledger |
| `hallazgo_abierto` | revisor | Dimensión, gravedad, evidencia, explicación, acción | |
| `hallazgo_corregido` | revisor | Id del hallazgo, resultado | `causa` = seq del hallazgo abierto |
| `corregir` | redactor / director_arte | Motivo, operación nueva | `causa` = seq del evento sustituido |
| `aprobacion_solicitada` | sistema | Estado de revisión, abiertos, sello | |
| `aprobada` | humano | Decisión | |
| `editada` | humano | Campo, texto antes, texto después | Diff para aprender (Fase 6) |
| `run_finalizada` | sistema | Estado final, referencia al fact ledger, sello | |

## Reglas del canal (B.4)

- **Entrega:** SSE. Al reconectar, el cliente informa el último `seq` y el servidor reenvía lo faltante.
- **Orden:** el lienzo aplica eventos estrictamente por `seq`; ante un hueco lo pide de nuevo y no dibuja con huecos.
- **Idempotencia:** aplicar dos veces el mismo `seq` no cambia el resultado.
- **Validación:** backend y frontend validan cada evento contra `events/event.schema.json`; un evento inválido muestra un error visible, nunca se ignora.
- **Eventos inmutables:** una corrección es otro evento que referencia al anterior en `causa`.
- **Tamaño:** límite por evento a definir al implementar; nunca se incluye la fuente completa.

## Dimensiones nuevas del revisor (0.1)

| Dimensión | Tipo | Gravedad inicial |
| --------- | ---- | ---------------- |
| `gancho_slide2` (el slide 2 funciona solo) | LLM | Mayor |
| `valor_guardable` (¿se guardaría o enviaría?) | LLM | Menor, hasta calibrar |
| `zona_segura` (el gancho sobrevive al recorte a cuadrado) | Código | Mayor |
| `atribucion_licencia` (slide de fuentes completo) | Código | Bloqueante |

## Para 0.x

`entrada_validada`, `conflicto_detectado`, `plantillas_candidatas`, `reintento_iniciado`, `rechazada` y los `exportacion_*` (Fase 5).
