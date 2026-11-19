"""Resolución de la entrada: reglas que cruzan archivos (regla 3 del SPEC).

El esquema de entrada solo cubre la forma. Aquí se carga el catálogo de plantillas y se
comprueba que la entrada encaje con una plantilla concreta. Las reglas son las mismas que
aplica contracts/validate.py (`reglas_cruzadas`); una prueba corre todos los ejemplos de
contracts/input/examples para que las dos implementaciones no se separen.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app import config


@dataclass(frozen=True)
class Resolucion:
    """Lo que se decidió a partir de la entrada: plantilla, cómo se eligió y número de slides."""

    ficha: dict  # ficha completa de la plantilla (card.json sin su $comment raíz)
    plantilla_id: str  # identificador de la plantilla
    modo_plantilla: str  # "fijo" si la eligió el usuario, "auto" si la eligió el sistema
    num_slides: int  # número de slides resuelto (incluye el de fuentes)


def cargar_fichas(carpeta: Path | None = None) -> dict[str, dict]:
    """Carga las fichas card.json del catálogo, indexadas por su id.

    Un JSON roto sube como error (500 visible); no se ignora.
    """
    carpeta = carpeta or config.CATALOGO_DIR
    fichas = {}
    # Una carpeta por plantilla; el orden estable hace repetible la elección en modo auto.
    for ruta in sorted(carpeta.glob("*/card.json")):
        with open(ruta, encoding="utf-8") as f:
            ficha = json.load(f)
        ficha.pop("$comment", None)  # el comentario raíz es documentación, no parte de la ficha
        fichas[ficha.get("id", ruta.parent.name)] = ficha
    return fichas


def errores_de_plantilla(entrada: dict, ficha: dict) -> list[str]:
    """Reglas de la entrada contra UNA plantilla ya elegida (mismos mensajes que validate.py)."""
    errores = []
    n = entrada.get("destino", {}).get("num_slides", {})
    # Número de slides fijo y plantilla deben coincidir.
    if n.get("modo") == "fijo" and n.get("valor") != len(ficha["slides"]):
        errores.append(
            f"plantilla fija de {len(ficha['slides'])} slides contra num_slides fijo en {n.get('valor')}"
        )
    # El idioma de salida debe estar entre los idiomas probados de la plantilla.
    idioma = entrada.get("fuente", {}).get("idioma_salida")
    if idioma not in ficha["idiomas"]:
        errores.append(f"la plantilla {ficha['id']} no fue probada en el idioma {idioma}")
    # Cada imagen del usuario debe apuntar a un campo de imagen declarado en la ficha.
    campos_imagen = {
        c["nombre"].strip("{}") for s in ficha["slides"] for c in s["campos"] if c["tipo"] == "imagen"
    }
    for imagen in entrada.get("recursos", {}).get("imagenes", []):
        if imagen["rol"] not in campos_imagen:  # regla 7: la foto entra solo por un campo declarado
            errores.append(f"la imagen {imagen['archivo']} apunta al rol '{imagen['rol']}', que la plantilla no declara")
    return errores


def _es_compatible(entrada: dict, ficha: dict) -> bool:
    """¿Sirve esta plantilla para una entrada con plantilla en modo auto?"""
    destino = entrada.get("destino", {})
    # La red y el formato de la ficha deben ser los del destino pedido.
    if ficha.get("plataforma") != destino.get("red") or ficha.get("formato") != destino.get("formato"):
        return False
    return not errores_de_plantilla(entrada, ficha)


def resolver(entrada: dict, fichas: dict[str, dict]) -> tuple[Resolucion | None, list[str]]:
    """Decide la plantilla y el número de slides. Devuelve (resolución, errores).

    Con errores la resolución es None. La entrada ya debe haber pasado el esquema.
    """
    plantilla = entrada.get("diseno", {}).get("plantilla", {})
    if plantilla.get("modo") == "fijo":
        pid = plantilla.get("valor")
        if pid not in fichas:  # la plantilla fija debe existir en el catálogo
            return None, [f"plantilla fija inexistente en templates/catalog: {pid}"]
        ficha, modo = fichas[pid], "fijo"
        errores = errores_de_plantilla(entrada, ficha)
        if errores:  # la plantilla fija contradice otro dato de la entrada
            return None, errores
    else:
        # Con plantilla en auto se toma la primera compatible (orden estable por id).
        candidatas = [f for _, f in sorted(fichas.items()) if _es_compatible(entrada, f)]
        if not candidatas:  # ninguna encaja: error visible, no se elige "la más parecida"
            return None, ["ninguna plantilla del catálogo cumple la entrada (red, idioma, número de slides o imágenes)"]
        ficha, modo = candidatas[0], "auto"
    return Resolucion(ficha=ficha, plantilla_id=ficha["id"], modo_plantilla=modo, num_slides=len(ficha["slides"])), []
