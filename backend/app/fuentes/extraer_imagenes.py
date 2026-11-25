"""extraer_imagenes.py — Saca las imágenes embebidas de un PDF, sin decidir si se pueden usar.

Solo extrae y describe: no hay filtro de licencia ni asignación a slides (eso va después y con bloqueo por defecto).
Cada imagen distinta aparece una sola vez (un logo repetido en 12 páginas es una imagen), y las muy chicas
(íconos, viñetas) se descartan. Una imagen que cubre casi toda la página es una página escaneada, no una foto:
se marca con `cubre_pagina` para que quien la use no la tome por una foto.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

LADO_MIN_PX = 200  # el lado menor mínimo: por debajo son íconos o viñetas
COBERTURA_PAGINA = 0.9  # fracción del área de la página a partir de la cual la imagen es la página entera


@dataclass(frozen=True)
class ImagenExtraida:
    pagina: int  # primera página (desde 1) donde aparece
    ancho: int
    alto: int
    formato: str  # extensión que da PyMuPDF: jpeg, png, jpx...
    datos: bytes
    sha256: str
    cubre_pagina: bool


def extraer_imagenes(datos_pdf: bytes, lado_min: int = LADO_MIN_PX) -> tuple[ImagenExtraida, ...]:
    """Imágenes distintas del PDF, en orden de aparición. Lanza ValueError si el archivo no es un PDF legible."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - depende del entorno
        import fitz as pymupdf

    try:
        doc = pymupdf.open(stream=datos_pdf, filetype="pdf")
    except Exception as exc:  # PyMuPDF lanza varios tipos según el daño del archivo
        raise ValueError("No es un PDF válido o está dañado.") from exc

    vistas: set[str] = set()
    imagenes: list[ImagenExtraida] = []
    with doc:
        for numero, pagina in enumerate(doc, start=1):
            area_pagina = max(pagina.rect.width * pagina.rect.height, 1.0)
            for info in pagina.get_images(full=True):
                xref = info[0]
                extraida = doc.extract_image(xref)
                if not extraida:
                    continue
                ancho, alto = extraida["width"], extraida["height"]
                huella = hashlib.sha256(extraida["image"]).hexdigest()
                if min(ancho, alto) < lado_min or huella in vistas:
                    continue
                vistas.add(huella)
                cobertura = max((r.width * r.height for r in pagina.get_image_rects(xref)), default=0.0) / area_pagina
                imagenes.append(ImagenExtraida(
                    pagina=numero, ancho=ancho, alto=alto, formato=extraida["ext"],
                    datos=extraida["image"], sha256=huella, cubre_pagina=cobertura >= COBERTURA_PAGINA,
                ))
    return tuple(imagenes)
