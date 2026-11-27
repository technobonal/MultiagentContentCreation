"""Registro de rechazos: lo que una persona rechazó y por qué, guardado en disco.

Los runs viven en memoria, así que sin esto el motivo se perdería al reiniciar. Cada rechazo es una línea JSON
con lo necesario para convertirlo más adelante en una lección para el agente que falló (plan A6). Puede
incluir texto de documentos privados: el archivo queda en la máquina y fuera de Git.
"""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from app.runs.aprobacion import Rechazo, textos_vigentes
from app.runs.sello import hallazgos_abiertos


def armar_registro(
    run_id: str, plantilla_id: str, rechazo: Rechazo, eventos: Sequence[Mapping[str, Any]],
    estado_revision: str, sello: Mapping[str, int],
) -> dict:
    """Foto del momento del rechazo. Si la persona señaló un slide, solo lo de ese slide."""
    def del_slide(numero: Any) -> bool:
        return rechazo.slide is None or numero == rechazo.slide

    abiertos = hallazgos_abiertos(eventos)
    return {
        "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "plantilla_id": plantilla_id,
        "motivo": rechazo.motivo,
        "responsable": rechazo.responsable,
        "slide": rechazo.slide,
        "esperado": rechazo.esperado,
        "estado_revision": estado_revision,
        "sello": dict(sello),
        "textos": [
            {"slide": s, "campo": c, "texto": t} for (s, c), t in sorted(textos_vigentes(eventos).items()) if del_slide(s)
        ],
        # El historial completo de veredictos: ahí se ve qué dio por bueno el revisor.
        "verificaciones": [
            {"seq": e["seq"], "slide": e.get("slide"), **e["payload"]}
            for e in eventos if e.get("tipo") == "verificacion_fidelidad" and del_slide(e.get("slide"))
        ],
        "hallazgos_abiertos": [
            {"slide": e.get("slide"), **e["payload"]}
            for e in eventos if e.get("tipo") == "hallazgo_abierto" and e["payload"]["hallazgo_id"] in abiertos
        ],
    }


def guardar_rechazo(ruta: Path, registro: Mapping[str, Any]) -> None:
    """Agrega el registro como una línea al final del archivo (lo crea si no existe)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
