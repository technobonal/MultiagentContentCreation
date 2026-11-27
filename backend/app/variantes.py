"""Variantes de una plantilla (campos opcionales `variantes` y `composiciones` de la ficha), sin LLM.

Las dos salen del `run_id`, cada una por su lado: el mismo run siempre da lo mismo.
- Variante: cambio de colores "original -> nuevo" para los fondos de los slides (backend) y el SVG (lienzo).
- Composición: otras siluetas y adornos; el SVG trae las dos y el lienzo deja la elegida.
Ambas viajan en `plantilla_elegida`.
"""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Variante:
    id: str
    nombre: str
    reemplazos: dict[str, str]
    forzada: bool = False


@dataclass(frozen=True)
class Composicion:
    id: str
    nombre: str
    forzada: bool = False


def _elegir(disponibles: list[dict], semilla: str, forzada: str, que: str) -> dict:
    """La `forzada` (para probar una; debe existir) o la que toque según la semilla."""
    if forzada:
        elegida = next((d for d in disponibles if d["id"] == forzada), None)
        if elegida is None:
            ids = ", ".join(d["id"] for d in disponibles)
            raise ValueError(f"La plantilla no tiene la {que} «{forzada}». Disponibles: {ids}.")
        return elegida
    # `hash()` cambia entre procesos; sha256 no.
    numero = int.from_bytes(hashlib.sha256(semilla.encode("utf-8")).digest()[:8], "big")
    return disponibles[numero % len(disponibles)]


def elegir_composicion(ficha: dict, run_id: str, forzada: str = "") -> Composicion | None:
    """None si la plantilla no declara composiciones."""
    disponibles = ficha.get("composiciones") or []
    if not disponibles:
        return None
    # La semilla lleva un sufijo para que la composición no vaya atada a la paleta.
    elegida = _elegir(disponibles, f"{run_id}:composicion", forzada, "composición")
    return Composicion(elegida["id"], elegida["nombre"], bool(forzada))


def elegir_variante(ficha: dict, run_id: str, forzada: str = "") -> Variante | None:
    """None si la plantilla no declara variantes. `forzada` (para probar una) debe existir en la ficha."""
    disponibles = ficha.get("variantes") or []
    if not disponibles:
        return None
    elegida = _elegir(disponibles, run_id, forzada, "variante")
    return Variante(elegida["id"], elegida["nombre"], dict(elegida["reemplazos"]), bool(forzada))


def ficha_con_variante(ficha: dict, variante: Variante | None) -> dict:
    """Copia de la ficha con los fondos de los slides en los colores de la variante (la original no se modifica)."""
    if variante is None or not variante.reemplazos:
        return ficha
    cambios = {de.upper(): a for de, a in variante.reemplazos.items()}
    slides = [
        {**s, "fondo": cambios.get(s["fondo"].upper(), s["fondo"])} if "fondo" in s else s
        for s in ficha["slides"]
    ]
    return {**ficha, "slides": slides}


def payload_con_variante(payload: dict, variante: Variante | None, composicion: Composicion | None = None) -> dict:
    """Payload de `plantilla_elegida` con la variante y la composición, y su porqué en el motivo."""
    resultado = dict(payload)
    for etiqueta, elegida in (("Colores", variante), ("Composición", composicion)):
        if elegida is not None:
            porque = "fijada para probarla" if elegida.forzada else "según el identificador del run"
            resultado["motivo"] = f"{resultado['motivo']}. {etiqueta}: {elegida.nombre} ({porque})"
    if variante is not None:
        resultado["variante"] = {"id": variante.id, "reemplazos": variante.reemplazos}
    if composicion is not None:
        resultado["composicion"] = composicion.id
    return resultado
