"""Cliente del asesor: Cloudflare Workers AI, y solo modelos alojados por Cloudflare.

El asesor recibe texto de las fuentes de la persona. Según su documentación, Workers AI no usa ese contenido
para entrenar (revisado el 2026-11-26). Por eso la dirección no es configurable y solo se aceptan modelos «@cf/»:
Cloudflare también revende modelos de terceros, con otras condiciones. Si todos fallan, el asesor queda no
disponible: nunca se cambia a un modelo que no esté en la lista ni a otro proveedor.
La llamada HTTP se inyecta (`enviar`) para probar sin red. El token y la cuenta nunca se registran ni van en un error.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app import config

log = logging.getLogger(__name__)

# (url, cabeceras, cuerpo JSON, timeout) -> (código HTTP, JSON de respuesta)
Enviar = Callable[[str, dict[str, str], dict[str, Any], float], Awaitable[tuple[int, Any]]]

URL_BASE = "https://api.cloudflare.com/client/v4/accounts"
PREFIJO_PROPIO = "@cf/"  # modelos que aloja Cloudflare
_CUENTA = re.compile(r"[0-9a-fA-F]{32}")
# 404 o 410: ese modelo ya no está; otro de la lista puede que sí.
CODIGOS_DE_SALTO = {404, 408, 410, 429, 500, 502, 503, 504}


class AsesorNoDisponible(Exception):
    """No se pudo obtener consejo. `mensaje` es seguro de mostrar a la persona (sin la key)."""

    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


async def _enviar_httpx(url: str, cabeceras: dict[str, str], cuerpo: dict[str, Any], timeout: float) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=timeout) as cliente:
        respuesta = await cliente.post(url, headers=cabeceras, json=cuerpo)
    try:
        return respuesta.status_code, respuesta.json()
    except ValueError:
        return respuesta.status_code, None


def _objeto_json(respuesta: Any) -> dict | None:
    """El objeto JSON de la primera opción (tolera las vallas ```), o None si la respuesta no sirve."""
    try:
        eleccion = respuesta["choices"][0]
        if eleccion.get("finish_reason") == "length":
            return None  # cortada: faltarían frases
        texto = eleccion["message"]["content"].strip()
        dato = json.loads(texto[texto.index("{"):texto.rindex("}") + 1])
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None
    return dato if isinstance(dato, dict) else None


class ClienteAsesor:
    def __init__(
        self, api_key: str | None = None, modelos: tuple[str, ...] | None = None, enviar: Enviar | None = None,
        cuenta: str | None = None,
    ):
        self._api_key = config.CLOUDFLARE_API_TOKEN if api_key is None else api_key
        self._cuenta = config.CLOUDFLARE_ACCOUNT_ID if cuenta is None else cuenta
        self.modelos = config.ASESOR_MODELOS if modelos is None else modelos
        self._enviar = enviar or _enviar_httpx

    async def pedir(self, sistema: str, usuario: str, validar: Callable[[dict], bool]) -> tuple[dict, str]:
        """(respuesta válida, modelo que la dio) del primer modelo de la lista que conteste algo utilizable."""
        if not self._api_key:
            raise AsesorNoDisponible("Falta CLOUDFLARE_API_KEY_TOKEN en el .env.")
        # Va dentro de la dirección: solo se acepta con su forma exacta.
        if not _CUENTA.fullmatch(self._cuenta):
            raise AsesorNoDisponible("CLOUDFLARE_ACCOUNT_ID falta en el .env o no tiene 32 letras y números.")
        url = f"{URL_BASE}/{self._cuenta}/ai/v1/chat/completions"
        cabeceras = {"Authorization": f"Bearer {self._api_key}"}
        fallas: list[str] = []
        for modelo in self.modelos:
            if not modelo.startswith(PREFIJO_PROPIO):
                fallas.append(f"{modelo}: no es un modelo alojado por Cloudflare y no se usa")
                log.warning("Asesor: %s", fallas[-1])
                continue
            cuerpo = {
                "model": modelo, "temperature": 0, "max_tokens": config.ASESOR_MAX_TOKENS,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
                "response_format": {"type": "json_object"},
            }
            try:
                codigo, respuesta = await self._enviar(url, cabeceras, cuerpo, config.ASESOR_TIMEOUT_SEG)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                fallas.append(f"{modelo}: {type(exc).__name__}")
            else:
                if codigo == 200:
                    dato = _objeto_json(respuesta)
                    if dato is not None and validar(dato):
                        return dato, modelo
                    fallas.append(f"{modelo}: respuesta que no se puede usar")
                elif codigo in CODIGOS_DE_SALTO:
                    fallas.append(f"{modelo}: HTTP {codigo}")
                else:  # 401, 402, 400...: otro modelo no lo arregla
                    raise AsesorNoDisponible(f"Cloudflare rechazó el pedido con HTTP {codigo}.")
            log.warning("Asesor: %s", fallas[-1])
        raise AsesorNoDisponible("El asesor no está disponible ahora (" + "; ".join(fallas) + "). Probá más tarde.")
