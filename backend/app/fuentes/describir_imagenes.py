"""describir_imagenes.py — Pide una descripción de cada imagen extraída de un PDF a la cascada de visión.

Une `extraer_imagenes` con `ClienteVision`. Una imagen que falla no aborta a las demás: queda con `error`. Por defecto
se saltan las páginas escaneadas completas (`cubre_pagina`): no son fotos reutilizables. Las imágenes se piden de a
una (los modelos gratis se limitan rápido) y con un tope de cantidad.

Privacidad: cada imagen describida sale hacia un tercero (OpenRouter). Quien llame debe decidir antes si la fuente
puede enviarse; este módulo no lo decide.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agentes.cliente_vision import RespuestaVision, VisionError, preparar_imagen
from app.fuentes.extraer_imagenes import ImagenExtraida

MAXIMO_POR_DEFECTO = 6

INSTRUCCION = (
    "Describe en una sola frase, en español, qué muestra esta imagen. "
    "Di solo lo que se ve; no inventes texto ni datos que no aparezcan."
)


class _Describidor(Protocol):
    async def describir(self, imagen: bytes, instruccion: str, *, mime: str = ..., max_tokens: int = ...) -> RespuestaVision: ...


@dataclass(frozen=True)
class ImagenDescrita:
    pagina: int
    sha256: str
    cubre_pagina: bool
    descripcion: str | None  # None si falló
    modelo: str | None
    error: str | None  # mensaje seguro (sin la key) si falló


async def describir_imagenes(
    imagenes: tuple[ImagenExtraida, ...],
    cliente: _Describidor,
    *,
    incluir_paginas_completas: bool = False,
    maximo: int = MAXIMO_POR_DEFECTO,
) -> tuple[ImagenDescrita, ...]:
    """Descripción de cada imagen elegible, en el orden en que aparecen, hasta `maximo`."""
    elegibles = [i for i in imagenes if incluir_paginas_completas or not i.cubre_pagina][: max(0, maximo)]
    resultado: list[ImagenDescrita] = []
    for imagen in elegibles:
        try:
            datos, mime = preparar_imagen(imagen.datos)
            r = await cliente.describir(datos, INSTRUCCION, mime=mime)
        except VisionError as exc:
            resultado.append(ImagenDescrita(imagen.pagina, imagen.sha256, imagen.cubre_pagina, None, None, exc.mensaje))
            # Sin credenciales o con un pedido rechazado, las demás imágenes fallarían igual: se corta.
            if exc.codigo in ("sin_api_key", "sin_modelos", "pedido_rechazado"):
                break
            continue
        except Exception as exc:  # imagen ilegible para Pillow u otra falla local: no tumba a las demás
            resultado.append(ImagenDescrita(
                imagen.pagina, imagen.sha256, imagen.cubre_pagina, None, None, f"No se pudo preparar la imagen ({type(exc).__name__})."))
            continue
        resultado.append(ImagenDescrita(imagen.pagina, imagen.sha256, imagen.cubre_pagina, r.texto, r.modelo, None))
    return tuple(resultado)
