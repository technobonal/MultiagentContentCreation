"""Validación de eventos contra el contrato (contracts/events/event.schema.json).

Replica la carga de esquemas de contracts/validate.py (registro por $id y
FormatChecker) para que backend y frontend validen con las mismas reglas.
Además aplica el tope de tamaño por evento definido en el README de contratos.
"""

import json
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from app import config


@lru_cache(maxsize=1)
def obtener_validador() -> Draft202012Validator:
    """Construye (una sola vez) el validador del esquema completo de evento.

    Registra todos los *.schema.json por su $id para que los $ref relativos
    (envelope, common, un esquema por evento) se resuelvan sin red.
    """
    recursos = []
    # Recorre todos los esquemas bajo contracts/ en orden estable.
    for ruta in sorted(config.CONTRATOS_DIR.rglob("*.schema.json")):
        with open(ruta, encoding="utf-8") as f:
            esquema = json.load(f)
        # Un esquema sin $id no se puede referenciar desde otro archivo: se omite del registro.
        if "$id" in esquema:
            recursos.append((esquema["$id"], Resource.from_contents(esquema)))
    registro = Registry().with_resources(recursos)

    ruta_evento = config.CONTRATOS_DIR / "events" / "event.schema.json"
    with open(ruta_evento, encoding="utf-8") as f:
        esquema_evento = json.load(f)
    return Draft202012Validator(esquema_evento, registry=registro, format_checker=FormatChecker())


def tamano_bytes(evento: dict) -> int:
    """Devuelve el tamaño en bytes del evento serializado como JSON UTF-8."""
    return len(json.dumps(evento, ensure_ascii=False).encode("utf-8"))


def comprobar_evento(evento: dict, limite_mensajes: int = 6) -> list[str]:
    """Valida un evento y devuelve la lista de motivos de rechazo (vacía si es válido).

    Orden de las comprobaciones: primero el tamaño (barato y evita validar algo
    gigante) y luego el esquema completo.
    """
    # Tope de tamaño: un evento demasiado grande se rechaza sin mirar su contenido.
    tam = tamano_bytes(evento)
    if tam > config.TAM_MAX_EVENTO_BYTES:
        return [f"el evento pesa {tam} bytes y el máximo es {config.TAM_MAX_EVENTO_BYTES}"]

    motivos = []
    errores = sorted(
        obtener_validador().iter_errors(evento),
        key=lambda e: list(map(str, e.absolute_path)),  # orden estable entre ejecuciones
    )
    for error in errores:
        ruta = "/".join(map(str, error.absolute_path)) or "(raíz)"
        motivos.append(f"{ruta}: {error.message[:150]}")
        # Evita inundar al cliente cuando un evento está muy roto.
        if len(motivos) >= limite_mensajes:
            break
    return motivos