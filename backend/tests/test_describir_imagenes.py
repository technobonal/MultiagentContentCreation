"""Descripción de las imágenes de un PDF con un cliente de visión falso."""
import asyncio
import io

from PIL import Image

from app.agentes.cliente_vision import RespuestaVision, VisionError
from app.fuentes.describir_imagenes import describir_imagenes
from app.fuentes.extraer_imagenes import ImagenExtraida


def png(lado=300) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (lado, lado), (50, 60, 70)).save(b, "PNG")
    return b.getvalue()


def img(pagina, cubre=False, datos=None):
    return ImagenExtraida(pagina, 300, 300, "png", datos if datos is not None else png(), f"h{pagina}", cubre)


class Falso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    async def describir(self, imagen, instruccion, *, mime="image/jpeg", max_tokens=300):
        self.llamadas += 1
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return RespuestaVision(r, "m1:free")


def correr(imagenes, cliente, **kw):
    return asyncio.run(describir_imagenes(imagenes, cliente, **kw))


def test_describe_cada_imagen_en_orden():
    r = correr((img(1), img(2)), Falso(["Un edificio.", "Un mapa."]))
    assert [(d.pagina, d.descripcion, d.modelo, d.error) for d in r] == [
        (1, "Un edificio.", "m1:free", None), (2, "Un mapa.", "m1:free", None)]


def test_salta_las_paginas_completas_salvo_que_se_pidan():
    c = Falso(["Foto."])
    assert [d.pagina for d in correr((img(1, cubre=True), img(2)), c)] == [2]
    c2 = Falso(["a", "b"])
    assert len(correr((img(1, cubre=True), img(2)), c2, incluir_paginas_completas=True)) == 2


def test_respeta_el_maximo():
    c = Falso(["a", "b", "c"])
    assert len(correr((img(1), img(2), img(3)), c, maximo=2)) == 2 and c.llamadas == 2


def test_una_imagen_que_falla_no_aborta_a_las_demas():
    c = Falso([VisionError("sin_respuesta", "Ningún modelo respondió."), "Segunda."])
    r = correr((img(1), img(2)), c)
    assert (r[0].descripcion, r[0].error) == (None, "Ningún modelo respondió.")
    assert r[1].descripcion == "Segunda."


def test_sin_credenciales_corta_en_la_primera():
    c = Falso([VisionError("sin_api_key", "Falta OPENROUTER_API_KEY en el .env.")])
    r = correr((img(1), img(2)), c)
    assert len(r) == 1 and "OPENROUTER_API_KEY" in r[0].error and c.llamadas == 1


def test_una_imagen_ilegible_se_informa_y_sigue():
    r = correr((img(1, datos=b"no es una imagen"), img(2)), Falso(["Buena."]))
    assert r[0].descripcion is None and "No se pudo preparar" in r[0].error
    assert r[1].descripcion == "Buena."


def test_sin_imagenes_devuelve_vacio():
    assert correr((), Falso([])) == ()
