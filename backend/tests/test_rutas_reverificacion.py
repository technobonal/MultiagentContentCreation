"""POST /api/runs/{id}/reverificar: 202, 404, 409 (no espera / en curso / tope) y 422. Sin orquestador en marcha."""

from app import config
from tests.test_rutas import ajustes, cliente_http, correr, falsos, kit_de_prueba, registro  # noqa: F401
from tests.test_rutas_aprobacion import _run_esperando


def _post(ejecucion_id: str, **kw):
    async def llamada():
        async with cliente_http() as c:
            return await c.post(f"/api/runs/{ejecucion_id}/reverificar", **kw)
    return llamada()


_EDICION = {"slide": 1, "modo": "edicion", "ediciones": [{"slide": 1, "campo": "titulo", "texto": "Salud y bienestar"}]}


def test_edicion_valida_devuelve_202_y_registra_el_pedido(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        return ej, await _post(ej.run_id, json=_EDICION)

    ej, r = correr(escenario())
    assert r.status_code == 202 and r.json() == {"run_id": ej.run_id, "slide": 1, "modo": "edicion"}
    assert ej._pedido is not None and ej._pedido[0] == "reverificar"
    assert ej.decision_recibida is False  # no es una decisión final: el run sigue esperando


def test_modo_agente_valido_devuelve_202(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        return await _post(ej.run_id, json={"slide": 1, "modo": "agente"})

    assert correr(escenario()).json()["modo"] == "agente"


def test_run_inexistente_es_404(falsos, registro):
    assert correr(_post("run_noexiste", json=_EDICION)).status_code == 404


def test_run_que_no_espera_es_409(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro, esperando=False)
        return await _post(ej.run_id, json=_EDICION)

    r = correr(escenario())
    assert r.status_code == 409 and "no está esperando" in r.json()["motivos"][0]


def test_mientras_reverifica_es_409(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        ej.reverificando = True
        return await _post(ej.run_id, json=_EDICION)

    r = correr(escenario())
    assert r.status_code == 409 and "en curso" in r.json()["motivos"][0]


def test_al_agotar_el_tope_es_409(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        ej.rondas_reverif = config.REVERIF_MAX_RONDAS
        return await _post(ej.run_id, json=_EDICION)

    r = correr(escenario())
    assert r.status_code == 409 and str(config.REVERIF_MAX_RONDAS) in r.json()["motivos"][0]


def test_pedido_invalido_es_422_y_no_se_registra(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        r = await _post(ej.run_id, json={"slide": 1, "modo": "edicion", "ediciones": []})  # sin cambios
        return ej, r

    ej, r = correr(escenario())
    assert r.status_code == 422 and ej._pedido is None and ej.esperando_decision


def test_cuerpo_que_no_es_json_es_422(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        return await _post(ej.run_id, content=b"x", headers={"Content-Type": "application/json"})

    assert correr(escenario()).status_code == 422
