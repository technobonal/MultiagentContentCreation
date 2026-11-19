"""Validación contra los contratos: eventos (contracts/events/event.schema.json) y entrada
(contracts/input/input.schema.json).

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
def obtener_registro() -> Registry:
    """Construye (una sola vez) el registro con todos los *.schema.json por su $id.

    Así los $ref relativos (envelope, common, un esquema por evento, entrada)
    se resuelven sin red.
    """
    recursos = []
    # Recorre todos los esquemas bajo contracts/ en orden estable.
    for ruta in sorted(config.CONTRATOS_DIR.rglob("*.schema.json")):
        with open(ruta, encoding="utf-8") as f:
            esquema = json.load(f)
        # Un esquema sin $id no se puede referenciar desde otro archivo: se omite del registro.
        if "$id" in esquema:
            recursos.append((esquema["$id"], Resource.from_contents(esquema)))
    return Registry().with_resources(recursos)


def _construir_validador(ruta_esquema) -> Draft202012Validator:
    """Crea un validador para el esquema de la ruta dada, con el registro compartido."""
    with open(ruta_esquema, encoding="utf-8") as f:
        esquema = json.load(f)
    return Draft202012Validator(esquema, registry=obtener_registro(), format_checker=FormatChecker())


@lru_cache(maxsize=1)
def obtener_validador() -> Draft202012Validator:
    """Validador (cacheado) del esquema completo de evento."""
    return _construir_validador(config.CONTRATOS_DIR / "events" / "event.schema.json")


@lru_cache(maxsize=1)
def obtener_validador_entrada() -> Draft202012Validator:
    """Validador (cacheado) del esquema de entrada del sistema."""
    return _construir_validador(config.CONTRATOS_DIR / "input" / "input.schema.json")


def tamano_bytes(evento: dict) -> int:
    """Devuelve el tamaño en bytes del evento serializado como JSON UTF-8."""
    return len(json.dumps(evento, ensure_ascii=False).encode("utf-8"))


def _motivos_de(validador: Draft202012Validator, instancia, limite_mensajes: int) -> list[str]:
    """Devuelve hasta `limite_mensajes` motivos legibles de rechazo (lista vacía si es válida)."""
    motivos = []
    errores = sorted(
        validador.iter_errors(instancia),
        key=lambda e: list(map(str, e.absolute_path)),  # orden estable entre ejecuciones
    )
    for error in errores:
        ruta = "/".join(map(str, error.absolute_path)) or "(raíz)"
        motivos.append(f"{ruta}: {error.message[:150]}")
        # Evita inundar al cliente cuando la instancia está muy rota.
        if len(motivos) >= limite_mensajes:
            break
    return motivos


def comprobar_evento(evento: dict, limite_mensajes: int = 6) -> list[str]:
    """Valida un evento y devuelve la lista de motivos de rechazo (vacía si es válido).

    Orden de las comprobaciones: primero el tamaño (barato y evita validar algo
    gigante) y luego el esquema completo.
    """
    # Tope de tamaño: un evento demasiado grande se rechaza sin mirar su contenido.
    tam = tamano_bytes(evento)
    if tam > config.TAM_MAX_EVENTO_BYTES:
        return [f"el evento pesa {tam} bytes y el máximo es {config.TAM_MAX_EVENTO_BYTES}"]
    return _motivos_de(obtener_validador(), evento, limite_mensajes)


def comprobar_entrada(entrada, limite_mensajes: int = 6) -> list[str]:
    """Valida la FORMA de una entrada contra input.schema.json (lista vacía si es válida).

    Las reglas que cruzan archivos (plantilla existe, num_slides compatible) viven en resolution.py.
    """
    return _motivos_de(obtener_validador_entrada(), entrada, limite_mensajes)
