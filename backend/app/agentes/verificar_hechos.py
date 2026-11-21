"""Verificación literal de los hechos que cita el redactor.

El redactor devuelve, junto con el texto de un slide, los hechos que usó copiados de la
fuente. Este módulo (código puro, sin LLM) comprueba que cada hecho aparezca de verdad en
los fragmentos asignados al slide y calcula su posición exacta en el texto normalizado de la
fuente, de modo que se cumpla siempre `fuente.texto[inicio:fin] == hecho.texto`.

Tolerancia: la búsqueda es literal (distingue mayúsculas y signos) PERO acepta que los
espacios y saltos de línea del original difieran de los que devolvió el modelo (los modelos
suelen aplanar un salto de línea a un espacio). El hecho que se guarda es siempre el trozo
real de la fuente, no la versión del modelo.
"""

import re
from dataclasses import dataclass

from app.fuentes.cargador_fuente import Fragmento


@dataclass(frozen=True)
class HechoUbicado:
    """Un hecho verificado: su texto exacto en la fuente y su rango [inicio, fin) sobre el texto normalizado."""

    texto: str
    inicio: int
    fin: int
    fragmento: int  # índice del fragmento donde se encontró


def _patron(hecho: str) -> re.Pattern[str] | None:
    """Patrón que casa el hecho literal, permitiendo cualquier blanco entre sus palabras.

    Devuelve None si el hecho no tiene contenido (vacío o solo blancos).
    """
    palabras = hecho.split()
    # Un hecho sin palabras no se puede buscar.
    if not palabras:
        return None
    return re.compile(r"\s+".join(re.escape(p) for p in palabras))


def ubicar_hecho(hecho: str, fragmentos: tuple[Fragmento, ...] | list[Fragmento]) -> HechoUbicado | None:
    """Busca el hecho en los fragmentos dados; devuelve su ubicación o None si no aparece."""
    patron = _patron(hecho)
    if patron is None:
        return None
    # Se recorren los fragmentos en orden y se devuelve la primera aparición.
    for f in fragmentos:
        m = patron.search(f.texto)
        if m:
            inicio = f.inicio + m.start()  # posición absoluta: inicio del fragmento + desplazamiento interno
            return HechoUbicado(texto=m.group(0), inicio=inicio, fin=f.inicio + m.end(), fragmento=f.indice)
    return None


def ubicar_hechos(
    hechos: list[str], fragmentos: tuple[Fragmento, ...] | list[Fragmento]
) -> tuple[list[HechoUbicado], list[str]]:
    """Ubica cada hecho. Devuelve (ubicados, no_encontrados), conservando el orden y sin repetir rangos."""
    ubicados: list[HechoUbicado] = []
    faltan: list[str] = []
    vistos: set[tuple[int, int]] = set()  # rangos ya registrados, para no duplicar el mismo trozo
    # Cada hecho se busca por separado.
    for h in hechos:
        u = ubicar_hecho(h, fragmentos)
        if u is None:
            faltan.append(h)
        elif (u.inicio, u.fin) not in vistos:
            vistos.add((u.inicio, u.fin))
            ubicados.append(u)
    return ubicados, faltan