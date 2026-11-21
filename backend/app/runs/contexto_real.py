"""Contexto del modo real: el cliente LLM y el kit de marca, construidos UNA vez al arrancar.

Qué resuelve:
- `construir_contexto()` arma el `ClienteGroq` y carga el kit de marca. Si falta GROQ_API_KEY o el kit
  no existe o está mal formado, FALLA al construirse (el servidor no arranca), no a mitad de un run.
- El contexto vive en `app.state` (lo guarda el lifespan en la tanda 8E-2), no en un caché de módulo:
  así se construye dentro del bucle de asyncio correcto y no se contamina entre pruebas.
- El kit es compartido por todos los runs, pero cada run recibe su propia copia (`kit_para_run`),
  para que un agente que lo modifique no afecte a otro run en curso.
"""

import copy
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path

from app import config
from app.agentes.cliente_llm import ClienteGroq, ClienteLLM

# Origen que llevan los eventos de una ejecución real (el relleno usa "grabado").
ORIGEN_REAL = "real"

# Caracteres que no pueden aparecer en el nombre del kit (así no se sale de la carpeta de kits).
_PROHIBIDOS_EN_NOMBRE = "/\\:"


class ContextoRealError(Exception):
    """Fallo al armar el contexto real. `codigo` es estable (pruebas y mensajes); `mensaje` es apto para mostrar."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class ContextoReal:
    """Lo que necesita `ejecutar_run_real` además de la fuente: el cliente LLM y el kit de marca.

    Los campos no salen en el `repr` para que nunca se filtren claves ni el contenido del kit a un log.
    """

    cliente: ClienteLLM = field(repr=False)
    kit: dict = field(repr=False)

    def kit_para_run(self) -> dict:
        """Devuelve una copia profunda del kit: cada ejecución trabaja con la suya."""
        return copy.deepcopy(self.kit)

    async def cerrar(self) -> None:
        """Cierra el cliente HTTP del SDK (si lo tiene) al apagar el servidor; sin SDK no hace nada."""
        sdk = getattr(self.cliente, "sdk", None)
        cerrar_sdk = getattr(sdk, "close", None)
        # Sin un `close` en el SDK (por ejemplo, un cliente falso) no hay nada que cerrar.
        if cerrar_sdk is None:
            return
        resultado = cerrar_sdk()
        # El SDK async devuelve una corutina; uno síncrono ya terminó al llamarlo.
        if inspect.isawaitable(resultado):
            await resultado


def cargar_kit(nombre: str | None = None, carpeta: Path | None = None) -> dict:
    """Lee `<carpeta>/<nombre>.json` (por defecto el KIT_MARCA de config) y lo devuelve como dict.

    Lanza ContextoRealError ante cualquier problema: nombre inválido, archivo inexistente o ilegible,
    JSON mal formado o un contenido que no es un objeto con datos. Los mensajes no incluyen rutas del servidor.
    """
    nombre = nombre if nombre is not None else config.KIT_MARCA
    carpeta = Path(carpeta) if carpeta is not None else config.KITS_DIR
    limpio = (nombre or "").strip()

    # Debe ser solo un nombre de archivo: nada de rutas, unidades de disco ni "..".
    if not limpio or limpio in (".", "..") or "\x00" in limpio or any(c in limpio for c in _PROHIBIDOS_EN_NOMBRE):
        raise ContextoRealError(
            "kit_invalido",
            "El nombre del kit de marca debe ser solo el nombre del archivo (sin carpetas ni rutas).",
        )

    ruta = carpeta / f"{limpio}.json"
    # Sin el archivo no hay kit.
    if not ruta.is_file():
        raise ContextoRealError("kit_no_encontrado", f"No existe el kit de marca «{limpio}».")

    try:
        texto = ruta.read_text(encoding="utf-8-sig")  # utf-8-sig tolera el BOM que deja PowerShell
    except (OSError, UnicodeDecodeError) as exc:
        raise ContextoRealError("kit_no_legible", f"No se pudo leer el kit de marca «{limpio}» como UTF-8.") from exc

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ContextoRealError(
            "kit_json_invalido",
            f"El kit de marca «{limpio}» no es un JSON válido (línea {exc.lineno}, columna {exc.colno}).",
        ) from exc

    # El kit debe ser un objeto JSON con contenido (una lista, un texto o {} no sirven a los agentes).
    if not isinstance(datos, dict) or not datos:
        raise ContextoRealError("kit_invalido", f"El kit de marca «{limpio}» debe ser un objeto JSON con contenido.")
    return datos


def construir_contexto(cliente: ClienteLLM | None = None, kit: dict | None = None) -> ContextoReal:
    """Arma el contexto del modo real; los parámetros opcionales existen para las pruebas.

    Sin `cliente` construye un `ClienteGroq` (lanza LLMError "sin_clave" si falta GROQ_API_KEY).
    Sin `kit` lo carga de config.KITS_DIR / f"{config.KIT_MARCA}.json" (lanza ContextoRealError si falla).
    """
    cliente = cliente if cliente is not None else ClienteGroq()
    kit = kit if kit is not None else cargar_kit()
    return ContextoReal(cliente=cliente, kit=kit)