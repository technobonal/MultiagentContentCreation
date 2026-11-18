"""Carga de secuencias grabadas desde contracts/recordings/.

Devuelve los eventos crudos y ordenados por seq. NO valida: la validación se
hace en el borde, justo antes de emitir (ver emisor.py), para que un evento
inválido produzca un error visible en vez de desaparecer aquí.
"""

import json
from pathlib import Path

from app import config


class RunNoEncontrado(Exception):
    """No hay ninguna grabación con el run_id pedido."""


def _clave_seq(evento) -> int:
    """Clave de orden: el seq del evento, o 0 si falta o no es entero.

    Un evento sin seq válido queda al principio, donde el validador lo
    rechazará de inmediato en vez de esconderse al final.
    """
    seq = evento.get("seq") if isinstance(evento, dict) else None
    return seq if isinstance(seq, int) else 0


def ordenar_por_seq(eventos: list) -> list:
    """Devuelve una copia de la lista ordenada por seq creciente."""
    return sorted(eventos, key=_clave_seq)


def cargar_eventos(run_id: str, carpeta: Path | None = None) -> list:
    """Busca la grabación cuyo run_id coincide y devuelve sus eventos ordenados.

    El run_id solo se compara con el contenido de los archivos; nunca se usa
    para construir una ruta (así no hay riesgo de salirse de la carpeta).
    Lanza RunNoEncontrado si ninguna grabación coincide.
    """
    carpeta = carpeta or config.GRABACIONES_DIR
    # Revisa cada archivo .json de la carpeta, en orden estable.
    for ruta in sorted(carpeta.glob("*.json")):
        # Los esquemas viven en la misma carpeta y no son grabaciones.
        if ruta.name.endswith(".schema.json"):
            continue
        with open(ruta, encoding="utf-8") as f:
            doc = json.load(f)  # un JSON roto aquí sube como error 500, visible
        # Solo cuenta si es un objeto con el run_id pedido.
        if isinstance(doc, dict) and doc.get("run_id") == run_id:
            return ordenar_por_seq(doc.get("eventos", []))
    raise RunNoEncontrado(run_id)