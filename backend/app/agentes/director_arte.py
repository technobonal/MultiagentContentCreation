"""Director de arte (paso 3, MVP): decide qué se dibuja en el lienzo y en qué orden. Sin LLM.

Es determinista a propósito: no gasta tokens, no puede inventar nada y siempre produce
eventos válidos según el contrato. El LLM entrará más adelante, cuando haya que elegir
imágenes o variar la composición.

Por cada slide emite, en este orden:
1. `colocar_fondo`: el color de fondo del kit de marca (un evento por slide).
2. `escribir_texto`: un evento por cada campo que escribió el redactor, en el orden de la ficha.

Los campos que no escribe el LLM (imagen del usuario, atribución, licencia y sello) no pasan
por aquí: los resuelve el lienzo con campos calculados.

Este módulo devuelve eventos "desnudos" (`EventoArte`). El orquestador les pone el sobre
(run_id, seq, timestamp, origen) y los emite; así el director de arte no depende del canal.

Entrada:  la resolución (ficha), el kit de marca (dict ya validado) y los `TextoSlide` del redactor.
Salida:   una lista de `EventoArte` lista para emitir.
"""

import re
from dataclasses import dataclass
from typing import Any

from app.agentes.comun import AgenteError
from app.agentes.redactor import TextoSlide, campos_del_redactor

# Valor del campo `agente` de los eventos que emite este módulo (contrato de colocar_fondo y escribir_texto).
AGENTE = "director_arte"

# Tope del contrato `texto` (common.schema.json): un evento con más caracteres no valida.
TEXTO_MAX_CONTRATO = 400

# Color en hexadecimal de 6 dígitos con almohadilla (contrato `color_hex`).
_COLOR_HEX = re.compile(r"#[0-9A-Fa-f]{6}")

# Nombre de campo sin llaves (contrato `nombre_campo`).
_NOMBRE_CAMPO = re.compile(r"[a-z][a-z0-9_]{0,30}")


@dataclass(frozen=True)
class EventoArte:
    """Evento del director de arte sin sobre: tipo, slide y payload ya conformes al contrato."""

    tipo: str  # "colocar_fondo" o "escribir_texto"
    slide: int
    payload: dict
    agente: str = AGENTE


def payload_fondo(kit: Any) -> dict:
    """Payload de `colocar_fondo` con el color de fondo del kit de marca.

    Lanza AgenteError `kit_invalido` si el kit no trae un color de fondo hexadecimal.
    """
    paleta = kit.get("paleta") if isinstance(kit, dict) else None
    color = paleta.get("fondo") if isinstance(paleta, dict) else None
    # Sin un color válido el lienzo no sabría qué dibujar: se informa en lugar de adivinar un fondo.
    if not isinstance(color, str) or not _COLOR_HEX.fullmatch(color):
        raise AgenteError("kit_invalido", "El kit de marca no tiene una paleta.fondo en hexadecimal (#RRGGBB).")
    return {"fondo": {"tipo": "color", "valor": color}}


def componer_slide(slide_ficha: dict, kit: Any, texto: TextoSlide | None) -> list[EventoArte]:
    """Eventos de un slide: primero el fondo y después un `escribir_texto` por campo.

    `texto` es None (o no trae campos) cuando el slide aún no tiene redacción o no la necesita
    (el de fuentes): entonces solo se coloca el fondo.
    Lanza AgenteError `campo_desconocido` o `texto_invalido` si el texto no cumple el contrato.
    """
    numero = slide_ficha["numero"]
    eventos = [EventoArte("colocar_fondo", numero, payload_fondo(kit))]
    # Sin redacción no hay nada más que dibujar en este slide.
    if texto is None:
        return eventos

    # Solo se aceptan los campos que la ficha reserva al redactor (no imágenes ni calculados).
    permitidos = {nombre for nombre, _ in campos_del_redactor(slide_ficha)}
    # Un evento por campo, respetando el orden en que llegó la redacción (el de la ficha).
    for nombre, valor in texto.campos.items():
        # Un campo fuera de la ficha sería un desajuste entre redactor y plantilla.
        if nombre not in permitidos or not _NOMBRE_CAMPO.fullmatch(nombre):
            raise AgenteError(
                "campo_desconocido",
                f"El slide {numero} no tiene el campo «{nombre}» entre los que escribe el redactor.",
            )
        limpio = valor.strip() if isinstance(valor, str) else ""
        # El contrato exige texto no vacío y de hasta 400 caracteres.
        if not limpio or len(limpio) > TEXTO_MAX_CONTRATO:
            raise AgenteError(
                "texto_invalido",
                f"El texto del campo «{nombre}» (slide {numero}) debe tener entre 1 y {TEXTO_MAX_CONTRATO} caracteres.",
            )
        eventos.append(EventoArte("escribir_texto", numero, {"campo": nombre, "texto": limpio}))
    return eventos


def componer_carrusel(resolucion, kit: Any, textos: dict[int, TextoSlide]) -> list[EventoArte]:
    """Eventos de todo el carrusel, slide por slide en el orden de la ficha.

    `textos` mapea número de slide -> `TextoSlide` (puede estar incompleto). Lanza AgenteError
    `slide_desconocido` si trae un slide que la ficha no tiene.
    """
    numeros = {s["numero"] for s in resolucion.ficha["slides"]}
    sobrantes = sorted(set(textos) - numeros)
    # Una redacción para un slide inexistente indica un desajuste entre redactor y ficha.
    if sobrantes:
        raise AgenteError("slide_desconocido", f"Hay textos para slides que la ficha no tiene: {sobrantes}.")

    eventos: list[EventoArte] = []
    # Cada slide aporta su fondo y, si ya tiene redacción, sus textos.
    for slide_ficha in resolucion.ficha["slides"]:
        eventos.extend(componer_slide(slide_ficha, kit, textos.get(slide_ficha["numero"])))
    return eventos