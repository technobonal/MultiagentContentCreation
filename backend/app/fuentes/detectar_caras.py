"""detectar_caras.py — Dónde hay caras en una imagen, con YuNet (OpenCV) corriendo en la máquina. Sin red.

Sirve para que el recorte de una foto no corte cabezas. Las cajas salen normalizadas (0 a 1). Las caras muy chicas
(alguien al fondo) se descartan: no condicionan el encuadre. Límite conocido: una cara muy inclinada (una persona
acostada) puede no detectarse; en ese caso el recorte se elige como si no la hubiera.
"""
from __future__ import annotations

import io
from pathlib import Path

MODELO = Path(__file__).resolve().parents[1] / "modelos" / "face_detection_yunet_2023mar.onnx"
PUNTAJE_MIN = 0.7
ALTO_MIN = 0.05  # fracción del alto de la imagen: por debajo es alguien al fondo
LADO_MAX_PX = 1280  # se detecta sobre una copia reducida: más rápido y suficiente
# Cuánto se agranda la caja de la cara para abarcar la cabeza, como fracción de su ancho o su alto.
MARGEN_ARRIBA, MARGEN_ABAJO, MARGEN_LADOS = 0.45, 0.2, 0.25

Caja = tuple[float, float, float, float]  # x1, y1, x2, y2


def filtrar_caras(crudas: list[tuple[float, float, float, float, float]], ancho: int, alto: int) -> list[Caja]:
    """De (x, y, w, h, puntaje) en píxeles a cajas normalizadas, sin las dudosas ni las diminutas; las más grandes primero."""
    cajas = []
    for x, y, w, h, puntaje in crudas:
        if puntaje < PUNTAJE_MIN or h / alto < ALTO_MIN:
            continue
        cajas.append((max(0.0, x / ancho), max(0.0, y / alto), min(1.0, (x + w) / ancho), min(1.0, (y + h) / alto)))
    return sorted(cajas, key=lambda c: -(c[2] - c[0]) * (c[3] - c[1]))


def caja_de_cabeza(cara: Caja) -> Caja:
    """La cara agrandada para abarcar la cabeza (pelo y mentón), sin salirse de la imagen."""
    x1, y1, x2, y2 = cara
    w, h = x2 - x1, y2 - y1
    return (max(0.0, x1 - w * MARGEN_LADOS), max(0.0, y1 - h * MARGEN_ARRIBA),
            min(1.0, x2 + w * MARGEN_LADOS), min(1.0, y2 + h * MARGEN_ABAJO))


def detectar_caras(datos: bytes) -> list[Caja]:
    """Caras de una imagen (cualquier formato que lea Pillow), normalizadas, de la más grande a la más chica."""
    import cv2
    import numpy as np
    from PIL import Image

    imagen = Image.open(io.BytesIO(datos)).convert("RGB")
    imagen.thumbnail((LADO_MAX_PX, LADO_MAX_PX))
    bgr = np.ascontiguousarray(np.asarray(imagen)[:, :, ::-1])
    # El modelo se pasa como bytes: la ruta puede tener tildes y OpenCV no siempre las abre en Windows.
    modelo = np.frombuffer(MODELO.read_bytes(), dtype=np.uint8)
    detector = cv2.FaceDetectorYN.create("onnx", modelo, np.empty(0, dtype=np.uint8), (imagen.width, imagen.height),
                                         PUNTAJE_MIN, 0.3, 50)
    _, halladas = detector.detect(bgr)
    crudas = [] if halladas is None else [(float(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[-1])) for c in halladas]
    return filtrar_caras(crudas, imagen.width, imagen.height)
