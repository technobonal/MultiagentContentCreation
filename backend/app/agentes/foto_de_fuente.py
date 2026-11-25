"""foto_de_fuente.py — Elige, por código, las fotos de un PDF para los huecos de imagen de la plantilla.

Une las piezas de `fuentes/`: saca las imágenes del PDF y, para cada hueco, recorta de cada imagen la zona más grande
SIN texto con la proporción de ese hueco. Reparte las fotos sin repetir: los huecos más grandes eligen primero y cada
imagen se usa una sola vez; con menos imágenes que huecos, algunos huecos quedan vacíos. Sin modelos y sin red.
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
from app.fuentes.extraer_imagenes import ImagenExtraida, extraer_imagenes
from app.fuentes.ocr_pdf import Motor, leer_paginas
from app.fuentes.recortar_foto import mejor_recorte, recortar_imagen, tiene_contenido

# Tamaño de cada hueco de imagen de la plantilla, en píxeles (templates/catalog/.../template.svg, grupos con
# class="hueco-imagen"). Un test compara esta tabla con el SVG para que no se separen.
TAMANO_HUECO: dict[str, tuple[int, int]] = {
    "imagen_portada": (920, 280),  # slide 1, debajo del subtítulo
    "imagen_producto": (920, 422),  # slide 2
    "imagen_apoyo_3": (920, 250),  # slide 3, debajo del cuerpo
    "imagen_apoyo_4": (920, 250),  # slide 4
    "imagen_cierre": (920, 300),  # slide 5, debajo del CTA
}


@dataclass(frozen=True)
class Hueco:
    slide: int
    campo: str  # sin llaves
    ancho: int
    alto: int

    @property
    def proporcion(self) -> float:
        return self.ancho / self.alto


@dataclass(frozen=True)
class FotoPreparada:
    datos: bytes  # JPEG ya recortado, del ancho del hueco como mucho
    mime: str
    pagina: int  # página del PDF de donde salió
    texto_alternativo: str


def huecos_de_ficha(ficha: dict) -> list[Hueco]:
    """Campos de imagen de la ficha con tamaño conocido, en orden de slide. Un campo de imagen sin tamaño se ignora."""
    huecos = []
    for slide in ficha["slides"]:
        for campo in slide.get("campos", []):
            nombre = campo["nombre"].strip("{}")
            if campo.get("tipo") == "imagen" and nombre in TAMANO_HUECO:
                huecos.append(Hueco(slide["numero"], nombre, *TAMANO_HUECO[nombre]))
    return huecos


def _cajas_por_pagina(datos_pdf: bytes, candidatas: list[ImagenExtraida], motor_ocr: Motor | None, max_paginas: int) -> dict[int, list]:
    """Cajas de texto (normalizadas) de las páginas escaneadas; solo se hace OCR si alguna imagen ocupa toda la página."""
    if not any(i.cubre_pagina for i in candidatas):
        return {}
    import pymupdf

    with pymupdf.open(stream=datos_pdf, filetype="pdf") as doc:
        doc.select(list(range(min(max_paginas, doc.page_count))))  # solo las páginas que se miran
        return {n: leida.cajas_normalizadas() for n, leida in enumerate(leer_paginas(doc, motor_ocr), start=1)}


def fotos_de_pdf(
    datos_pdf: bytes, huecos: list[Hueco], motor_ocr: Motor | None = None, max_paginas: int | None = None
) -> dict[str, FotoPreparada]:
    """Una foto distinta para cada hueco que se pueda llenar: {campo: foto}. Síncrona: usa CPU."""
    max_paginas = config.FOTOS_MAX_PAGINAS if max_paginas is None else max_paginas
    candidatas = [i for i in extraer_imagenes(datos_pdf) if i.pagina <= max_paginas]
    if not candidatas or not huecos:
        return {}
    cajas = _cajas_por_pagina(datos_pdf, candidatas, motor_ocr, max_paginas)

    usadas: set[str] = set()
    elegidas: dict[str, FotoPreparada] = {}
    # Los huecos más grandes eligen primero (se llevan la mejor foto); a igual tamaño, el de slide menor.
    for hueco in sorted(huecos, key=lambda h: (-h.ancho * h.alto, h.slide)):
        propuestas = []  # (píxeles de ancho del recorte, imagen, recorte)
        for imagen in candidatas:
            if imagen.sha256 in usadas:
                continue
            texto = cajas.get(imagen.pagina, []) if imagen.cubre_pagina else []
            recorte = mejor_recorte(imagen.ancho, imagen.alto, texto, hueco.proporcion)
            if recorte is None:
                continue
            if not texto:  # sin texto que evitar, el centro de la foto es mejor que la esquina
                recorte = dataclasses.replace(recorte, x=(1 - recorte.ancho) / 2, y=(1 - recorte.alto) / 2)
            propuestas.append((round(recorte.ancho * imagen.ancho), imagen, recorte))
        # De la más grande a la más chica; la primera con contenido (no un fondo liso) gana. `sorted` es estable: a igual tamaño, la primera página.
        for _, imagen, recorte in sorted(propuestas, key=lambda p: -p[0]):
            jpeg = recortar_imagen(imagen.datos, recorte, hueco.ancho)
            if not tiene_contenido(jpeg):
                continue
            usadas.add(imagen.sha256)
            elegidas[hueco.campo] = FotoPreparada(jpeg, "image/jpeg", imagen.pagina, f"Imagen de la página {imagen.pagina} de la fuente")
            break
    return elegidas


async def preparar_fotos(
    fuente: FuenteCargada, huecos: list[Hueco], carpeta: Path | None = None, motor_ocr: Motor | None = None
) -> dict[str, FotoPreparada]:
    """Fotos para los huecos a partir de la fuente del run; {} si la fuente no es un PDF o no hay fotos que sirvan.

    Relee el PDF de la carpeta de fuentes (la `FuenteCargada` solo guarda el texto) y trabaja en un hilo aparte.
    """
    if Path(fuente.referencia).suffix.lower() != ".pdf":
        return {}
    ruta = (Path(carpeta) if carpeta is not None else config.FUENTES_DIR) / fuente.referencia
    if not ruta.is_file():
        return {}
    return await asyncio.to_thread(fotos_de_pdf, ruta.read_bytes(), huecos, motor_ocr)
