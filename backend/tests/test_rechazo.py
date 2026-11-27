"""Rechazar un run: qué decisión se acepta, qué eventos salen y qué queda guardado para aprender."""
import json

import pytest

from app import config
from app.runs.aprobacion import Decision, DecisionInvalida, Rechazo, validar_decision
from app.runs.registro import EstadoRun
from tests.test_orquestador_aprobacion import _correr_con_persona
from tests.test_orquestador_real import de_tipo, tipos

FICHA = {"slides": [{"numero": 1, "campos": []}, {"numero": 2, "campos": []}]}


@pytest.fixture(autouse=True)
def archivo(tmp_path, monkeypatch):
    """Ningún test escribe en el registro real."""
    ruta = tmp_path / "datos" / "rechazos.jsonl"
    monkeypatch.setattr(config, "RECHAZOS_ARCHIVO", ruta)
    return ruta


def _rechazar(**datos):
    return _correr_con_persona(lambda e: e.registrar_decision(Decision(rechazo=Rechazo(**datos))))


# ---------------------------- qué se acepta ----------------------------

def test_basta_con_el_motivo():
    decision = validar_decision({"rechazo": {"motivo": "  Cambia lo que dice la fuente.  "}}, [], FICHA)
    assert decision.rechazo == Rechazo("Cambia lo que dice la fuente.") and decision.ediciones == ()


def test_acepta_quien_fallo_donde_y_que_debia_hacer():
    cuerpo = {"rechazo": {"motivo": "m", "responsable": "revisor", "slide": 2, "esperado": "Juzgar la frase entera."}}
    assert validar_decision(cuerpo, [], FICHA).rechazo == Rechazo("m", "revisor", 2, "Juzgar la frase entera.")


@pytest.mark.parametrize("cuerpo, parte", [
    ({"rechazo": {}}, "escribir el motivo"),
    ({"rechazo": {"motivo": "   "}}, "escribir el motivo"),
    ({"rechazo": {"motivo": 5}}, "debe ser un texto"),
    ({"rechazo": {"motivo": "x" * 401}}, "supera 400"),
    ({"rechazo": {"motivo": "m", "responsable": "humano"}}, "responsable"),
    ({"rechazo": {"motivo": "m", "slide": 9}}, "no tiene el slide"),
    ({"rechazo": {"motivo": "m", "slide": True}}, "no tiene el slide"),
    ({"rechazo": {"motivo": "m", "otra": 1}}, "Clave desconocida"),
    ({"rechazo": "no me gusta"}, "debe ser un objeto"),
    ({"rechazo": None}, "debe ser un objeto"),
    ({"rechazo": {"motivo": "m"}, "ediciones": []}, "junto con un rechazo"),
    ({"rechazo": {"motivo": "m"}, "comentario": "ok"}, "junto con un rechazo"),
])
def test_un_rechazo_mal_formado_no_se_acepta(cuerpo, parte):
    with pytest.raises(DecisionInvalida) as e:
        validar_decision(cuerpo, [], FICHA)
    assert any(parte in motivo for motivo in e.value.motivos)


# ---------------------------- qué pasa con el run ----------------------------

def test_el_run_se_cierra_como_rechazado_sin_aprobada():
    ej = _rechazar(motivo="No dice lo de la fuente.")
    assert tipos(ej)[-3:] == ["aprobacion_solicitada", "rechazada", "run_finalizada"]
    assert de_tipo(ej, "aprobada") == [] and ej.estado == EstadoRun.TERMINADA
    rechazada = de_tipo(ej, "rechazada")[0]
    assert rechazada["agente"] == "humano" and "slide" not in rechazada
    assert rechazada["payload"] == {"decision": "rechazada", "motivo": "No dice lo de la fuente."}
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "rechazada"


def test_el_evento_lleva_el_slide_quien_fallo_y_lo_esperado():
    ej = _rechazar(motivo="m", responsable="revisor", slide=2, esperado="e")
    rechazada = de_tipo(ej, "rechazada")[0]
    assert rechazada["slide"] == 2
    assert rechazada["payload"] == {"decision": "rechazada", "motivo": "m", "responsable": "revisor", "esperado": "e"}


# ---------------------------- qué queda guardado ----------------------------

def test_cada_rechazo_agrega_una_linea_con_lo_necesario_para_aprender(archivo):
    _rechazar(motivo="primero")
    ej = _rechazar(motivo="segundo", responsable="redactor", slide=1)
    primero, segundo = [json.loads(linea) for linea in archivo.read_text(encoding="utf-8").splitlines()]
    assert (primero["motivo"], segundo["motivo"], segundo["responsable"]) == ("primero", "segundo", "redactor")
    assert segundo["run_id"] == ej.run_id and segundo["plantilla_id"] == ej.resolucion.plantilla_id
    assert segundo["estado_revision"] and "afirmaciones_totales" in segundo["sello"]
    # Con un slide señalado solo se guarda lo suyo; sin señalarlo, el carrusel entero.
    assert {t["slide"] for t in segundo["textos"]} == {1}
    assert {v["slide"] for v in segundo["verificaciones"]} <= {1} and segundo["verificaciones"]
    assert len({t["slide"] for t in primero["textos"]}) > 1


def test_aprobar_no_guarda_nada(archivo):
    _correr_con_persona(lambda e: e.registrar_decision(Decision()))
    assert not archivo.exists()


def test_si_el_disco_falla_el_rechazo_vale_igual_y_se_avisa(tmp_path, monkeypatch, caplog):
    tapon = tmp_path / "archivo"
    tapon.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "RECHAZOS_ARCHIVO", tapon / "rechazos.jsonl")  # su carpeta es un archivo
    ej = _rechazar(motivo="m")
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "rechazada"
    assert "No se pudo guardar el rechazo" in caplog.text
