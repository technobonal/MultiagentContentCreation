"""El evento colocar_imagen cumple (y rompe) el contrato, validado con el validador real del backend."""
import copy

import pytest

from app.events.validador import comprobar_evento

VALIDO = {
    "version": "0.1", "run_id": "run_abc12345", "seq": 7, "timestamp": "2026-11-25T17:00:00.000-03:00",
    "origen": "real", "agente": "director_arte", "tipo": "colocar_imagen", "slide": 2,
    "payload": {
        "campo": "imagen_producto", "referencia": "foto-2", "licencia": "Uso autorizado por el titular",
        "texto_alternativo": "Edificio residencial al atardecer",
    },
}


def con(**cambios):
    e = copy.deepcopy(VALIDO)
    for clave, valor in cambios.items():
        if clave.startswith("payload_"):
            e["payload"][clave.removeprefix("payload_")] = valor
        else:
            e[clave] = valor
    return e


def test_un_colocar_imagen_valido_se_acepta():
    assert comprobar_evento(VALIDO) == []


@pytest.mark.parametrize("campo", ["campo", "referencia", "licencia", "texto_alternativo"])
def test_cada_campo_del_payload_es_obligatorio(campo):
    e = copy.deepcopy(VALIDO)
    del e["payload"][campo]
    assert comprobar_evento(e) != []


@pytest.mark.parametrize("referencia", ["../secreto", "Con Mayusculas", "a/b", "", "x" * 41, "http://externo/x.jpg"])
def test_una_referencia_que_no_es_segura_en_una_url_se_rechaza(referencia):
    assert comprobar_evento(con(payload_referencia=referencia)) != []


def test_solo_el_director_de_arte_lo_emite():
    assert comprobar_evento(con(agente="revisor")) != []


def test_no_admite_campos_de_mas_ni_una_url_externa():
    assert comprobar_evento(con(payload_url="http://externo.example/x.jpg")) != []


def test_el_slide_es_obligatorio():
    e = copy.deepcopy(VALIDO)
    del e["slide"]
    assert comprobar_evento(e) != []


def test_licencia_y_texto_alternativo_tienen_limites():
    assert comprobar_evento(con(payload_licencia="x")) != []  # menos de 2 caracteres
    assert comprobar_evento(con(payload_texto_alternativo="")) != []
    assert comprobar_evento(con(payload_texto_alternativo="a" * 201)) != []
