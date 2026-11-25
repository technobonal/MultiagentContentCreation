"""cliente_vision.py — Describe una imagen con modelos de visión gratis de OpenRouter, con cascada de respaldo.

No es un agente: es un cliente. Prueba los modelos de `config.OPENROUTER_MODELOS_VISION` en orden y salta al siguiente
SOLO por fallas técnicas (429, 5xx, timeout, red) o por una respuesta vacía (los modelos que razonan pueden gastar todo
el tope pensando y no escribir nada). Un error de credenciales o de pedido (401, 402, 400...) corta de inmediato:
probar otro modelo con la misma key o el mismo pedido no lo arregla.

Los modelos razonadores reciben `reasoning: {enabled: false}`: sin eso `nemotron` tardaba 16 s y devolvía vacío.
La llamada HTTP se inyecta (`enviar`) para probar sin red. La key nunca se registra ni se incluye en un mensaje de error.
"""
from __future__ import annotations

import base64
import io
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app import config

log = logging.getLogger(__name__)

# (url, cabeceras, cuerpo JSON, timeout) -> (código HTTP, JSON de respuesta)
Enviar = Callable[[str, dict[str, str], dict[str, Any], float], Awaitable[tuple[int, Any]]]

LADO_MAX_PX = 1024  # una imagen más grande no mejora la descripción y encarece el pedido
CODIGOS_DE_SALTO = {408, 429, 500, 502, 503, 504}


class VisionError(Exception):
    """No se pudo describir la imagen. `codigo` es estable; `mensaje` es seguro de mostrar (sin la key)."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class RespuestaVision:
    texto: str
    modelo: str
    # Un renglón por modelo que no respondió antes del que sí lo hizo: «modelo: motivo».
    saltos: tuple[str, ...] = field(default=())


def preparar_imagen(datos: bytes, lado_max: int = LADO_MAX_PX) -> tuple[bytes, str]:
    """Reduce la imagen a `lado_max` px como mucho y la devuelve como JPEG: (bytes, tipo MIME)."""
    from PIL import Image

    imagen = Image.open(io.BytesIO(datos)).convert("RGB")
    imagen.thumbnail((lado_max, lado_max))
    salida = io.BytesIO()
    imagen.save(salida, "JPEG", quality=80)
    return salida.getvalue(), "image/jpeg"


async def _enviar_httpx(url: str, cabeceras: dict[str, str], cuerpo: dict[str, Any], timeout: float) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=timeout) as cliente:
        respuesta = await cliente.post(url, headers=cabeceras, json=cuerpo)
    try:
        return respuesta.status_code, respuesta.json()
    except ValueError:
        return respuesta.status_code, None


def _texto_de(json_respuesta: Any) -> str:
    """Texto de la primera opción, o cadena vacía si no hay (respuesta vacía o con otra forma)."""
    try:
        contenido = json_respuesta["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""
    return contenido.strip() if isinstance(contenido, str) else ""


class ClienteVision:
    def __init__(
        self,
        api_key: str | None = None,
        modelos: tuple[str, ...] | None = None,
        enviar: Enviar | None = None,
        timeout_seg: float | None = None,
    ):
        self._api_key = config.OPENROUTER_API_KEY if api_key is None else api_key
        self.modelos = modelos if modelos is not None else config.OPENROUTER_MODELOS_VISION
        self._enviar = enviar or _enviar_httpx
        self._timeout = timeout_seg if timeout_seg is not None else config.OPENROUTER_TIMEOUT_SEG

    async def describir(
        self, imagen: bytes, instruccion: str, *, mime: str = "image/jpeg", max_tokens: int = 300
    ) -> RespuestaVision:
        """Responde a `instruccion` sobre la imagen con el primer modelo que conteste."""
        if not self._api_key:
            raise VisionError("sin_api_key", "Falta OPENROUTER_API_KEY en el .env.")
        if not self.modelos:
            raise VisionError("sin_modelos", "No hay modelos de visión configurados (OPENROUTER_MODELOS_VISION).")
        url = f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
        cabeceras = {"Authorization": f"Bearer {self._api_key}"}
        data_url = f"data:{mime};base64,{base64.b64encode(imagen).decode()}"
        saltos: list[str] = []
        for modelo in self.modelos:
            cuerpo = {
                "model": modelo, "max_tokens": max_tokens, "temperature": 0,
                "reasoning": {"enabled": False},
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": instruccion},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]}],
            }
            try:
                codigo, json_respuesta = await self._enviar(url, cabeceras, cuerpo, self._timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                saltos.append(f"{modelo}: {type(exc).__name__}")
                log.warning("Visión %s falló (%s); se prueba el siguiente", modelo, type(exc).__name__)
                continue
            if codigo == 200:
                texto = _texto_de(json_respuesta)
                if texto:
                    return RespuestaVision(texto, modelo, tuple(saltos))
                saltos.append(f"{modelo}: respuesta vacía")
                log.warning("Visión %s devolvió una respuesta vacía; se prueba el siguiente", modelo)
                continue
            if codigo in CODIGOS_DE_SALTO:
                saltos.append(f"{modelo}: HTTP {codigo}")
                log.warning("Visión %s respondió HTTP %s; se prueba el siguiente", modelo, codigo)
                continue
            # 400, 401, 402, 403...: el problema no es del modelo, probar otro no lo arregla.
            raise VisionError("pedido_rechazado", f"OpenRouter rechazó el pedido con HTTP {codigo} ({modelo}).")
        raise VisionError("sin_respuesta", "Ningún modelo de visión respondió: " + "; ".join(saltos) + ".")
