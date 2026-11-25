"""Recorte sin texto: geometría pura, sin OCR ni modelos."""
import io

from PIL import Image

from app.fuentes.recortar_foto import mejor_recorte, recortar_imagen

PROPORCION = 920 / 422  # el hueco de foto de la plantilla


def sin_texto_dentro(recorte, cajas):
    """Ninguna caja de texto se cruza con el recorte."""
    for x1, y1, x2, y2 in cajas:
        cruza_x = x1 < recorte.x + recorte.ancho and x2 > recorte.x
        cruza_y = y1 < recorte.y + recorte.alto and y2 > recorte.y
        assert not (cruza_x and cruza_y)


def test_imagen_sin_texto_da_la_ventana_mas_grande():
    r = mejor_recorte(1920, 1080, [], PROPORCION)
    assert r.solape == 0 and r.ancho == 1.0  # ocupa todo el ancho: la proporción cabe en el alto
    assert abs(r.ancho * 1920 / (r.alto * 1080) - PROPORCION) < 0.15


def test_evita_el_texto_de_la_parte_de_arriba():
    cajas = [(0.05, 0.02, 0.95, 0.30)]  # un título grande arriba
    r = mejor_recorte(1920, 1080, cajas, PROPORCION)
    assert r is not None and r.y >= 0.30 - 0.02
    sin_texto_dentro(r, cajas)


def test_si_el_texto_ocupa_todo_no_hay_recorte():
    cajas = [(0.0, i / 10, 1.0, i / 10 + 0.08) for i in range(10)]  # renglones por toda la imagen
    assert mejor_recorte(1920, 1080, cajas, PROPORCION) is None


def test_busca_una_ventana_mas_chica_cuando_la_grande_no_cabe():
    cajas = [(0.45, 0.0, 0.55, 1.0)]  # una columna de texto al medio
    r = mejor_recorte(1920, 1080, cajas, PROPORCION)
    assert r is not None and r.ancho < 0.5
    sin_texto_dentro(r, cajas)


def test_un_poco_de_texto_dentro_de_la_tolerancia_se_acepta():
    r = mejor_recorte(1920, 1080, [(0.0, 0.0, 0.01, 0.01)], PROPORCION, solape_max=0.5)
    assert r is not None


def test_tamano_invalido_o_proporcion_invalida():
    assert mejor_recorte(0, 100, [], PROPORCION) is None
    assert mejor_recorte(100, 100, [], 0) is None


def test_recortar_imagen_respeta_la_proporcion_y_el_ancho_de_salida():
    original = io.BytesIO()
    Image.new("RGB", (1920, 1080), (200, 100, 50)).save(original, "PNG")
    r = mejor_recorte(1920, 1080, [], PROPORCION)
    datos = recortar_imagen(original.getvalue(), r, ancho_salida=920)
    salida = Image.open(io.BytesIO(datos))
    assert salida.format == "JPEG" and salida.width == 920
    assert abs(salida.width / salida.height - PROPORCION) < 0.1


def png_de(imagen):
    b = io.BytesIO()
    imagen.save(b, "PNG")
    return b.getvalue()


def test_un_fondo_liso_no_tiene_contenido_y_una_foto_si():
    from app.fuentes.recortar_foto import contraste_de, tiene_contenido

    liso = png_de(Image.new("RGB", (200, 100), (12, 20, 35)))
    ruido = Image.effect_noise((200, 100), 60).convert("RGB")
    assert contraste_de(liso) == 0 and not tiene_contenido(liso)
    assert tiene_contenido(png_de(ruido))


def test_por_defecto_no_tolera_texto_dentro_del_recorte():
    cajas = [(0.5, 0.5, 0.52, 0.52)]  # una letra suelta
    r = mejor_recorte(1920, 1080, cajas, PROPORCION)
    assert r is not None and r.solape == 0
    sin_texto_dentro(r, cajas)
