"""POST /api/runs/{id}/aprobacion: 202, 404, 409 y 422. Sin red ni agentes: la ejecución se arma a mano."""

from types import SimpleNamespace

from app.runs.registro import RegistroRuns
from tests.test_rutas import ajustes, cliente_http, correr, falsos, hacer_entrada, kit_de_prueba, registro  # noqa: F401

FICHA = {
    "slides": [
        {"numero": 1, "campos": [
            {"nombre": "{{titulo}}", "tipo": "texto", "origen_valor": "llm", "longitud_max": 20},
            {"nombre": "{{cuerpo}}", "tipo": "texto", "origen_valor": "llm", "longitud_max": 50},
        ]},
    ]
}


async def _run_esperando(registro: RegistroRuns, esperando: bool = True):
    """Ejecución real con dos textos dibujados; con `esperando` abre la espera como lo hace el orquestador."""
    ejecucion = registro.crear(hacer_entrada(), SimpleNamespace(ficha=FICHA), "real")
    await ejecucion.emitir("redactor", "texto_propuesto", {"campo": "titulo", "texto": "Salud para todos"}, slide=1)
    await ejecucion.emitir("director_arte", "escribir_texto", {"campo": "titulo", "texto": "Salud para todos"}, slide=1)
    await ejecucion.emitir("director_arte", "escribir_texto", {"campo": "cuerpo", "texto": "Un derecho."}, slide=1)
    await ejecucion.emitir("revisor", "verificacion_fidelidad", {
        "afirmacion_id": "a1", "afirmacion": "Salud para todos", "clasificacion": "opinion_cta",
        "veredicto": "no_aplica", "cita": None, "motivo": "m",
    }, slide=1)
    if esperando:
        ejecucion.abrir_decision()
    return ejecucion


def _post(ejecucion_id: str, **kw):
    async def llamada():
        async with cliente_http() as c:
            return await c.post(f"/api/runs/{ejecucion_id}/aprobacion", **kw)
    return llamada()


def test_aprobar_sin_cambios_devuelve_202_y_registra_la_decision(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        r = await _post(ej.run_id, json={})
        return ej, r

    ej, r = correr(escenario())
    assert r.status_code == 202 and r.json() == {"run_id": ej.run_id, "ediciones": 0}
    assert ej._decision is not None and ej._decision.ediciones == ()


def test_las_ediciones_llegan_con_el_antes_calculado_por_el_servidor(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        # El cliente no manda el «antes»: lo calcula el servidor desde lo dibujado.
        r = await _post(ej.run_id, json={"ediciones": [{"slide": 1, "campo": "titulo", "texto": "Salud y bienestar"}], "comentario": "Ok", "excepcion": "Lo comprobé."})
        return ej, r

    ej, r = correr(escenario())
    assert r.status_code == 202 and r.json()["ediciones"] == 1
    e = ej._decision.ediciones[0]
    assert (e.texto_antes, e.texto_despues) == ("Salud para todos", "Salud y bienestar") and ej._decision.comentario == "Ok"


def test_run_inexistente_es_404(falsos, registro):
    assert correr(_post("run_noexiste", json={})).status_code == 404


def test_run_que_no_espera_es_409(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro, esperando=False)
        return await _post(ej.run_id, json={})

    r = correr(escenario())
    assert r.status_code == 409 and "no está esperando" in r.json()["motivos"][0]


def test_la_segunda_decision_es_409_y_no_pisa_la_primera(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        primera = await _post(ej.run_id, json={"comentario": "primera"})
        segunda = await _post(ej.run_id, json={"comentario": "segunda"})
        return ej, primera, segunda

    ej, primera, segunda = correr(escenario())
    assert primera.status_code == 202 and ej._decision.comentario == "primera"
    assert segunda.status_code == 409


def test_decision_invalida_es_422_con_todos_los_motivos_y_no_se_registra(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        r = await _post(ej.run_id, json={"ediciones": [
            {"slide": 1, "campo": "titulo", "texto": "x" * 21},
            {"slide": 9, "campo": "titulo", "texto": "y"},
        ]})
        return ej, r

    ej, r = correr(escenario())
    assert r.status_code == 422 and len(r.json()["motivos"]) == 2
    assert ej._decision is None and ej.esperando_decision  # sigue esperando una decisión buena


def test_cuerpo_que_no_es_json_es_422(falsos, registro):
    async def escenario():
        ej = await _run_esperando(registro)
        return await _post(ej.run_id, content=b"no es json", headers={"Content-Type": "application/json"})

    r = correr(escenario())
    assert r.status_code == 422 and "JSON" in r.json()["motivos"][0]


def test_el_orquestador_recibe_la_decision_del_endpoint_y_cierra_el_run(falsos, registro):
    """De punta a punta: el endpoint despierta la espera y salen editada, aprobada y run_finalizada."""
    from tests.test_orquestador_real import KIT, fabricar_agentes, fuente
    from tests.test_orquestador_real import resolucion as resolucion_real
    from app.runs.orquestador_real import ejecutar_run_real
    import asyncio

    async def escenario():
        ej = registro.crear(hacer_entrada(), resolucion_real("auto"), "real")
        tarea = asyncio.create_task(ejecutar_run_real(
            ej, fuente(), "cliente", KIT, fabricar_agentes()[0], esperar_aprobacion=True, aprobacion_timeout_seg=5.0))
        while not any(e["tipo"] == "aprobacion_solicitada" for e in ej.eventos):
            await asyncio.sleep(0.001)
        edicion = {"ediciones": [{"slide": 1, "campo": "titulo", "texto": "De la persona"}]}
        bloqueada = await _post(ej.run_id, json=edicion)  # editar quita el visto bueno
        assert bloqueada.status_code == 422
        r = await _post(ej.run_id, json={**edicion, "excepcion": "Lo comprobé."})
        await tarea
        return ej, r

    ej, r = correr(escenario())
    assert r.status_code == 202
    assert [e["tipo"] for e in ej.eventos][-4:] == ["aprobacion_solicitada", "editada", "aprobada", "run_finalizada"]
    assert ej.eventos[-1]["payload"]["estado_final"] == "aprobada_sin_visto_bueno"
