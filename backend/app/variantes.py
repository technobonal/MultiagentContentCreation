"""Variantes de color de una plantilla (campo opcional `variantes` de la ficha), sin LLM.

La variante sale del `run_id`: el mismo run siempre da la misma. Es un cambio de colores "original -> nuevo"
que se aplica a los fondos de los slides (backend) y al SVG (lienzo, con lo que viaja en `plantilla_elegida`).
"""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Variante:
    id: str
    nombre: str
    reemplazos: dict[str, str]
    forzada: bool = False


def elegir_variante(ficha: dict, run_id: str, forzada: str = "") -> Variante | None:
    """None si la plantilla no declara variantes. `forzada` (para probar una) debe existir en la ficha."""
    disponibles = ficha.get("variantes") or []
    if not disponibles:
        return None
    if forzada:
        elegida = next((v for v in disponibles if v["id"] == forzada), None)
        if elegida is None:
            ids = ", ".join(v["id"] for v in disponibles)
            raise ValueError(f"La plantilla no tiene la variante «{forzada}». Disponibles: {ids}.")
    else:
        # `hash()` cambia entre procesos; sha256 no.
        numero = int.from_bytes(hashlib.sha256(run_id.encode("utf-8")).digest()[:8], "big")
        elegida = disponibles[numero % len(disponibles)]
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


def payload_con_variante(payload: dict, variante: Variante | None) -> dict:
    """Payload de `plantilla_elegida` con la variante y su porqué en el motivo."""
    if variante is None:
        return payload
    porque = "fijada para probarla" if variante.forzada else "según el identificador del run"
    return {
        **payload,
        "motivo": f"{payload['motivo']}. Colores: {variante.nombre} ({porque})",
        "variante": {"id": variante.id, "reemplazos": variante.reemplazos},
    }
