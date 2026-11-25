"""Elegir la foto de un PDF para el hueco de la plantilla: PDFs armados en memoria y un OCR falso."""
import asyncio
import io
from types import SimpleNamespace

import pymupdf
from PIL import Image

from app.agentes.foto_de_fuente import FOTO_ANCHO, PROPORCION, foto_de_pdf, preparar_foto


def jpeg(ancho=800, alto=500, ruido=True) -> bytes:
    """Imagen con detalle (ruido) o lisa, para que el filtro de contenido las distinga."""
    im = Image.effect_noise((ancho, alto), 70).convert("RGB") if ruido else Image.new("RGB", (ancho, alto), (10, 20, 30))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


def pdf(paginas: list[tuple[bytes, "pymupdf.Rect | None"]]) -> bytes:
    """Un PDF con una imagen por página; rect None = la página entera."""
    doc = pymupdf.open()
    for datos, rect in paginas:
        pagina = doc.new_page()
        pagina.insert_image(rect or pagina.rect, stream=datos, keep_proportion=False)
    return doc.tobytes()


def sin_texto(imagen):
    return []


def test_foto_embebida_en_un_pdf_normal_se_recorta_al_hueco():
    foto = foto_de_pdf(pdf([(jpeg(), pymupdf.Rect(50, 50, 400, 300))]), sin_texto)
    assert foto is not None and foto.pagina == 1 and foto.mime == "image/jpeg"
    im = Image.open(io.BytesIO(foto.datos))
    assert im.width <= FOTO_ANCHO and abs(im.width / im.height - PROPORCION) < 0.1
    assert "página 1" in foto.texto_alternativo


def test_pdf_sin_imagenes_no_da_foto():
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "solo texto")
    assert foto_de_pdf(doc.tobytes(), sin_texto) is None


def test_un_fondo_liso_no_sirve_como_foto():
    assert foto_de_pdf(pdf([(jpeg(ruido=False), None)]), sin_texto) is None


def test_en_una_pagina_escaneada_el_recorte_evita_el_texto_que_lee_el_ocr():
    # El OCR dice que la mitad izquierda de la página es texto: el recorte tiene que salir de la derecha.
    pedidos = []

    def motor(imagen):
        pedidos.append(imagen.shape)
        h, w = imagen.shape[:2]
        return [([(0, 0), (w * 0.5, 0), (w * 0.5, h), (0, h)], "texto")]

    foto = foto_de_pdf(pdf([(jpeg(1600, 1000), None)]), motor)
    assert pedidos and foto is not None
    assert Image.open(io.BytesIO(foto.datos)).width <= FOTO_ANCHO


def test_gana_la_imagen_con_el_recorte_mas_grande_y_se_ignoran_las_paginas_de_mas():
    chica, grande = jpeg(400, 300), jpeg(1600, 900)
    datos = pdf([(chica, pymupdf.Rect(50, 50, 300, 200)), (grande, pymupdf.Rect(20, 20, 560, 330)), (grande + b"", pymupdf.Rect(20, 20, 560, 330))])
    foto = foto_de_pdf(datos, sin_texto)
    assert foto is not None and foto.pagina == 2
    # Con el tope en una página solo se mira la primera.
    assert foto_de_pdf(datos, sin_texto, max_paginas=1).pagina == 1


def test_preparar_foto_ignora_fuentes_que_no_son_pdf_o_no_existen(tmp_path):
    assert asyncio.run(preparar_foto(SimpleNamespace(referencia="guia.md"), carpeta=tmp_path)) is None
    assert asyncio.run(preparar_foto(SimpleNamespace(referencia="falta.pdf"), carpeta=tmp_path)) is None


def test_preparar_foto_lee_el_pdf_de_la_carpeta(tmp_path):
    (tmp_path / "folleto.pdf").write_bytes(pdf([(jpeg(), pymupdf.Rect(50, 50, 400, 300))]))
    foto = asyncio.run(preparar_foto(SimpleNamespace(referencia="folleto.pdf"), carpeta=tmp_path, motor_ocr=sin_texto))
    assert foto is not None and foto.pagina == 1
