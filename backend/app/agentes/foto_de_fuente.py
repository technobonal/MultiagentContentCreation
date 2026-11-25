"""foto_de_fuente.py — Elige, por código, la foto de un PDF para el hueco de imagen de la plantilla.

Une las piezas de `fuentes/`: saca las imágenes del PDF, recorta de cada una la zona más grande SIN texto con la
proporción del hueco y se queda con la de más píxeles que tenga contenido (no un fondo liso). Sin modelos y sin red.
En una página escaneada (la imagen ES la página) el texto de la imagen se localiza con OCR y el recorte lo evita;
en una foto embebida de un PDF normal no hay texto encima, así que se recorta el centro.

No decide la licencia ni emite eventos: eso es del orquestador.
"""
from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.fuentes.cargador_fuente import FuenteCargada
from app.fuentes.extraer_imagenes import extraer_imagenes
from app.fuentes.ocr_pdf import Motor, leer_paginas
from app.fuentes.recortar_foto import mejor_recorte, recortar_imagen, tiene_contenido

# Tamaño del hueco `imagen_producto` de la plantilla (templates/catalog/.../template.svg, grupo imagen-producto).
FOTO_ANCHO = 920
FOTO_ALTO = 422
PROPORCION = FOTO_ANCHO / FOTO_ALTO


@dataclass(frozen=True)
class FotoPreparada:
    datos: bytes  # JPEG ya recortado, de FOTO_ANCHO px de ancho como mucho
    mime: str
    pagina: int  # página del PDF de donde salió
    texto_alternativo: str


def foto_de_pdf(datos_pdf: bytes, motor_ocr: Motor | None = None, max_paginas: int | None = None) -> FotoPreparada | None:
    """La mejor foto del PDF recortada al hueco, o None si no hay imágenes o ninguna sirve. Síncrona: usa CPU."""
    max_paginas = config.FOTOS_MAX_PAGINAS if max_paginas is None else max_paginas
    candidatas = [i for i in extraer_imagenes(datos_pdf) if i.pagina <= max_paginas]
    if not candidatas:
        return None

    cajas_por_pagina: dict[int, list] = {}
    if any(i.cubre_pagina for i in candidatas):
        import pymupdf

        with pymupdf.open(stream=datos_pdf, filetype="pdf") as doc:
            doc.select(list(range(min(max_paginas, doc.page_count))))  # solo las páginas que se miran
            for numero, leida in enumerate(leer_paginas(doc, motor_ocr), start=1):
                cajas_por_pagina[numero] = leida.cajas_normalizadas()

    mejor: tuple[int, FotoPreparada] | None = None  # (píxeles de ancho del recorte, foto)
    for imagen in candidatas:
        cajas = cajas_por_pagina.get(imagen.pagina, []) if imagen.cubre_pagina else []
        recorte = mejor_recorte(imagen.ancho, imagen.alto, cajas, PROPORCION)
        if recorte is None:
            continue
        if not cajas:  # sin texto que evitar, el centro de la foto es mejor que la esquina
            recorte = dataclasses.replace(recorte, x=(1 - recorte.ancho) / 2, y=(1 - recorte.alto) / 2)
        jpeg = recortar_imagen(imagen.datos, recorte, FOTO_ANCHO)
        if not tiene_contenido(jpeg):
            continue
        pixeles = round(recorte.ancho * imagen.ancho)
        if mejor is None or pixeles > mejor[0]:
            mejor = (pixeles, FotoPreparada(jpeg, "image/jpeg", imagen.pagina, f"Imagen de la página {imagen.pagina} de la fuente"))
    return mejor[1] if mejor else None


async def preparar_foto(
    fuente: FuenteCargada, carpeta: Path | None = None, motor_ocr: Motor | None = None
) -> FotoPreparada | None:
    """Foto para la plantilla a partir de la fuente del run; None si la fuente no es un PDF o no hay una foto que sirva.

    Relee el PDF de la carpeta de fuentes (la `FuenteCargada` solo guarda el texto) y trabaja en un hilo aparte.
    """
    if Path(fuente.referencia).suffix.lower() != ".pdf":
        return None
    ruta = (Path(carpeta) if carpeta is not None else config.FUENTES_DIR) / fuente.referencia
    if not ruta.is_file():
        return None
    return await asyncio.to_thread(foto_de_pdf, ruta.read_bytes(), motor_ocr)
