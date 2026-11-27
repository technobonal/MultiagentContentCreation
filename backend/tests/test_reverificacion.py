"""Re-verificación a pedido (A5.1a): funciones puras, el canal de la Ejecucion y el lazo en el orquestador."""

import asyncio
from itertools import count

import pytest

from app.runs.aprobacion import DecisionInvalida, Edicion
from app.runs.registro import Ejecucion
from app.runs.reverificacion import Reverificacion, reconstruir_abiertos, validar_reverificacion
from tests.test_aprobacion import EVENTOS, FICHA

# ----------------------------- reconstruir_abiertos -----------------------------

_SEQ = count(1)


def _ev(tipo, slide, **payload):
    return {"seq": next(_SEQ), "tipo": tipo, "slide": slide, "payload": payload}


def test_reconstruir_abiertos_deja_solo_los_que_siguen_abiertos():
    eventos = [
        _ev("hallazgo_abierto", 1, hallazgo_id="h1", gravedad="mayor", dimension="fidelidad", evidencia="x"),
        _ev("hallazgo_abierto", 2, hallazgo_id="h2", gravedad="bloqueante", dimension="fidelidad", evidencia="y"),
        _ev("hallazgo_corregido", 1, hallazgo_id="h1", resultado="corregido"),
        _ev("hallazgo_corregido", 2, hallazgo_id="h2", resultado="persiste"),
    ]
    abiertos = reconstruir_abiertos(eventos)
    assert [h.hallazgo_id for h in abiertos] == ["h2"]  # h1 se cerró
    h2 = abiertos[0]
    assert h2.slide == 2 and h2.seq_abierto == 2 and h2.intentos == 2  # apertura + un «persiste»


# ----------------------------- validar_reverificacion -----------------------------

def _edicion_valida():
    # El título del slide 1 está dibujado como "Salud para todos" en EVENTOS.
    return {"slide": 1, "modo": "edicion", "ediciones": [{"slide": 1, "campo": "titulo", "texto": "Salud ya"}]}


def test_edicion_valida_devuelve_el_pedido_con_la_edicion():
    pedido = validar_reverificacion(_edicion_valida(), EVENTOS, FICHA)
    assert pedido.slide == 1 and pedido.modo == "edicion"
    assert pedido.ediciones == (Edicion(1, "titulo", "Salud para todos", "Salud ya"),)


def test_modo_agente_no_admite_ediciones_y_no_las_necesita():
    pedido = validar_reverificacion({"slide": 2, "modo": "agente"}, EVENTOS, FICHA)
    assert pedido == Reverificacion(2, "agente", ())
    with pytest.raises(DecisionInvalida, match="no se envían ediciones"):
        validar_reverificacion({"slide": 2, "modo": "agente", "ediciones": [{"slide": 2, "campo": "cta", "texto": "x"}]}, EVENTOS, FICHA)


@pytest.mark.parametrize("cuerpo, trozo", [
    ({"slide": 9, "modo": "edicion", "ediciones": []}, "slide"),
    ({"slide": 1, "modo": "otro"}, "modo"),
    ({"slide": 1, "modo": "edicion", "ediciones": []}, "No cambiaste"),
    ({"slide": 1, "modo": "edicion", "ediciones": [{"slide": 2, "campo": "cta", "texto": "Otro"}]}, "del slide 1"),
    ({"slide": 1, "modo": "edicion", "ediciones": [{"slide": 1, "campo": "titulo", "texto": "Salud para todos"}]}, "No cambiaste"),
])
def test_pedidos_invalidos_se_rechazan(cuerpo, trozo):
    with pytest.raises(DecisionInvalida) as e:
        validar_reverificacion(cuerpo, EVENTOS, FICHA)
    assert any(trozo in m for m in e.value.motivos)


# ----------------------------- el canal de la Ejecucion -----------------------------

def _ejecucion():
    from tests.test_registro import _ejecucion as crear
    return crear()


