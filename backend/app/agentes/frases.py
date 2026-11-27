"""Separa el texto de un slide en las frases que el revisor de fidelidad tiene que juzgar.

Las define el código y no el modelo: así lo que se evalúa es exactamente lo que dice el slide, y se nota si
falta un veredicto. Se corta tras «.», «!», «?» o «…» cuando sigue un comienzo de frase, y en cada salto de línea.
No se corta en «:» ni en «,»: partir ahí dejaría trozos que solos cambian de sentido.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.agentes.revisor_codigo import nombre_campo

# Fin de frase (con sus comillas o paréntesis de cierre) seguido de espacio.
_FIN = re.compile(r"[.!?…]+[\"'»”)\]]*(?=\s)")

# Tras estas abreviaturas el punto no cierra la frase.
_ABREVIATURAS = frozenset("sr sra srta dr dra ing lic prof av avda ej p núm num nro aprox vs ee uu st mt".split())


@dataclass(frozen=True)
class Frase:
    numero: int  # desde 1, corrido por todo el slide
    campo: str  # sin llaves
    texto: str  # tal como está escrito, con los espacios normalizados


def _empieza_frase(resto: str) -> bool:
    """Lo que sigue puede ser otra frase: no empieza en minúscula."""
    inicio = resto.lstrip(" \t\"'«“([¿¡")
    return bool(inicio) and not inicio[0].islower()


def _cortar(linea: str) -> list[str]:
    trozos, desde = [], 0
    for m in _FIN.finditer(linea):
        palabra = re.search(r"([^\W\d_]+)$", linea[desde:m.start()])
        if m.group() == "." and palabra and palabra.group(1).lower() in _ABREVIATURAS:
            continue
        if not _empieza_frase(linea[m.end():]):
            continue
        trozos.append(linea[desde:m.end()])
        desde = m.end()
    trozos.append(linea[desde:])
    return trozos


def separar_campo(texto: str) -> list[str]:
    """Frases de un campo. Un trozo sin letras (el «1.» de una lista) se une al siguiente: nada queda afuera."""
    trozos = [" ".join(t.split()) for linea in texto.splitlines() for t in _cortar(linea)]
    frases: list[str] = []
    pendiente = ""
    for trozo in filter(None, trozos):
        trozo = f"{pendiente} {trozo}".strip()
        if any(c.isalpha() for c in trozo):
            frases.append(trozo)
            pendiente = ""
        else:
            pendiente = trozo
    if pendiente:  # un campo (o un final) hecho solo de cifras o signos también se juzga
        if frases:
            frases[-1] = f"{frases[-1]} {pendiente}"
        elif any(c.isalnum() for c in pendiente):
            frases.append(pendiente)
    return frases


def frases_del_slide(campos: Mapping[str, str]) -> list[Frase]:
    """Frases de todos los campos con texto, numeradas en el orden de los campos."""
    frases: list[Frase] = []
    for nombre, texto in campos.items():
        if isinstance(texto, str):
            for trozo in separar_campo(texto):
                frases.append(Frase(len(frases) + 1, nombre_campo(nombre), trozo))
    return frases
