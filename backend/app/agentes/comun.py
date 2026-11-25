"""Utilidades compartidas por los agentes (estratega, redactor y más adelante el revisor).

Contiene tres piezas:
- `AgenteError`: error de un agente, con código estable y mensaje apto para el usuario.
- `cargar_prompt`: lee un prompt de la carpeta `prompts/` y le quita los comentarios.
- `pedir_json`: pide una respuesta JSON al LLM, la valida y reintenta si salió mal.

Orden del prompt y caché de Groq: el caché funciona por prefijo idéntico, así que los
agentes ponen primero lo fijo (el prompt del sistema, sin placeholders) y al final lo
variable (el mensaje del usuario). Por eso `cargar_prompt` devuelve el texto idéntico
byte a byte en cada llamada.
"""

import json
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agentes.cliente_llm import ClienteLLM, RespuestaLLM

# Carpeta con los prompts (uno por archivo .md), junto a este módulo.
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Comentarios de HTML (<!-- ... -->), también de varias líneas: sirven para documentar el prompt y no viajan al modelo.
_COMENTARIO_PROMPT = re.compile(r"<!--.*?-->", re.DOTALL)

# Valla de código que algunos modelos ponen alrededor del JSON (```json ... ```).
_VALLA_CODIGO = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)

# Un validador recibe el dato ya parseado y devuelve la lista de motivos de rechazo (vacía = válido).
Validador = Callable[[Any], list[str]]


class AgenteError(Exception):
    """Fallo de un agente. `codigo` es estable (para pruebas y mensajes); `mensaje` va al usuario."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@lru_cache(maxsize=None)
def cargar_prompt(nombre: str, carpeta: Path | None = None) -> str:
    """Lee `prompts/<nombre>.md`, le quita los comentarios HTML y devuelve el texto limpio.

    El resultado se guarda en caché de memoria: es el mismo objeto en cada llamada, lo que
    mantiene idéntico el prefijo que ve Groq. `carpeta` existe para las pruebas.
    """
    base = Path(carpeta) if carpeta is not None else PROMPTS_DIR
    ruta = base / f"{nombre}.md"
    # Un prompt que falta es un error de despliegue: se avisa con claridad al arrancar el run.
    if not ruta.is_file():
        raise AgenteError("prompt_no_encontrado", f"No existe el prompt «{nombre}» en {base}.")
    texto = _COMENTARIO_PROMPT.sub("", ruta.read_text(encoding="utf-8"))
    # Se colapsan las líneas en blanco que dejan los comentarios al quitarse.
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    # Un prompt vacío tras quitar comentarios no sirve de nada.
    if not texto:
        raise AgenteError("prompt_vacio", f"El prompt «{nombre}» quedó vacío.")
    return texto


def extraer_json(texto: str) -> Any:
    """Convierte el texto del modelo en un objeto JSON, tolerando una valla ```json alrededor.

    Lanza ValueError con un motivo corto si no es JSON válido.
    """
    limpio = texto.strip()
    valla = _VALLA_CODIGO.match(limpio)
    # Si viene envuelto en una valla de código, se usa solo su interior.
    if valla:
        limpio = valla.group(1).strip()
    try:
        return json.loads(limpio)
    except json.JSONDecodeError as exc:
        raise ValueError(f"no es JSON válido ({exc.msg}, posición {exc.pos})") from exc


async def pedir_json(
    cliente: ClienteLLM,
    rol: str,
    mensajes: list[dict[str, str]],
    validar: Validador,
    *,
    max_tokens: int,
    reintentos: int = 1,
    temperatura: float = 0.2,
    permitir_fallback: bool | None = None,
    extra: dict[str, Any] | None = None,
    validar_ultimo: Validador | None = None,
) -> tuple[Any, RespuestaLLM]:
    """Pide un JSON al LLM del `rol`, lo valida y reintenta si la respuesta no sirve.

    Devuelve (dato_validado, respuesta). En cada reintento por JSON o contenido inválido se
    añade al diálogo la respuesta anterior y los motivos, para que el modelo corrija.
    Una salida truncada NO se reintenta: repetir el mismo pedido la volvería a cortar.
    Los errores del cliente (LLMError: sin cupo, pedido grande, API) se propagan sin tocar.

    `validar_ultimo` (opcional) es un validador más tolerante que se usa SOLO en el último
    intento, cuando ya no quedan correcciones por pedir. Sirve para aceptar con una pérdida
    menor (por ejemplo, descartar un detalle que el modelo no supo corregir) en vez de tumbar
    todo el pedido. Sin él, todos los intentos usan `validar`. Con `reintentos=0` el único
    intento es también el último.

    Lanza AgenteError con código `salida_truncada` o `salida_invalida`.
    """
    dialogo = list(mensajes)  # copia: no se modifica la lista del llamador
    motivos: list[str] = []

    # Intento inicial más los reintentos permitidos.
    for intento in range(reintentos + 1):
        # En el último intento se usa el validador tolerante (si lo hay); antes, el estricto.
        es_ultimo = intento == reintentos
        validador = validar_ultimo if (es_ultimo and validar_ultimo is not None) else validar

        resp = await cliente.completar(
            rol,
            dialogo,
            temperatura=temperatura,
            json_mode=True,
            permitir_fallback=permitir_fallback,
            max_tokens=max_tokens,
            extra=extra,
        )
        # Salida cortada o vacía: el JSON estaría incompleto, así que se corta aquí.
        if resp.truncada:
            raise AgenteError(
                "salida_truncada",
                f"La respuesta del modelo se cortó o llegó vacía (rol {rol}, tope {max_tokens} tokens).",
            )

        try:
            dato = extraer_json(resp.texto)
            motivos = validador(dato)  # [] si cumple las reglas del agente
        except ValueError as exc:
            motivos = [str(exc)]
            dato = None

        # Sin motivos de rechazo: respuesta aceptada.
        if not motivos:
            return dato, resp

        # Quedan reintentos: se devuelve al modelo su respuesta y qué corregir.
        if intento < reintentos:
            dialogo = dialogo + [
                {"role": "assistant", "content": resp.texto},
                {
                    "role": "user",
                    "content": "Tu respuesta no es válida:\n- "
                    + "\n- ".join(motivos)
                    + "\nDevuelve de nuevo SOLO el JSON corregido.",
                },
            ]

    # Se agotaron los intentos con la última respuesta todavía inválida.
    raise AgenteError("salida_invalida", "El modelo no devolvió una respuesta válida: " + "; ".join(motivos))