def test_el_canal_rechaza_pedidos_cuando_no_corresponde():
    async def escenario():
        e = _ejecucion()
        sin_abrir = e.registrar_reverificacion(Reverificacion(1, "edicion"))  # no se abrió la espera
        e.abrir_decision()
        abierto = e.registrar_reverificacion(Reverificacion(1, "edicion"))
        otro = e.registrar_reverificacion(Reverificacion(1, "edicion"))  # ya hay uno sin consumir
        return sin_abrir, abierto, otro

    assert asyncio.run(escenario()) == (False, True, False)


def test_una_decision_final_cierra_la_puerta_a_mas_reverificaciones():
    async def escenario():
        e = _ejecucion()
        e.abrir_decision()
        clase, _ = (("decidir", "d") if e.registrar_decision("d") else (None, None), await e.esperar_pedido(1))[1]
        return clase, e.registrar_reverificacion(Reverificacion(1, "edicion"))

    clase, acepta = asyncio.run(escenario())
    assert clase == "decidir" and acepta is False


def test_mientras_reverifica_no_entra_otro_pedido():
    async def escenario():
        e = _ejecucion()
        e.abrir_decision()
        e.reverificando = True
        return e.registrar_reverificacion(Reverificacion(1, "edicion")), e.registrar_decision("d")

    assert asyncio.run(escenario()) == (False, False)


# ----------------------------- el lazo en el orquestador -----------------------------

def _correr_con_reverificacion(actuar, **kw):
    """Corre un run que espera aprobación; `actuar(ejecucion)` (corutina) obra cuando ya pidió la aprobación."""
    from app.runs.orquestador_real import ejecutar_run_real
    from app.runs.registro import EstadoRun  # noqa: F401
    from tests.test_orquestador_real import ENTRADA, KIT, RUN_ID, fabricar_agentes, fuente, resolucion

    agentes = kw.get("agentes") or fabricar_agentes()[0]

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, resolucion("auto"), "real")
        tarea = asyncio.create_task(ejecutar_run_real(
            ejecucion, fuente(), "cliente", KIT, agentes, None,
            esperar_aprobacion=True, aprobacion_timeout_seg=5.0,
        ))
        while not any(e["tipo"] == "aprobacion_solicitada" for e in ejecucion.eventos):
            await asyncio.sleep(0.001)
        await actuar(ejecucion)
        await tarea
        return ejecucion

    return asyncio.run(principal())


async def _esperar(cond, limite=2.0):
    """Espera a que `cond()` sea verdadero (o falla por tiempo)."""
    for _ in range(int(limite / 0.005)):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("no se cumplió la condición a tiempo")


def test_una_reverificacion_de_edicion_re_emite_la_verificacion_y_el_run_sigue_esperando():
    from app.runs.aprobacion import Decision
    from tests.test_orquestador_real import de_tipo

    async def actuar(ej):
        antes = len(de_tipo(ej, "verificacion_fidelidad"))
        # El título del slide 1 que escribió el redactor falso es "titulo 1".
        pedido = Reverificacion(1, "edicion", (Edicion(1, "titulo", "titulo 1", "Editado a mano"),))
        assert ej.registrar_reverificacion(pedido) is True
        await _esperar(lambda: ej.rondas_reverif == 1 and not ej.reverificando)
        # Se emitió la edición y una verificación nueva del slide 1, sin cerrar el run.
        assert de_tipo(ej, "editada") and len(de_tipo(ej, "verificacion_fidelidad")) > antes
        assert ej.esperando_decision and not ej.decision_recibida
        ej.registrar_decision(Decision())

    ej = _correr_con_reverificacion(actuar)
    verifs = de_tipo(ej, "verificacion_fidelidad")
    assert any(v["slide"] == 1 for v in verifs[-2:])  # la última verificación cubre el slide 1
    assert de_tipo(ej, "editada")[-1]["payload"]["texto_despues"] == "Editado a mano"
    from tests.test_orquestador_real import tipos
    assert tipos(ej)[-2:] == ["aprobada", "run_finalizada"]
