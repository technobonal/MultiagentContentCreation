"""Asesor de aprobación: una segunda opinión, de otra familia de modelos, sobre lo que la persona va a aprobar.

Solo puede frenar: sus alertas ponen un slide en rojo (semaforo.py), nunca en verde. No cambia textos ni decide.
Igual que el revisor, no redacta lo que juzga: las frases las separa el código (frases.py) y él responde por
número. Recibe los mismos fragmentos de la fuente que el revisor, pero NO sus veredictos, para no copiarlos.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.agentes.cliente_asesor import ClienteAsesor
from app.agentes.comun import cargar_prompt
from app.agentes.frases import Frase, frases_del_slide
from app.agentes.revisor_codigo import recortar_texto

SUGERENCIAS = ("reescribir", "quitar", "rechazar")


def frases_a_revisar(textos: Mapping[tuple[int, str], str], del_redactor: set[tuple[int, str]]) -> dict[int, list[Frase]]:
    """Frases vigentes de los campos que escribió el redactor, por slide."""
    por_slide: dict[int, dict[str, str]] = {}
    for (slide, campo), texto in textos.items():
        if (slide, campo) in del_redactor:
            por_slide.setdefault(slide, {})[campo] = texto
    return {n: frases_del_slide(por_slide[n]) for n in sorted(por_slide)}


def mensaje_usuario(frases: Mapping[int, Sequence[Frase]], material: Mapping[int, Sequence[str]]) -> str:
    bloques = []
    for slide, del_slide in frases.items():
        lineas = [f"SLIDE: {slide}", "", "FRASES:"]
        lineas += [f"{f.numero}. [{f.campo}] {f.texto}" for f in del_slide]
        lineas += ["", "FRAGMENTOS DE LA FUENTE:"]
        fragmentos = material.get(slide) or ()
        lineas += [f"[F{i}] {t}" for i, t in enumerate(fragmentos, start=1)] or ["(ninguno)"]
        bloques.append("\n".join(lineas))
    return "\n\n---\n\n".join(bloques)


def _juicios(dato: Mapping[str, Any], frases: Mapping[int, Sequence[Frase]]) -> dict[tuple[int, int], Mapping[str, Any]]:
    """(slide, número) -> juicio, solo para frases que existen. Entre dos de la misma, manda la que alerta."""
    validas = {(slide, f.numero) for slide, del_slide in frases.items() for f in del_slide}
    juicios: dict[tuple[int, int], Mapping[str, Any]] = {}
    lista = dato.get("juicios")
    for j in lista if isinstance(lista, list) else []:
        if not isinstance(j, Mapping) or not isinstance(j.get("problema"), bool):
            continue
        slide, frase = j.get("slide"), j.get("frase")
        if type(slide) is not int or type(frase) is not int or (slide, frase) not in validas:
            continue
        if (slide, frase) not in juicios or j["problema"]:
            juicios[(slide, frase)] = j
    return juicios


async def asesorar(
    cliente: ClienteAsesor, frases: Mapping[int, Sequence[Frase]], material: Mapping[int, Sequence[str]],
) -> dict:
    """Payload del evento `asesoria`: modelo, cuántas frases revisó de cuántas y las alertas."""
    total = sum(len(f) for f in frases.values())
    dato, modelo = await cliente.pedir(
        cargar_prompt("asesor"), mensaje_usuario(frases, material),
        # Una respuesta que no juzga ni una frase no sirve: se prueba con el siguiente modelo.
        lambda d: bool(_juicios(d, frases)),
    )
    juicios = _juicios(dato, frases)
    textos = {(slide, f.numero): f for slide, del_slide in frases.items() for f in del_slide}
    alertas = []
    for clave in sorted(juicios):
        j = juicios[clave]
        if j["problema"]:
            explicacion = j.get("explicacion")
            sugerencia = j.get("sugerencia")
            alertas.append({
                "slide": clave[0],
                "frase": recortar_texto(textos[clave].texto),  # la pone el código, no el modelo
                "explicacion": recortar_texto(explicacion if isinstance(explicacion, str) and explicacion.strip()
                                              else "El asesor marcó la frase sin explicar por qué."),
                "sugerencia": sugerencia if sugerencia in SUGERENCIAS else "reescribir",
            })
    return {"modelo": modelo, "frases_revisadas": len(juicios), "frases_totales": total, "alertas": alertas}
