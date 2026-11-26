"""Detección de caras: el filtrado y la caja de cabeza (puros), y que el modelo local es el esperado y carga."""
import hashlib
import io

import pytest
from PIL import Image

from app.fuentes.detectar_caras import MODELO, caja_de_cabeza, detectar_caras, filtrar_caras

SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"


def test_el_modelo_es_el_que_se_aprobo_y_trae_su_licencia():
    assert hashlib.sha256(MODELO.read_bytes()).hexdigest() == SHA256
    assert "MIT License" in (MODELO.parent / "LICENSE-yunet").read_text(encoding="utf-8")


def test_filtra_las_dudosas_y_las_diminutas_y_ordena_por_tamano():
    crudas = [(100, 100, 50, 80, 0.95), (500, 100, 100, 200, 0.9), (10, 10, 8, 12, 0.99), (300, 300, 90, 120, 0.4)]
    cajas = filtrar_caras(crudas, 1000, 1000)
    assert cajas == [(0.5, 0.1, 0.6, 0.3), (0.1, 0.1, 0.15, 0.18)]


def test_las_cajas_no_se_salen_de_la_imagen():
    [caja] = filtrar_caras([(-20, -10, 200, 300, 0.9)], 1000, 1000)
    assert caja[0] == 0.0 and caja[1] == 0.0
    assert caja_de_cabeza((0.0, 0.0, 1.0, 1.0)) == (0.0, 0.0, 1.0, 1.0)


def test_la_caja_de_cabeza_agranda_sobre_todo_hacia_arriba():
    x1, y1, x2, y2 = caja_de_cabeza((0.4, 0.4, 0.5, 0.6))
    assert (x1, y1, x2, y2) == pytest.approx((0.375, 0.31, 0.525, 0.64))


def test_una_imagen_sin_caras_no_detecta_nada():
    salida = io.BytesIO()
    Image.effect_noise((640, 480), 60).convert("RGB").save(salida, "JPEG")
    assert detectar_caras(salida.getvalue()) == []
