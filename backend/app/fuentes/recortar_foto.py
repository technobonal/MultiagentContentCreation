"""recortar_foto.py — Elige, por código, el recorte más grande SIN TEXTO de una imagen para un hueco de proporción fija.

No usa modelos: recibe las cajas del texto (las que da el OCR) y busca con una ventana deslizante, de la más grande a
la más chica, una zona de la proporción pedida con casi nada de texto. Sirve para folletos donde el texto va encima de
la foto: el recorte evita las letras en vez de intentar borrarlas. Las figuras con cifras nunca se redibujan ni se
tocan: esto solo recorta.

Las cajas y el resultado van en coordenadas normalizadas (0 a 1), así que no dependen de la resolución.
"""
from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

Caja = tuple[float, float, float, float]  # x1, y1, x2, y2

CUADRICULA = 240  # celdas del lado mayor en que se divide la imagen para medir el texto
SOLAPE_MAX = 0.0  # fracción de la ventana que puede tapar el texto: con 0,02 quedaban letras sueltas en el borde del recorte
ESCALA_MIN = 0.30  # ancho mínimo de la ventana, como fracción del ancho de la imagen
PASO_ESCALA = 0.05
CONTRASTE_MIN = 20.0  # desviación típica del gris por debajo de la cual el recorte es un fondo liso (medido: 8,7 vs 41 a 69)
MARGEN_TEXTO = 0.012  # el texto se ensancha esta fracción del lado mayor: las letras no tocan el borde del recorte


@dataclass(frozen=True)
class Recorte:
    x: float  # esquina superior izquierda, entre 0 y 1
    y: float
    ancho: float  # entre 0 y 1
    alto: float
    solape: float  # fracción de la ventana cubierta por texto (0 = limpia)

    def en_pixeles(self, ancho_img: int, alto_img: int) -> tuple[int, int, int, int]:
        """(izquierda, arriba, derecha, abajo) en píxeles de una imagen de ese tamaño."""
        izq, arr = round(self.x * ancho_img), round(self.y * alto_img)
        der, aba = round((self.x + self.ancho) * ancho_img), round((self.y + self.alto) * alto_img)
        return izq, arr, min(der, ancho_img), min(aba, alto_img)


def mejor_recorte(
    ancho_img: int, alto_img: int, cajas: Sequence[Caja], proporcion: float,
    solape_max: float = SOLAPE_MAX, escala_min: float = ESCALA_MIN,
) -> Recorte | None:
    """El recorte más grande de `proporcion` (ancho/alto) con a lo sumo `solape_max` de texto, o None si no hay.

    Entre los de igual tamaño gana el de menos texto y, si empatan, el más alto de la imagen.
    """
    import numpy as np

    if ancho_img <= 0 or alto_img <= 0 or proporcion <= 0:
        return None
    lado = max(ancho_img, alto_img)
    gw, gh = max(1, round(CUADRICULA * ancho_img / lado)), max(1, round(CUADRICULA * alto_img / lado))
    mascara = np.zeros((gh, gw), dtype=np.int32)
    margen = MARGEN_TEXTO * lado
    for x1, y1, x2, y2 in cajas:
        izq = max(0, int((x1 * ancho_img - margen) / ancho_img * gw))
        der = min(gw, int(np.ceil((x2 * ancho_img + margen) / ancho_img * gw)))
        arr = max(0, int((y1 * alto_img - margen) / alto_img * gh))
        aba = min(gh, int(np.ceil((y2 * alto_img + margen) / alto_img * gh)))
        if der > izq and aba > arr:
            mascara[arr:aba, izq:der] = 1
    # Imagen integral: la suma de texto de cualquier rectángulo en tiempo constante.
    integral = np.zeros((gh + 1, gw + 1), dtype=np.int64)
    integral[1:, 1:] = mascara.cumsum(0).cumsum(1)

    def texto_en(c0: int, f0: int, c1: int, f1: int) -> int:
        return int(integral[f1, c1] - integral[f0, c1] - integral[f1, c0] + integral[f0, c0])

    escala = 1.0
    while escala >= escala_min - 1e-9:
        # Ventana de ese ancho (fracción del ancho de la imagen) y la proporción pedida, medida en píxeles reales.
        v_ancho_px = escala * ancho_img
        v_alto_px = v_ancho_px / proporcion
        if v_alto_px <= alto_img:
            vc = max(1, round(v_ancho_px / ancho_img * gw))
            vf = max(1, round(v_alto_px / alto_img * gh))
            mejor: tuple[float, int, int] | None = None  # (solape, fila, columna)
            for f0 in range(0, gh - vf + 1):
                for c0 in range(0, gw - vc + 1):
                    solape = texto_en(c0, f0, c0 + vc, f0 + vf) / (vc * vf)
                    if solape <= solape_max and (mejor is None or solape < mejor[0]):
                        mejor = (solape, f0, c0)
            if mejor is not None:
                solape, f0, c0 = mejor
                return Recorte(c0 / gw, f0 / gh, vc / gw, vf / gh, solape)
        escala -= PASO_ESCALA
    return None


def recortar_imagen(datos: bytes, recorte: Recorte, ancho_salida: int | None = None) -> bytes:
    """Recorta la imagen (cualquier formato que lea Pillow) y la devuelve como JPEG, a `ancho_salida` px si se pide."""
    from PIL import Image

    imagen = Image.open(io.BytesIO(datos)).convert("RGB")
    pieza = imagen.crop(recorte.en_pixeles(*imagen.size))
    if ancho_salida and pieza.width > ancho_salida:
        pieza = pieza.resize((ancho_salida, round(pieza.height * ancho_salida / pieza.width)))
    salida = io.BytesIO()
    pieza.save(salida, "JPEG", quality=85)
    return salida.getvalue()


def contraste_de(datos: bytes) -> float:
    """Desviación típica de los grises de la imagen (0 a 255): un fondo liso o casi negro da un valor bajo."""
    import numpy as np
    from PIL import Image

    gris = np.asarray(Image.open(io.BytesIO(datos)).convert("L"), dtype=float)
    return float(gris.std())


def tiene_contenido(datos: bytes, minimo: float = CONTRASTE_MIN) -> bool:
    """False si el recorte es casi un fondo liso y no sirve como foto."""
    return contraste_de(datos) >= minimo
