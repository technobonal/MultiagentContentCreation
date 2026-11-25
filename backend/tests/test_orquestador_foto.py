"""La foto de la fuente en el run real: opcional, con la licencia bloqueada por defecto y sin tumbar nunca el run."""
import asyncio
import copy
import dataclasses

import pytest

from app import config
from app.agentes.foto_de_fuente import FotoPreparada
from app.runs.orquestador_real import ejecutar_run_real
from app.runs.registro import Ejecucion, EstadoRun
from tests.test_orquestador_real import ENTRADA, KIT, RUN_ID, de_tipo, fabricar_agentes, fuente, resolucion, tipos

JPEG = b"\xff\xd8\xff\xe0" + b"foto" * 30
FOTO = FotoPreparada(JPEG, "image/jpeg", 1, "Imagen de la página 1 de la fuente")
IMAGEN = {"nombre": "{{imagen_producto}}", "tipo": "imagen", "origen_valor": "usuario", "obligatorio": False}


def resolucion_con_hueco(con_hueco=True):
    r = resolucion("auto")
    r.ficha = copy.deepcopy(r.ficha)
    if con_hueco:
        r.ficha["slides"][1]["campos"].append(dict(IMAGEN))  # el hueco vive en el slide 2, como en la plantilla real
    return r


def correr_con_foto(preparar_foto, con_hueco=True):
    agentes = dataclasses.replace(fabricar_agentes()[0], preparar_foto=preparar_foto)
    llamadas = []

    async def preparar(fuente_):
        llamadas.append(fuente_)
        return await preparar_foto(fuente_)

    agentes = dataclasses.replace(agentes, preparar_foto=preparar)

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, resolucion_con_hueco(con_hueco), "real")
        await ejecutar_run_real(ejecucion, fuente(), "cliente", KIT, agentes, esperar_aprobacion=False)
        return ejecucion

    return asyncio.run(principal()), llamadas


async def da_foto(_):
    return FOTO


@pytest.fixture
def licencia(monkeypatch):
    monkeypatch.setattr(config, "FOTOS_LICENCIA", "Uso autorizado por el titular")


def test_con_licencia_coloca_la_foto_en_el_hueco_y_la_guarda_en_el_run(licencia):
    ej, llamadas = correr_con_foto(da_foto)
    [evento] = de_tipo(ej, "colocar_imagen")
    assert evento["agente"] == "director_arte" and evento["slide"] == 2
    assert evento["payload"] == {
        "campo": "imagen_producto", "referencia": "foto-2", "licencia": "Uso autorizado por el titular",
        "texto_alternativo": "Imagen de la página 1 de la fuente",
    }
    assert ej.obtener_imagen("foto-2") == (JPEG, "image/jpeg") and len(llamadas) == 1
    # Va después del arte del carrusel y antes de pedir la aprobación.
    t = tipos(ej)
    assert t.index("colocar_imagen") > max(i for i, x in enumerate(t) if x == "escribir_texto" and ej.eventos[i]["slide"] == 2)
    assert t.index("colocar_imagen") < t.index("aprobacion_solicitada") and ej.estado == EstadoRun.TERMINADA


def test_sin_licencia_no_se_hace_ni_el_trabajo_de_recortar(monkeypatch):
    monkeypatch.setattr(config, "FOTOS_LICENCIA", "")
    ej, llamadas = correr_con_foto(da_foto)
    assert de_tipo(ej, "colocar_imagen") == [] and llamadas == [] and ej.obtener_imagen("foto-2") is None
    assert ej.estado == EstadoRun.TERMINADA


def test_si_la_plantilla_no_tiene_hueco_de_imagen_no_se_coloca(licencia):
    ej, llamadas = correr_con_foto(da_foto, con_hueco=False)
    assert de_tipo(ej, "colocar_imagen") == [] and llamadas == []


def test_sin_foto_que_sirva_el_run_sale_solo_con_texto(licencia):
    async def ninguna(_):
        return None

    ej, _ = correr_con_foto(ninguna)
    assert de_tipo(ej, "colocar_imagen") == [] and ej.estado == EstadoRun.TERMINADA


def test_una_falla_al_preparar_la_foto_no_tumba_el_run(licencia):
    async def falla(_):
        raise RuntimeError("OCR roto")

    ej, _ = correr_con_foto(falla)
    assert de_tipo(ej, "colocar_imagen") == [] and de_tipo(ej, "run_finalizada") and ej.estado == EstadoRun.TERMINADA


def test_una_imagen_que_el_run_no_acepta_tampoco_tumba_el_run(licencia):
    async def pesada(_):
        return FotoPreparada(b"x" * (3 * 1024 * 1024), "image/jpeg", 1, "Foto")

    ej, _ = correr_con_foto(pesada)
    assert de_tipo(ej, "colocar_imagen") == [] and ej.estado == EstadoRun.TERMINADA


@pytest.mark.parametrize("texto", ["x", "L" * 121])
def test_una_licencia_fuera_del_contrato_bloquea_la_foto_en_vez_de_romper_el_evento(monkeypatch, texto):
    monkeypatch.setattr(config, "FOTOS_LICENCIA", texto)
    ej, llamadas = correr_con_foto(da_foto)
    assert de_tipo(ej, "colocar_imagen") == [] and llamadas == [] and ej.estado == EstadoRun.TERMINADA
