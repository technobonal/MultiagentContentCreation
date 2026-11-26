"""Las fotos de la fuente en el run real: opcionales, una por hueco, con la licencia bloqueada y sin tumbar nunca el run."""
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


def foto(pagina):
    return FotoPreparada(JPEG + bytes([pagina]), "image/jpeg", pagina, f"Imagen de la página {pagina} de la fuente")


def hueco(nombre):
    return {"nombre": "{{" + nombre + "}}", "tipo": "imagen", "origen_valor": "usuario", "obligatorio": False,
            "hueco": {"ancho": 920, "alto": 300}}


def resolucion_con_huecos(slides_con_hueco=((1, "imagen_portada"), (2, "imagen_producto"), (5, "imagen_cierre"))):
    r = resolucion("auto")
    r.ficha = copy.deepcopy(r.ficha)
    for numero, nombre in slides_con_hueco:
        r.ficha["slides"][numero - 1]["campos"].append(hueco(nombre))
    return r


def correr_con_fotos(preparar_fotos, huecos=None):
    llamadas = []

    async def preparar(fuente_, huecos_):
        llamadas.append(huecos_)
        return await preparar_fotos(fuente_, huecos_)

    agentes = dataclasses.replace(fabricar_agentes()[0], preparar_fotos=preparar)
    res = resolucion_con_huecos() if huecos is None else resolucion_con_huecos(huecos)

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, res, "real")
        await ejecutar_run_real(ejecucion, fuente(), "cliente", KIT, agentes, esperar_aprobacion=False)
        return ejecucion

    return asyncio.run(principal()), llamadas


async def da_fotos(_, huecos):
    return {h.campo: foto(i + 1) for i, h in enumerate(huecos)}


@pytest.fixture
def licencia(monkeypatch):
    monkeypatch.setattr(config, "FOTOS_LICENCIA", "Uso autorizado por el titular")


def test_con_licencia_coloca_una_foto_por_hueco_en_orden_de_slide_y_las_guarda_en_el_run(licencia):
    ej, llamadas = correr_con_fotos(da_fotos)
    eventos = de_tipo(ej, "colocar_imagen")
    assert [(e["slide"], e["payload"]["campo"], e["payload"]["referencia"]) for e in eventos] == [
        (1, "imagen_portada", "foto-1"), (2, "imagen_producto", "foto-2"), (5, "imagen_cierre", "foto-5")]
    assert {e["payload"]["licencia"] for e in eventos} == {"Uso autorizado por el titular"}
    assert len({e["payload"]["texto_alternativo"] for e in eventos}) == 3  # fotos distintas
    assert ej.obtener_imagen("foto-5")[0] == JPEG + bytes([3]) and len(llamadas) == 1
    assert [h.campo for h in llamadas[0]] == ["imagen_portada", "imagen_producto", "imagen_cierre"]
    # Todas van después del arte del carrusel y antes de pedir la aprobación.
    t = tipos(ej)
    ultimo_texto = max(i for i, x in enumerate(t) if x == "escribir_texto")
    assert min(i for i, x in enumerate(t) if x == "colocar_imagen") > ultimo_texto
    assert max(i for i, x in enumerate(t) if x == "colocar_imagen") < t.index("aprobacion_solicitada")
    assert ej.estado == EstadoRun.TERMINADA


def test_un_hueco_sin_foto_queda_vacio_y_los_demas_se_colocan(licencia):
    async def solo_dos(_, huecos):
        return {"imagen_portada": foto(1), "imagen_cierre": foto(2)}

    ej, _ = correr_con_fotos(solo_dos)
    assert [e["slide"] for e in de_tipo(ej, "colocar_imagen")] == [1, 5]


def test_sin_licencia_no_se_hace_ni_el_trabajo_de_recortar(monkeypatch):
    monkeypatch.setattr(config, "FOTOS_LICENCIA", "")
    ej, llamadas = correr_con_fotos(da_fotos)
    assert de_tipo(ej, "colocar_imagen") == [] and llamadas == [] and ej.estado == EstadoRun.TERMINADA


def test_si_la_plantilla_no_tiene_huecos_de_imagen_no_se_coloca(licencia):
    ej, llamadas = correr_con_fotos(da_fotos, huecos=())
    assert de_tipo(ej, "colocar_imagen") == [] and llamadas == []


def test_sin_fotos_que_sirvan_el_run_sale_solo_con_texto(licencia):
    async def ninguna(_, huecos):
        return {}

    ej, _ = correr_con_fotos(ninguna)
    assert de_tipo(ej, "colocar_imagen") == [] and ej.estado == EstadoRun.TERMINADA


def test_una_falla_al_preparar_las_fotos_no_tumba_el_run(licencia):
    async def falla(_, huecos):
        raise RuntimeError("OCR roto")

    ej, _ = correr_con_fotos(falla)
    assert de_tipo(ej, "colocar_imagen") == [] and de_tipo(ej, "run_finalizada") and ej.estado == EstadoRun.TERMINADA


def test_una_imagen_que_el_run_no_acepta_no_impide_las_demas(licencia):
    async def una_pesada(_, huecos):
        return {"imagen_portada": FotoPreparada(b"x" * (3 * 1024 * 1024), "image/jpeg", 1, "Pesada"), "imagen_producto": foto(2)}

    ej, _ = correr_con_fotos(una_pesada)
    assert [e["slide"] for e in de_tipo(ej, "colocar_imagen")] == [2] and ej.estado == EstadoRun.TERMINADA


@pytest.mark.parametrize("texto", ["x", "L" * 121])
def test_una_licencia_fuera_del_contrato_bloquea_las_fotos_en_vez_de_romper_el_evento(monkeypatch, texto):
    monkeypatch.setattr(config, "FOTOS_LICENCIA", texto)
    ej, llamadas = correr_con_fotos(da_fotos)
    assert de_tipo(ej, "colocar_imagen") == [] and llamadas == [] and ej.estado == EstadoRun.TERMINADA


def test_hay_una_pausa_antes_de_cada_foto_y_otra_al_final_para_que_el_lienzo_las_anime_completas(licencia, monkeypatch):
    monkeypatch.setattr(config, "FOTOS_PAUSA_SEG", 1.5)
    pausas = []

    async def dormir_falso(seg):
        pausas.append(seg)

    async def preparar(_, huecos):
        return await da_fotos(_, huecos)

    agentes = dataclasses.replace(fabricar_agentes()[0], preparar_fotos=preparar, dormir=dormir_falso)

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, resolucion_con_huecos(), "real")
        await ejecutar_run_real(ejecucion, fuente(), "cliente", KIT, agentes, esperar_aprobacion=False)
        return ejecucion

    ej = asyncio.run(principal())
    # Una antes de cada foto y otra al final, para que la última escena no la corte el revisor.
    assert len(de_tipo(ej, "colocar_imagen")) == 3 and pausas == [1.5, 1.5, 1.5, 1.5]


def test_con_pausa_cero_no_se_duerme_nada(licencia):
    ej, _ = correr_con_fotos(da_fotos)  # el conftest deja la pausa en 0 y el dormir real fallaría con un tope bajo si se usara
    assert len(de_tipo(ej, "colocar_imagen")) == 3
