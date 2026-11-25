"""Aprobación humana (HITL): textos vigentes de un run y validación de la decisión de la persona.

Funciones puras, sin red ni estado: reciben los eventos ya emitidos y la ficha de la plantilla. Así se
prueban solas y las usan tanto el endpoint (para rechazar una decisión mala con un 422) como el orquestador
(para emitir los eventos `editada` y `aprobada`).

Reglas:
- Solo se editan los campos que el redactor escribió (los mismos de `campos_del_redactor`), con su límite de la ficha.
- El «texto_antes» sale de lo que ya está dibujado (último `escribir_texto` o `editada` del campo), nunca del cliente.
- Una edición que deja el texto igual se ignora; un mismo campo dos veces en la decisión es un error.
- Las ediciones NO se vuelven a verificar contra la fuente: el sello cubre solo lo que escribió el modelo.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agentes.redactor import campos_del_redactor

# Tope del contrato `texto` (common.schema.json): un evento con más caracteres no valida.
TEXTO_MAX_CONTRATO = 400


class DecisionInvalida(Exception):
    """La decisión de la persona no cumple las reglas; `motivos` va tal cual en la respuesta 422."""

    def __init__(self, motivos: list[str]):
        super().__init__("; ".join(motivos))
        self.motivos = motivos


@dataclass(frozen=True)
class Edicion:
    """Un campo editado a mano, con el texto de antes y el de después."""

    slide: int
    campo: str
    texto_antes: str
    texto_despues: str


@dataclass(frozen=True)
class Decision:
    """Decisión de la persona: ediciones (puede no haber) y comentario opcional. Siempre es una aprobación."""

    ediciones: tuple[Edicion, ...] = ()
    comentario: str | None = None


def textos_vigentes(eventos: Sequence[Mapping[str, Any]]) -> dict[tuple[int, str], str]:
    """Texto que hoy está dibujado en cada (slide, campo): el último `escribir_texto` o `editada`."""
    textos: dict[tuple[int, str], str] = {}
    for e in eventos:
        slide = e.get("slide")
        if not isinstance(slide, int):
            continue
        if e.get("tipo") == "escribir_texto":
            textos[(slide, e["payload"]["campo"])] = e["payload"]["texto"]
        elif e.get("tipo") == "editada":
            textos[(slide, e["payload"]["campo"])] = e["payload"]["texto_despues"]
    return textos


def _limites(ficha: Mapping[str, Any]) -> dict[tuple[int, str], int]:
    """Límite de caracteres de cada campo que escribe el redactor, según la ficha."""
    return {
        (s["numero"], nombre): min(maximo, TEXTO_MAX_CONTRATO)
        for s in ficha["slides"]
        for nombre, maximo in campos_del_redactor(s)
    }


def validar_decision(cuerpo: Any, eventos: Sequence[Mapping[str, Any]], ficha: Mapping[str, Any]) -> Decision:
    """Convierte el cuerpo del POST en una `Decision` o lanza `DecisionInvalida` con todos los motivos.

    Forma esperada: {"ediciones": [{"slide": 2, "campo": "cuerpo", "texto": "..."}], "comentario": "..."},
    con las dos claves opcionales.
    """
    if not isinstance(cuerpo, Mapping):
        raise DecisionInvalida(["El cuerpo debe ser un objeto JSON."])
    desconocidas = sorted(set(cuerpo) - {"ediciones", "comentario"})
    motivos: list[str] = [f"Clave desconocida: «{k}»." for k in desconocidas]

    comentario = cuerpo.get("comentario")
    if comentario is not None:
        if not isinstance(comentario, str):
            motivos.append("«comentario» debe ser un texto.")
            comentario = None
        else:
            comentario = comentario.strip() or None
            if comentario is not None and len(comentario) > TEXTO_MAX_CONTRATO:
                motivos.append(f"«comentario» supera {TEXTO_MAX_CONTRATO} caracteres ({len(comentario)}).")

    crudas = cuerpo.get("ediciones", [])
    if not isinstance(crudas, list):
        motivos.append("«ediciones» debe ser una lista.")
        crudas = []

    vigentes = textos_vigentes(eventos)
    limites = _limites(ficha)
    ediciones: list[Edicion] = []
    vistas: set[tuple[int, str]] = set()
    for i, cruda in enumerate(crudas, start=1):
        pos = f"Edición {i}:"
        if not isinstance(cruda, Mapping):
            motivos.append(f"{pos} debe ser un objeto con slide, campo y texto.")
            continue
        slide, campo, texto = cruda.get("slide"), cruda.get("campo"), cruda.get("texto")
        if isinstance(slide, bool) or not isinstance(slide, int) or not isinstance(campo, str) or not isinstance(texto, str):
            motivos.append(f"{pos} necesita «slide» (entero), «campo» (texto) y «texto» (texto).")
            continue
        clave = (slide, campo)
        if clave not in limites or clave not in vigentes:
            motivos.append(f"{pos} el slide {slide} no tiene un campo editable «{campo}».")
            continue
        if clave in vistas:
            motivos.append(f"{pos} el campo «{campo}» del slide {slide} aparece más de una vez.")
            continue
        vistas.add(clave)
        nuevo = texto.strip()
        if not nuevo:
            motivos.append(f"{pos} el texto de «{campo}» (slide {slide}) no puede quedar vacío.")
        elif len(nuevo) > limites[clave]:
            motivos.append(
                f"{pos} el texto de «{campo}» (slide {slide}) supera {limites[clave]} caracteres ({len(nuevo)})."
            )
        elif nuevo != vigentes[clave]:  # sin cambio real no hay edición: así no se emite una `editada` sin diferencia
            ediciones.append(Edicion(slide, campo, vigentes[clave], nuevo))

    if motivos:
        raise DecisionInvalida(motivos)
    return Decision(tuple(ediciones), comentario)
