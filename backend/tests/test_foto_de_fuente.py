"""Elegir fotos distintas de un PDF para los huecos de la plantilla: PDFs en memoria y un OCR falso."""
import asyncio
import io
import re
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from PIL import Image

from app.agentes.foto_de_fuente import TAMANO_HUECO, Hueco, fotos_de_pdf, huecos_de_ficha, preparar_fotos

RAIZ = Path(__file__).resolve().parents[2]
H_PRODUCTO = Hueco(2, "imagen_producto", 920, 422)
H_CIERRE = Hueco(5, "imagen_cierre", 920, 300)
H_PORTADA = Hueco(1, "imagen_portada", 920, 280)


def jpeg(ancho=800, alto=500, ruido=True, sal=0) -> bytes:
    """Imagen con detalle (ruido) o lisa; `sal` cambia el contenido para que dos imágenes no sean idénticas."""
    im = Image.effect_noise((ancho, alto), 70 + sal).convert("RGB") if ruido else Image.new("RGB", (ancho, alto), (10, 20, 30))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


def pdf(paginas: list[tuple[bytes, "pymupdf.Rect | None"]]) -> bytes:
    """Un PDF con una imagen por página; rect None = la página entera."""
    doc = pymupdf.open()
    for datos, rect in paginas:
        pagina = doc.new_page()
        pagina.insert_image(pagina.rect, stream=datos, keep_proportion=False) if rect is None else pagina.insert_image(rect, stream=datos, keep_proportion=False)
    return doc.tobytes()


def sin_texto(imagen):
    return []


RECT = pymupdf.Rect(50, 50, 450, 300)


def test_una_foto_embebida_se_recorta_a_la_proporcion_de_su_hueco():
    fotos = fotos_de_pdf(pdf([(jpeg(), RECT)]), [H_PRODUCTO], sin_texto)
    foto = fotos["imagen_producto"]
    im = Image.open(io.BytesIO(foto.datos))
    assert foto.pagina == 1 and foto.mime == "image/jpeg" and im.width <= 920
    assert abs(im.width / im.height - H_PRODUCTO.proporcion) < 0.1 and "página 1" in foto.texto_alternativo


def test_cada_hueco_recibe_una_foto_distinta_y_los_huecos_sobrantes_quedan_vacios():
    datos = pdf([(jpeg(sal=i * 5), RECT) for i in range(2)])  # dos imágenes distintas
    fotos = fotos_de_pdf(datos, [H_PORTADA, H_PRODUCTO, H_CIERRE], sin_texto)
    assert len(fotos) == 2  # tres huecos, dos imágenes: una queda vacía
    assert {f.pagina for f in fotos.values()} == {1, 2}  # nunca la misma página dos veces


def test_los_huecos_mas_grandes_eligen_primero_y_se_llevan_la_foto_mas_grande():
    chica, grande = jpeg(500, 300), jpeg(1600, 900, sal=9)
    datos = pdf([(chica, RECT), (grande, pymupdf.Rect(20, 20, 560, 330))])
    fotos = fotos_de_pdf(datos, [H_CIERRE, H_PRODUCTO], sin_texto)
    assert fotos["imagen_producto"].pagina == 2  # el hueco de 920×422 se queda con la imagen grande
    assert fotos["imagen_cierre"].pagina == 1


def test_un_fondo_liso_no_sirve_y_un_pdf_sin_imagenes_no_da_fotos():
    assert fotos_de_pdf(pdf([(jpeg(ruido=False), None)]), [H_PRODUCTO], sin_texto) == {}
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "solo texto")
    assert fotos_de_pdf(doc.tobytes(), [H_PRODUCTO], sin_texto) == {}
    assert fotos_de_pdf(pdf([(jpeg(), RECT)]), [], sin_texto) == {}


def test_en_una_pagina_escaneada_el_recorte_evita_el_texto_que_lee_el_ocr():
    pedidos = []

    def motor(imagen):
        pedidos.append(imagen.shape)
        h, w = imagen.shape[:2]
        return [([(0, 0), (w * 0.5, 0), (w * 0.5, h), (0, h)], "texto")]  # la mitad izquierda es texto

    fotos = fotos_de_pdf(pdf([(jpeg(1600, 1000), None)]), [H_PRODUCTO], motor)
    assert pedidos and "imagen_producto" in fotos


def test_solo_se_miran_las_primeras_paginas():
    datos = pdf([(jpeg(sal=i * 5), RECT) for i in range(3)])
    fotos = fotos_de_pdf(datos, [H_PORTADA, H_PRODUCTO, H_CIERRE], sin_texto, max_paginas=1)
    assert len(fotos) == 1 and next(iter(fotos.values())).pagina == 1


def test_preparar_fotos_ignora_fuentes_que_no_son_pdf_o_no_existen(tmp_path):
    assert asyncio.run(preparar_fotos(SimpleNamespace(referencia="guia.md"), [H_PRODUCTO], carpeta=tmp_path)) == {}
    assert asyncio.run(preparar_fotos(SimpleNamespace(referencia="falta.pdf"), [H_PRODUCTO], carpeta=tmp_path)) == {}


def test_preparar_fotos_lee_el_pdf_de_la_carpeta(tmp_path):
    (tmp_path / "folleto.pdf").write_bytes(pdf([(jpeg(), RECT)]))
    fotos = asyncio.run(preparar_fotos(SimpleNamespace(referencia="folleto.pdf"), [H_PRODUCTO], carpeta=tmp_path, motor_ocr=sin_texto))
    assert fotos["imagen_producto"].pagina == 1


def test_huecos_de_ficha_toma_los_campos_de_imagen_con_tamano_conocido_en_orden_de_slide():
    ficha = {"slides": [
        {"numero": 1, "campos": [{"nombre": "{{titulo}}", "tipo": "texto"}, {"nombre": "{{imagen_portada}}", "tipo": "imagen"}]},
        {"numero": 2, "campos": [{"nombre": "{{imagen_desconocida}}", "tipo": "imagen"}, {"nombre": "{{imagen_producto}}", "tipo": "imagen"}]},
    ]}
    assert huecos_de_ficha(ficha) == [Hueco(1, "imagen_portada", 920, 280), Hueco(2, "imagen_producto", 920, 422)]


def test_la_tabla_de_tamanos_coincide_con_la_plantilla_real():
    """Si alguien cambia un hueco del SVG sin tocar la tabla, las fotos saldrían con otra proporción."""
    svg = (RAIZ / "templates" / "catalog" / "ig_carrusel_pasos_oscuro_6slides" / "template.svg").read_text(encoding="utf-8")
    encontrados = {}
    for m in re.finditer(r'<g id="[^"]+" class="hueco-imagen" data-campo="\{\{(\w+)\}\}"[^>]*>.*?<image[^>]*width="(\d+)" height="(\d+)"', svg, re.S):
        encontrados[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    assert encontrados == TAMANO_HUECO
