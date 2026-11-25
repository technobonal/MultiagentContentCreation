"""La espera de la aprobación humana en el orquestador real: decide la persona, vence el tiempo, ediciones y topes."""

import asyncio

from app.runs.aprobacion import Decision, Edicion
from app.runs.orquestador_real import ejecutar_run_real
from app.runs.registro import Ejecucion, EstadoRun
from tests.test_orquestador_real import ENTRADA, KIT, RUN_ID, de_tipo, fabricar_agentes, fuente, resolucion, tipos


def _correr_con_persona(decidir, aprobacion_timeout_seg=5.0, timeout_seg=None, agentes=None):
    """Corre un run que espera aprobación; `decidir(ejecucion)` es lo que hace la persona (o None si no hace nada)."""
    agentes = agentes or fabricar_agentes()[0]

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, resolucion("auto"), "real")
        tarea = asyncio.create_task(ejecutar_run_real(
            ejecucion, fuente(), "cliente", KIT, agentes, timeout_seg,
            esperar_aprobacion=True, aprobacion_timeout_seg=aprobacion_timeout_seg,
        ))
        if decidir is not None:
            # La persona actúa cuando el run ya pidió la aprobación.
            while not any(e["tipo"] == "aprobacion_solicitada" for e in ejecucion.eventos):
                await asyncio.sleep(0.001)
            decidir(ejecucion)
        await tarea
        return ejecucion

    return asyncio.run(principal())


def test_el_run_espera_la_decision_antes_de_finalizar():
    seen = {}

    def decidir(ej):
        seen["esperando"] = ej.esperando_decision
        seen["ultimo"] = ej.eventos[-1]["tipo"]  # al pedir la aprobación todavía no hay run_finalizada
        seen["estado"] = ej.estado
        ej.registrar_decision(Decision())

    ej = _correr_con_persona(decidir)
    assert seen == {"esperando": True, "ultimo": "aprobacion_solicitada", "estado": EstadoRun.EN_CURSO}
    assert tipos(ej)[-3:] == ["aprobacion_solicitada", "aprobada", "run_finalizada"]
    assert ej.estado == EstadoRun.TERMINADA and not ej.esperando_decision


def test_aprobada_la_emite_la_persona_con_su_comentario():
    ej = _correr_con_persona(lambda e: e.registrar_decision(Decision((), "Se ve bien.")))
    aprobada = de_tipo(ej, "aprobada")[0]
    assert aprobada["agente"] == "humano" and aprobada["payload"] == {"decision": "aprobada", "comentario": "Se ve bien."}
    assert de_tipo(ej, "editada") == []


def test_sin_comentario_el_payload_no_lleva_la_clave():
    ej = _correr_con_persona(lambda e: e.registrar_decision(Decision()))
    assert de_tipo(ej, "aprobada")[0]["payload"] == {"decision": "aprobada"}


def test_las_ediciones_se_emiten_antes_de_aprobar_y_con_el_antes_declarado():
    def decidir(ej):
        e = Edicion(1, "titulo", "titulo 1", "Título de la persona")
        ej.registrar_decision(Decision((e,), None))

    ej = _correr_con_persona(decidir)
    assert tipos(ej)[-4:] == ["aprobacion_solicitada", "editada", "aprobada", "run_finalizada"]
    editada = de_tipo(ej, "editada")[0]
    assert editada["agente"] == "humano" and editada["slide"] == 1
    assert editada["payload"] == {"campo": "titulo", "texto_antes": "titulo 1", "texto_despues": "Título de la persona"}


def test_si_nadie_decide_el_run_termina_en_requiere_humano_sin_aprobada():
    ej = _correr_con_persona(None, aprobacion_timeout_seg=0.05)
    assert "aprobada" not in tipos(ej) and tipos(ej)[-2:] == ["aprobacion_solicitada", "run_finalizada"]
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "requiere_humano"
    assert ej.estado == EstadoRun.TERMINADA and not ej.esperando_decision  # liberó su cupo


def test_una_decision_tardia_se_rechaza():
    ej = _correr_con_persona(None, aprobacion_timeout_seg=0.05)
    assert ej.registrar_decision(Decision()) is False


def test_la_espera_de_la_persona_no_cuenta_para_el_tope_de_los_agentes():
    """El tope de los agentes es de 1 s y la persona tarda más: el run no se corta por tiempo."""

    def decidir(ej):
        async def tarde():
            await asyncio.sleep(1.2)
            ej.registrar_decision(Decision())
        asyncio.get_running_loop().create_task(tarde())

    ej = _correr_con_persona(decidir, timeout_seg=1.0)
    assert ej.estado == EstadoRun.TERMINADA and "aprobada" in tipos(ej)


def test_la_aprobacion_con_bloqueante_abierto_no_cambia_el_estado_final():
    from tests.test_orquestador_real import hallazgo
    agentes, _ = fabricar_agentes(hallazgo_fijo=lambda n: hallazgo(2, "bloqueante") if n == 2 else None)
    ej = _correr_con_persona(lambda e: e.registrar_decision(Decision()), agentes=agentes)
    assert de_tipo(ej, "aprobada") and de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "requiere_humano"


def test_sin_esperar_aprobacion_todo_sigue_igual():
    agentes, _ = fabricar_agentes()

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, resolucion("auto"), "real")
        await ejecutar_run_real(ejecucion, fuente(), "cliente", KIT, agentes, esperar_aprobacion=False)
        return ejecucion

    ej = asyncio.run(principal())
    assert "aprobada" not in tipos(ej) and tipos(ej)[-2:] == ["aprobacion_solicitada", "run_finalizada"]
    assert not ej.esperando_decision
