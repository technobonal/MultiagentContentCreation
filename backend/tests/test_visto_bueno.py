"""Sin visto bueno no hay aprobación normal: el bloqueo en el endpoint, el estado final y lo que queda guardado."""
import json

import pytest

from app import config
from app.runs.aprobacion import Decision, DecisionInvalida, Edicion, validar_decision
from app.runs.semaforo import informe
from tests.test_aprobacion import EVENTOS, FICHA
from tests.test_orquestador_aprobacion import _correr_con_persona
from tests.test_orquestador_real import de_tipo
from tests.test_rutas import ajustes, cliente_http, correr, falsos, kit_de_prueba, registro  # noqa: F401
from tests.test_rutas_aprobacion import _post, _run_esperando

EDICION = Edicion(1, "titulo", "titulo 1", "De la persona")
SIN_VEREDICTOS = [e for e in EVENTOS if e["tipo"] != "verificacion_fidelidad"]


@pytest.fixture(autouse=True)
def archivo(tmp_path, monkeypatch):
    ruta = tmp_path / "rechazos.jsonl"
    monkeypatch.setattr(config, "RECHAZOS_ARCHIVO", ruta)
    return ruta


# ---------------------------- qué decisión se acepta ----------------------------

def test_en_rojo_no_se_puede_aprobar_sin_excepcion_y_dice_que_slides():
    with pytest.raises(DecisionInvalida) as e:
        validar_decision({"comentario": "está bien"}, SIN_VEREDICTOS, FICHA)
    assert "No hay visto bueno" in e.value.motivos[0] and "1, 2" in e.value.motivos[0]


@pytest.mark.parametrize("excepcion", ["", "   ", None, 5])
def test_una_excepcion_vacia_o_que_no_es_texto_no_abre_la_puerta(excepcion):
    with pytest.raises(DecisionInvalida):
        validar_decision({"excepcion": excepcion}, SIN_VEREDICTOS, FICHA)


def test_en_rojo_la_excepcion_con_motivo_se_acepta():
    assert validar_decision({"excepcion": " Lo comprobé. "}, SIN_VEREDICTOS, FICHA).excepcion == "Lo comprobé."


def test_en_verde_una_excepcion_sobra():
    with pytest.raises(DecisionInvalida, match="no hace falta"):
        validar_decision({"excepcion": "porque sí"}, EVENTOS, FICHA)


# ---------------------------- cómo termina el run ----------------------------

def test_en_verde_se_aprueba_con_el_estado_de_la_revision_y_sin_registro(archivo):
    ej = _correr_con_persona(lambda e: e.registrar_decision(Decision()))
    assert informe(ej.eventos)["visto_bueno"]
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "aprobada"
    assert not archivo.exists()


def test_con_excepcion_queda_marcado_y_guardado_para_aprender(archivo):
    ej = _correr_con_persona(lambda e: e.registrar_decision(Decision((EDICION,), excepcion="Lo comprobé.")))
    assert de_tipo(ej, "aprobada")[0]["payload"] == {
        "decision": "aprobada", "excepcion": {"motivo": "Lo comprobé.", "slides_en_rojo": [1]},
    }
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "aprobada_sin_visto_bueno"
    (linea,) = archivo.read_text(encoding="utf-8").splitlines()
    guardado = json.loads(linea)
    assert (guardado["tipo"], guardado["motivo"]) == ("excepcion", "Lo comprobé.")
    assert guardado["semaforo"]["slides"][0]["color"] == "rojo"


def test_si_una_decision_en_rojo_se_saltara_el_endpoint_no_sale_como_aprobada():
    ej = _correr_con_persona(lambda e: e.registrar_decision(Decision((EDICION,))))
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "requiere_humano"


# ---------------------------- endpoints ----------------------------

def test_el_endpoint_bloquea_en_rojo_y_el_run_sigue_esperando(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        await ej.emitir("director_arte", "escribir_texto", {"campo": "titulo", "texto": "Texto sin revisar"}, slide=1)
        r = await _post(ej.run_id, json={})
        return ej, r

    ej, r = correr(escenario())
    assert r.status_code == 422 and "No hay visto bueno" in r.json()["motivos"][0]
    assert ej.esperando_decision and ej._decision is None


def test_el_informe_es_el_mismo_semaforo_y_un_run_inexistente_es_404(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        async with cliente_http() as c:
            return ej, await c.get(f"/api/runs/{ej.run_id}/informe"), await c.get("/api/runs/run_noexiste/informe")

    ej, bien, mal = correr(escenario())
    assert bien.status_code == 200 and bien.json() == informe(ej.eventos) and bien.json()["visto_bueno"]
    assert mal.status_code == 404
