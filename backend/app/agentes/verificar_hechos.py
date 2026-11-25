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


def _patron_sin_blancos(hecho: str) -> re.Pattern[str] | None:
    """Patrón que casa las mismas LETRAS del hecho permitiendo blancos en cualquier posición, incluso dentro de una palabra.

    Existe por los PDF: el texto justificado deja espacios falsos dentro de las palabras («Protección So cial»)
    y el modelo copia la cita «arreglada» («Protección Social»). Es el segundo intento: solo se usa si el patrón
    estricto no encontró nada, y el trozo que devuelve es siempre el de la fuente, con su ruido.
    """
    letras = "".join(hecho.split())
    if not letras:
        return None
    return re.compile(r"\s*".join(re.escape(c) for c in letras))


# Blancos, comillas y puntos suspensivos que el modelo suele poner en los EXTREMOS de una cita («"Toda persona…"»,
# «...el Seguro Popular…»). No forman parte de la fuente: se quitan solo si la búsqueda directa no encontró nada.
_BORDE = re.compile(r"^(?:[\s\"'“”‘’«»…]|\.\.\.)+|(?:[\s\"'“”‘’«»…]|\.\.\.)+$")


def quitar_bordes(hecho: str) -> str:
    """Quita comillas, blancos y puntos suspensivos de los extremos del hecho (lo de adentro no se toca)."""
    return _BORDE.sub("", hecho)


def _buscar(patron: re.Pattern[str], fragmentos: tuple[Fragmento, ...] | list[Fragmento]) -> HechoUbicado | None:
    """Primera aparición del patrón en los fragmentos, con posiciones absolutas."""
    for f in fragmentos:
        m = patron.search(f.texto)
        if m:
            inicio = f.inicio + m.start()  # posición absoluta: inicio del fragmento + desplazamiento interno
            return HechoUbicado(texto=m.group(0), inicio=inicio, fin=f.inicio + m.end(), fragmento=f.indice)
    return None


def ubicar_hecho(hecho: str, fragmentos: tuple[Fragmento, ...] | list[Fragmento]) -> HechoUbicado | None:
    """Busca el hecho en los fragmentos dados; devuelve su ubicación o None si no aparece.

    Primero la búsqueda literal (blancos flexibles entre palabras); si falla, ignora los blancos dentro de las
    palabras (PDF con espacios falsos). Se recorren los fragmentos en orden y gana la primera aparición.
    """
    patron = _patron(hecho)
    if patron is None:
        return None
    ubicado = _buscar(patron, fragmentos) or _buscar(_patron_sin_blancos(hecho), fragmentos)
    if ubicado is not None:
        return ubicado
    # Último intento: sin las comillas y los puntos suspensivos de los extremos.
    limpio = quitar_bordes(hecho)
    if not limpio or limpio == hecho.strip():
        return None
    return _buscar(_patron(limpio), fragmentos) or _buscar(_patron_sin_blancos(limpio), fragmentos)


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