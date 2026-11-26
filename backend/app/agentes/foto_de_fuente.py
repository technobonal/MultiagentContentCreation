"""foto_de_fuente.py — Elige, por código, las fotos de un PDF para los huecos de imagen de la plantilla.

Une las piezas de `fuentes/`: saca las imágenes del PDF y, para cada hueco, recorta de cada imagen la zona más grande
SIN texto con la proporción de ese hueco. Reparte las fotos sin repetir: los huecos más grandes eligen primero y cada
imagen se usa una sola vez; con menos imágenes que huecos, algunos huecos quedan vacíos. Sin modelos y sin red.
En una página escaneada (la imagen ES la página) el texto de la imagen se localiza con OCR y el recorte lo evita;
en una foto embebida de un PDF normal no hay texto encima, así que se recorta el centro.
Si la imagen tiene una cara, el recorte tiene que abarcar la cabeza entera; si en un hueco no cabe (por ejemplo, uno muy
ancho), esa foto no va ahí y queda para otro.

No decide la licencia ni emite eventos: eso es del orquestador.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from app import config
from app.fuentes.cargador_fuente import FuenteCargada
from app.fuentes.detectar_caras import Caja, caja_de_cabeza, detectar_caras
from app.fuentes.extraer_imagenes import ImagenExtraida, extraer_imagenes
from app.fuentes.ocr_pdf import Motor, leer_paginas
from app.fuentes.recortar_foto import mejor_recorte, recortar_imagen, tiene_contenido


log = logging.getLogger(__name__)

Detector = Callable[[bytes], list[Caja]]


def _cabezas(imagen: ImagenExtraida, detector: Detector) -> Caja | None:
    """La caja que abarca las cabezas de todas las caras de la imagen, o None si no hay (o si el detector falla)."""
    try:
        caras = detector(imagen.datos)
    except Exception as exc:  # sin detector las fotos siguen saliendo, solo que sin cuidar las cabezas
        log.warning("No se pudieron buscar caras en la página %s (%s): %s", imagen.pagina, type(exc).__name__, exc)
        return None
    if not caras:
        return None
    cajas = [caja_de_cabeza(c) for c in caras]
    return (min(c[0] for c in cajas), min(c[1] for c in cajas), max(c[2] for c in cajas), max(c[3] for c in cajas))


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
    """Campos de imagen de la ficha que declaran su `hueco` (tamaño), en orden de slide. Sin hueco no reciben foto.

    El tamaño vive en la ficha de cada plantilla y un test lo compara con su SVG para que no se separen.
    """
    huecos = []
    for slide in ficha["slides"]:
        for campo in slide.get("campos", []):
            nombre = campo["nombre"].strip("{}")
            tamano = campo.get("hueco")
            if campo.get("tipo") == "imagen" and tamano:
                huecos.append(Hueco(slide["numero"], nombre, tamano["ancho"], tamano["alto"]))
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
    datos_pdf: bytes, huecos: list[Hueco], motor_ocr: Motor | None = None, max_paginas: int | None = None,
    detector: Detector = detectar_caras,
) -> dict[str, FotoPreparada]:
    """Una foto distinta para cada hueco que se pueda llenar: {campo: foto}. Síncrona: usa CPU."""
    max_paginas = config.FOTOS_MAX_PAGINAS if max_paginas is None else max_paginas
    candidatas = [i for i in extraer_imagenes(datos_pdf) if i.pagina <= max_paginas]
    if not candidatas or not huecos:
        return {}
    cajas = _cajas_por_pagina(datos_pdf, candidatas, motor_ocr, max_paginas)
    cabezas = {i.sha256: _cabezas(i, detector) for i in candidatas}  # una vez por imagen, no por cada hueco

    usadas: set[str] = set()
    elegidas: dict[str, FotoPreparada] = {}
    # Los huecos más grandes eligen primero (se llevan la mejor foto); a igual tamaño, el de slide menor.
    for hueco in sorted(huecos, key=lambda h: (-h.ancho * h.alto, h.slide)):
        propuestas = []  # (píxeles de ancho del recorte, imagen, recorte)
        for imagen in candidatas:
            if imagen.sha256 in usadas:
                continue
            texto = cajas.get(imagen.pagina, []) if imagen.cubre_pagina else []
            cabeza = cabezas[imagen.sha256]
            recorte = mejor_recorte(imagen.ancho, imagen.alto, texto, hueco.proporcion, obligatoria=cabeza)
            if recorte is None:
                continue
            if not texto and cabeza is None:  # sin texto ni cara que cuidar, el centro de la foto es mejor que la esquina
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
