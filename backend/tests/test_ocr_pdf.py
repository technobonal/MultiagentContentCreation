"""OCR de PDF escaneados: orden de lectura y enganche en el cargador, con un motor falso (sin rapidocr)."""
import pymupdf
import pytest

from app import config
from app.fuentes.cargador_fuente import FuenteError, _texto_de_pdf
from app.fuentes.ocr_pdf import ordenar_en_filas


def caja(x, y, ancho=100, alto=20):
    return [(x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)]


def pdf_solo_imagen(paginas: int = 1) -> bytes:
    """PDF sin capa de texto: cada página es una imagen blanca."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
    pix.clear_with(255)
    for _ in range(paginas):
        pagina = doc.new_page()
        pagina.insert_image(pagina.rect, pixmap=pix)
    return doc.tobytes()


FRASE = "El Sprint dura un mes como máximo y el equipo tiene diez personas o menos. El Daily Scrum dura quince minutos."


def motor_falso(imagen):
    return [(caja(10, 10), FRASE)]


def test_ordenar_en_filas_une_por_altura_y_ordena_de_izquierda_a_derecha():
    lineas = [(caja(300, 12), "mundo"), (caja(10, 10), "hola"), (caja(10, 100), "segunda fila")]
    assert ordenar_en_filas(lineas) == ["hola mundo", "segunda fila"]


def test_ordenar_en_filas_ignora_textos_vacios_y_sin_lineas():
    assert ordenar_en_filas([]) == []
    assert ordenar_en_filas([(caja(0, 0), "   ")]) == []


def test_pdf_escaneado_se_lee_con_ocr():
    texto = _texto_de_pdf(pdf_solo_imagen(), "escaneado.pdf", motor_falso)
    assert texto == FRASE


def test_ocr_apagado_rechaza_el_pdf_escaneado(monkeypatch):
    monkeypatch.setattr(config, "PDF_OCR", False)
    with pytest.raises(FuenteError) as e:
        _texto_de_pdf(pdf_solo_imagen(), "escaneado.pdf", motor_falso)
    assert e.value.codigo == "pdf_sin_texto" and "apagado" in str(e.value)


def test_ocr_sin_texto_legible_rechaza_el_pdf():
    with pytest.raises(FuenteError) as e:
        _texto_de_pdf(pdf_solo_imagen(), "escaneado.pdf", lambda imagen: [])
    assert e.value.codigo == "pdf_sin_texto" and "no encontró" in str(e.value)


def test_pdf_escaneado_con_demasiadas_paginas_no_se_lee(monkeypatch):
    monkeypatch.setattr(config, "PDF_OCR_MAX_PAGINAS", 2)
    with pytest.raises(FuenteError) as e:
        _texto_de_pdf(pdf_solo_imagen(3), "escaneado.pdf", motor_falso)
    assert e.value.codigo == "pdf_demasiadas_paginas_ocr"


def test_un_pdf_con_texto_no_usa_el_ocr():
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 500, 300), FRASE * 3)
    llamadas = []
    texto = _texto_de_pdf(doc.tobytes(), "texto.pdf", lambda imagen: llamadas.append(1) or [])
    assert llamadas == [] and "Sprint" in texto
