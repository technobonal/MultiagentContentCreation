"""ocr_pdf.py — OCR de las páginas de un PDF escaneado (sin capa de texto), con rapidocr local.

El motor se importa y se crea la primera vez que hace falta (cargarlo tarda y casi nunca se usa) y se puede
reemplazar en los tests: un «motor» es una función que recibe una imagen (numpy RGB) y devuelve una lista de
`(caja, texto)`, donde la caja son 4 puntos `(x, y)`. El orden de lectura se arma aquí, en código.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from statistics import median

from app import config

Caja = Sequence[Sequence[float]]
Motor = Callable[[object], list[tuple[Caja, str]]]

_motor_por_defecto: Motor | None = None


def _crear_motor() -> Motor:
    """Motor de rapidocr. Lanza ImportError si no está instalado."""
    from rapidocr import RapidOCR

    ocr = RapidOCR()

    def motor(imagen: object) -> list[tuple[Caja, str]]:
        r = ocr(imagen)
        if r is None or r.txts is None or r.boxes is None:
            return []
        return list(zip(r.boxes, r.txts))

    return motor


def motor_por_defecto() -> Motor:
    global _motor_por_defecto
    if _motor_por_defecto is None:
        _motor_por_defecto = _crear_motor()
    return _motor_por_defecto


def ordenar_en_filas(lineas: list[tuple[Caja, str]]) -> list[str]:
    """Une los trozos que el OCR devuelve sueltos en filas de lectura: de arriba abajo y, en cada fila, de izquierda a derecha.

    Dos trozos van en la misma fila si sus centros verticales difieren menos de 0,6 veces la altura mediana de las cajas.
    """
    items = []
    for caja, texto in lineas:
        texto = " ".join(texto.split())
        if not texto:
            continue
        ys = [p[1] for p in caja]
        xs = [p[0] for p in caja]
        items.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), texto))
    if not items:
        return []
    tolerancia = 0.6 * median(i[2] for i in items)
    items.sort(key=lambda i: i[0])
    filas: list[list[tuple[float, float, float, str]]] = [[items[0]]]
    for it in items[1:]:
        if it[0] - filas[-1][-1][0] <= tolerancia:
            filas[-1].append(it)
        else:
            filas.append([it])
    return [" ".join(i[3] for i in sorted(fila, key=lambda i: i[1])) for fila in filas]


def ocr_de_paginas(doc: object, motor: Motor | None = None) -> list[list[str]]:
    """Lee con OCR cada página de un documento PyMuPDF abierto: una lista de filas de texto por página."""
    import numpy as np
    import pymupdf

    motor = motor or motor_por_defecto()
    paginas: list[list[str]] = []
    for pagina in doc:  # type: ignore[attr-defined]
        ancho, alto = pagina.rect.width, pagina.rect.height
        # 150 ppp como mucho, y el lado mayor nunca pasa de PDF_OCR_LADO_MAX_PX (las páginas grandes tardan mucho).
        zoom = min(150 / 72, config.PDF_OCR_LADO_MAX_PX / max(ancho, alto, 1))
        pix = pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB)
        imagen = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        paginas.append(ordenar_en_filas(motor(imagen)))
    return paginas
