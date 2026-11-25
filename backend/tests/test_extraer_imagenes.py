"""Extracción de imágenes embebidas de un PDF."""
import pymupdf
import pytest

from app.fuentes.extraer_imagenes import extraer_imagenes


def pixmap(lado: int, valor: int) -> "pymupdf.Pixmap":
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, lado, lado))
    pix.clear_with(valor)
    return pix


def pdf(paginas: list[list[tuple["pymupdf.Pixmap", "pymupdf.Rect | None"]]]) -> bytes:
    """Un PDF con las imágenes dadas por página; rect None = la página entera."""
    doc = pymupdf.open()
    for imagenes in paginas:
        pagina = doc.new_page()
        for pix, rect in imagenes:
            pagina.insert_image(rect or pagina.rect, pixmap=pix, keep_proportion=False)
    return doc.tobytes()


FOTO = pymupdf.Rect(50, 50, 300, 300)


def test_extrae_una_foto_con_su_pagina_y_tamano():
    [img] = extraer_imagenes(pdf([[], [(pixmap(300, 120), FOTO)]]))
    assert (img.pagina, img.ancho, img.alto) == (2, 300, 300)
    assert img.cubre_pagina is False
    assert len(img.sha256) == 64 and img.datos


def test_una_imagen_repetida_en_varias_paginas_sale_una_vez():
    logo = pixmap(300, 80)
    imagenes = extraer_imagenes(pdf([[(logo, FOTO)], [(logo, FOTO)], [(logo, FOTO)]]))
    assert len(imagenes) == 1 and imagenes[0].pagina == 1


def test_descarta_los_iconos_chicos():
    assert extraer_imagenes(pdf([[(pixmap(64, 10), FOTO)]])) == ()
    assert len(extraer_imagenes(pdf([[(pixmap(64, 10), FOTO)]]), lado_min=32)) == 1


def test_una_imagen_que_ocupa_la_pagina_entera_se_marca():
    [img] = extraer_imagenes(pdf([[(pixmap(400, 200), None)]]))
    assert img.cubre_pagina is True


def test_pdf_sin_imagenes_devuelve_vacio():
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "solo texto")
    assert extraer_imagenes(doc.tobytes()) == ()


def test_archivo_que_no_es_pdf_lanza_valueerror():
    with pytest.raises(ValueError):
        extraer_imagenes(b"no soy un pdf")
