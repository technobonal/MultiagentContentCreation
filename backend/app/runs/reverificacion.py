"""Re-verificación de un slide a pedido de la persona (A5).

Mientras el run espera la decisión, la persona puede pedir que un slide se vuelva a verificar sin cerrar el run:
  - modo "edicion": verificar el texto que ella misma editó (se aplican las ediciones y el revisor juzga el resultado).
  - modo "agente": el corrector reescribe el slide y el revisor lo re-verifica (reusa el ciclo de corrección).

Funciones puras (sin red ni estado): reconstruyen los hallazgos abiertos desde los eventos y validan el pedido.
El lazo y la emisión viven en el orquestador; el tope de rondas, en `config`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agentes.ciclo_correccion import HallazgoAbierto
from app.runs.aprobacion import DecisionInvalida, Edicion, validar_ediciones

MODOS = ("edicion", "agente")


@dataclass(frozen=True)
class Reverificacion:
    """Un pedido de re-verificación ya validado: qué slide, con qué modo y con qué ediciones (solo en modo edición)."""

    slide: int
    modo: str
    ediciones: tuple[Edicion, ...] = ()


def reconstruir_abiertos(eventos: Sequence[Mapping[str, Any]]) -> list[HallazgoAbierto]:
    """Rearma los hallazgos que siguen abiertos (con su payload y el seq de apertura) para sembrar el ciclo.

    Un hallazgo se cierra solo con un `hallazgo_corregido` «corregido»; cada «persiste» cuenta un intento.
    """
    abiertos: dict[str, HallazgoAbierto] = {}
    for e in eventos:
        tipo = e.get("tipo")
        payload = e.get("payload") or {}
        hid = payload.get("hallazgo_id")
        if not hid:
            continue
        if tipo == "hallazgo_abierto":
            abiertos[hid] = HallazgoAbierto(
                hallazgo_id=hid, slide=e.get("slide"), payload=payload, seq_abierto=e["seq"], intentos=1
            )
        elif tipo == "hallazgo_corregido":
            if payload.get("resultado") == "corregido":
                abiertos.pop(hid, None)
            elif hid in abiertos:  # «persiste»: un intento más
                abiertos[hid].intentos += 1
    return list(abiertos.values())


def validar_reverificacion(
    cuerpo: Any, eventos: Sequence[Mapping[str, Any]], ficha: Mapping[str, Any]
) -> Reverificacion:
    """Convierte el cuerpo del POST en una `Reverificacion` o lanza `DecisionInvalida` con todos los motivos.

    Cuerpo: {"slide": 2, "modo": "edicion", "ediciones": [{"slide": 2, "campo": "cuerpo", "texto": "..."}]}.
    En modo "agente" no se envían ediciones. En modo "edicion" todas las ediciones deben ser del mismo slide y
    tiene que haber al menos un cambio real.
    """
    if not isinstance(cuerpo, Mapping):
        raise DecisionInvalida(["El cuerpo debe ser un objeto JSON."])
    motivos = [f"Clave desconocida: «{k}»." for k in sorted(set(cuerpo) - {"slide", "modo", "ediciones"})]

    slide = cuerpo.get("slide")
    numeros = [s["numero"] for s in ficha["slides"]]
    if isinstance(slide, bool) or not isinstance(slide, int) or slide not in numeros:
        motivos.append(f"«slide» debe ser uno de: {', '.join(map(str, numeros))}.")

    modo = cuerpo.get("modo")
    if modo not in MODOS:
        motivos.append(f"«modo» debe ser uno de: {', '.join(MODOS)}.")

    ediciones: tuple[Edicion, ...] = ()
    if modo == "agente":
        if cuerpo.get("ediciones"):
            motivos.append("En modo «agente» no se envían ediciones: las escribe el corrector.")
    elif modo == "edicion":
        lista = validar_ediciones(cuerpo.get("ediciones", []), eventos, ficha, motivos)
        if isinstance(slide, int) and any(ed.slide != slide for ed in lista):
            motivos.append(f"Todas las ediciones deben ser del slide {slide}.")
        if not lista and not motivos:
            motivos.append("No cambiaste ningún texto: no hay nada que volver a verificar.")
        ediciones = tuple(lista)

    if motivos:
        raise DecisionInvalida(motivos)
    return Reverificacion(slide, modo, ediciones)
