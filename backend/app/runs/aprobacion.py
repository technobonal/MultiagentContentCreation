"""Aprobación humana (HITL): textos vigentes de un run y validación de la decisión de la persona.

La decisión es aprobar (con o sin ediciones) o rechazar con un motivo.

Funciones puras, sin red ni estado: reciben los eventos ya emitidos y la ficha de la plantilla. Así se
prueban solas y las usan tanto el endpoint (para rechazar una decisión mala con un 422) como el orquestador
(para emitir los eventos `editada` y `aprobada`).

Reglas:
- Solo se editan los campos que el redactor escribió (los mismos de `campos_del_redactor`), con su límite de la ficha.
- El «texto_antes» sale de lo que ya está dibujado (último `escribir_texto` o `editada` del campo), nunca del cliente.
- Una edición que deja el texto igual se ignora; un mismo campo dos veces en la decisión es un error.
- Las ediciones NO se vuelven a verificar contra la fuente: el sello cubre solo lo que escribió el modelo.
- Sin visto bueno (semaforo.py) solo se puede aprobar escribiendo una excepción, y el run lo deja marcado.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agentes.redactor import campos_del_redactor
from app.runs.semaforo import informe

# Tope del contrato `texto` (common.schema.json): un evento con más caracteres no valida.
TEXTO_MAX_CONTRATO = 400
# Agentes que se pueden señalar como responsables en un rechazo (contrato `rechazada`).
RESPONSABLES = ("estratega", "redactor", "director_arte", "revisor")


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
class Rechazo:
    """Por qué la persona rechaza el pack. Solo el motivo es obligatorio."""

    motivo: str
    responsable: str | None = None
    slide: int | None = None
    esperado: str | None = None


@dataclass(frozen=True)
class Decision:
    """Decisión de la persona. Con `rechazo` el pack se rechaza; sin él es una aprobación, con o sin ediciones."""

    ediciones: tuple[Edicion, ...] = ()
    comentario: str | None = None
    rechazo: Rechazo | None = None
    excepcion: str | None = None  # motivo para aprobar sin visto bueno


def _texto_opcional(valor: Any, nombre: str, motivos: list[str]) -> str | None:
    """Texto sin espacios en los bordes, o None si no vino o quedó vacío; anota por qué si no sirve."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        motivos.append(f"«{nombre}» debe ser un texto.")
        return None
    limpio = valor.strip()
    if len(limpio) > TEXTO_MAX_CONTRATO:
        motivos.append(f"«{nombre}» supera {TEXTO_MAX_CONTRATO} caracteres ({len(limpio)}).")
    return limpio or None


def _validar_rechazo(cuerpo: Mapping[str, Any], ficha: Mapping[str, Any]) -> Decision:
    """Un rechazo va solo: mezclarlo con ediciones o comentario sería una decisión ambigua."""
    motivos = [f"«{k}» no se puede enviar junto con un rechazo." for k in sorted(set(cuerpo) - {"rechazo"})]
    crudo = cuerpo["rechazo"]
    if not isinstance(crudo, Mapping):
        raise DecisionInvalida([*motivos, "«rechazo» debe ser un objeto con al menos el motivo."])
    motivos += [f"Clave desconocida en el rechazo: «{k}»." for k in sorted(set(crudo) - {"motivo", "responsable", "slide", "esperado"})]
    motivo = _texto_opcional(crudo.get("motivo"), "motivo", motivos)
    if motivo is None and (crudo.get("motivo") is None or isinstance(crudo.get("motivo"), str)):
        motivos.append("Para rechazar hay que escribir el motivo.")
    esperado = _texto_opcional(crudo.get("esperado"), "esperado", motivos)
    responsable = crudo.get("responsable")
    if responsable is not None and responsable not in RESPONSABLES:
        motivos.append(f"«responsable» debe ser uno de: {', '.join(RESPONSABLES)}.")
    slide = crudo.get("slide")
    if slide is not None and (isinstance(slide, bool) or slide not in [s["numero"] for s in ficha["slides"]]):
        motivos.append(f"El carrusel no tiene el slide {slide!r}.")
    if motivos:
        raise DecisionInvalida(motivos)
    return Decision(rechazo=Rechazo(motivo, responsable, slide, esperado))


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

    Para aprobar: {"ediciones": [{"slide": 2, "campo": "cuerpo", "texto": "..."}], "comentario": "..."}, con las
    dos claves opcionales. Para rechazar: {"rechazo": {"motivo": "...", "responsable": "revisor", "slide": 3,
    "esperado": "..."}}, con solo el motivo obligatorio.
    """
    if not isinstance(cuerpo, Mapping):
        raise DecisionInvalida(["El cuerpo debe ser un objeto JSON."])
    if "rechazo" in cuerpo:
        return _validar_rechazo(cuerpo, ficha)
    desconocidas = sorted(set(cuerpo) - {"ediciones", "comentario", "excepcion"})
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

    excepcion = _texto_opcional(cuerpo.get("excepcion"), "excepcion", motivos)

    if motivos:
        raise DecisionInvalida(motivos)
    _exigir_visto_bueno(informe(eventos, ediciones), excepcion)
    return Decision(tuple(ediciones), comentario, excepcion=excepcion)


def _exigir_visto_bueno(semaforo: Mapping[str, Any], excepcion: str | None) -> None:
    """En rojo hace falta la excepción; en verde sobra (marcaría como dudoso algo que pasó los controles)."""
    if semaforo["visto_bueno"] and excepcion is not None:
        raise DecisionInvalida(["El carrusel tiene visto bueno: no hace falta una excepción."])
    if not semaforo["visto_bueno"] and excepcion is None:
        rojos = [str(f["slide"]) for f in semaforo["slides"] if f["color"] == "rojo"]
        detalle = f" Slides en rojo: {', '.join(rojos)}." if rojos else f" {' '.join(semaforo['generales'])}"
        raise DecisionInvalida([
            f"No hay visto bueno.{detalle} Para aprobar igual, escribe en «excepcion» por qué; para no aprobar, rechaza."
        ])
