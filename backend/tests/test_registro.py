"""Pruebas de app/runs/registro.py: la ejecución (buffer de eventos y estado) y el registro (límites y tareas).

Cómo están hechas:
  - Las pruebas son síncronas y envuelven su escenario en asyncio.run (igual que test_canal_sse.py),
    así no hace falta pytest-asyncio. Cada prueba usa UN solo asyncio.run, porque la Condition de
    una Ejecucion queda atada al bucle donde se usa por primera vez.
  - Las unitarias reemplazan el validador por uno controlado (acepta todo o rechaza todo), para
    probar el registro sin depender de los esquemas.
  - Las que llevan "real" en el nombre usan el validador y los contratos reales de contracts/.
"""

import asyncio
import re
from datetime import datetime

import pytest

from app import config
from app.runs import registro as modulo_registro
from app.runs.registro import (
    Ejecucion,
    EstadoRun,
    EventoInvalido,
    LimiteDeRuns,
    RegistroRuns,
    obtener_registro_runs,
)

# Patrón de run_id del contrato (common.schema.json).
PATRON_RUN_ID = re.compile(r"^run_[a-z0-9_]{3,40}$")


# --------------------------------------------------------------------------------------
# Ayudas y fixtures
# --------------------------------------------------------------------------------------

@pytest.fixture
def contrato_ok(monkeypatch):
    """Validador que acepta todo evento (aísla el registro de los esquemas)."""
    monkeypatch.setattr(modulo_registro, "comprobar_evento", lambda evento: [])


@pytest.fixture
def contrato_roto(monkeypatch):
    """Validador que rechaza todo evento con un motivo conocido."""
    monkeypatch.setattr(modulo_registro, "comprobar_evento", lambda evento: ["payload: motivo de prueba"])


@pytest.fixture
def registro_limpio():
    """Vacía la caché de obtener_registro_runs antes y después, para no contaminar otras pruebas."""
    obtener_registro_runs.cache_clear()
    yield
    obtener_registro_runs.cache_clear()


def hacer_ejecucion(origen: str = "real", run_id: str = "run_prueba01") -> Ejecucion:
    """Crea una Ejecucion suelta con una entrada y una resolución de mentira."""
    return Ejecucion(run_id, {"entrada": "x"}, None, origen)


# --------------------------------------------------------------------------------------
# Ejecucion.emitir
# --------------------------------------------------------------------------------------

def test_emitir_arma_el_evento_con_el_sobre_del_contrato(contrato_ok):
    """El evento sale con versión, run_id, seq 1, origen, agente, tipo, payload y timestamp con zona."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        evento = await ejecucion.emitir("sistema", "run_iniciada", {"dato": 1})
        assert evento["version"] == "0.1"
        assert evento["run_id"] == "run_prueba01"
        assert evento["seq"] == 1
        assert evento["origen"] == "real"
        assert (evento["agente"], evento["tipo"], evento["payload"]) == ("sistema", "run_iniciada", {"dato": 1})
        # El timestamp es ISO 8601 con zona horaria (el contrato lo exige).
        assert datetime.fromisoformat(evento["timestamp"]).utcoffset() is not None
        assert ejecucion.eventos == [evento]  # entra al buffer tal cual

    asyncio.run(escenario())


def test_emitir_incluye_slide_y_causa_solo_si_se_dan(contrato_ok):
    """slide y causa viajan únicamente en los eventos que los usan."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        sin = await ejecucion.emitir("sistema", "run_iniciada", {})
        con = await ejecucion.emitir("redactor", "texto_propuesto", {}, slide=2, causa=1)
        assert "slide" not in sin and "causa" not in sin
        assert (con["slide"], con["causa"]) == (2, 1)

    asyncio.run(escenario())


def test_emitir_asigna_seq_consecutivo_desde_1(contrato_ok):
    """Tres eventos seguidos reciben seq 1, 2 y 3, y el seq N queda en el índice N-1."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        for _ in range(3):  # tres eventos seguidos
            await ejecucion.emitir("sistema", "run_iniciada", {})
        assert [e["seq"] for e in ejecucion.eventos] == [1, 2, 3]

    asyncio.run(escenario())


def test_emitir_no_reescribe_el_origen_de_la_ejecucion(contrato_ok):
    """Una ejecución grabada emite siempre 'grabado' y una real, 'real'."""

    async def escenario():
        grabada = await hacer_ejecucion(origen="grabado").emitir("sistema", "run_iniciada", {})
        real = await hacer_ejecucion(origen="real").emitir("sistema", "run_iniciada", {})
        assert (grabada["origen"], real["origen"]) == ("grabado", "real")

    asyncio.run(escenario())


def test_evento_invalido_no_entra_al_buffer_y_deja_la_ejecucion_fallida(contrato_roto):
    """Un evento que rompe el contrato lanza EventoInvalido, no se guarda y el fallo viaja como evento_invalido."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        with pytest.raises(EventoInvalido) as info:
            await ejecucion.emitir("sistema", "run_iniciada", {})
        assert info.value.motivos == ["payload: motivo de prueba"]
        assert str(info.value) == "payload: motivo de prueba"
        assert ejecucion.eventos == []  # nada inválido llega al buffer
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.fallo == {
            "nombre": "evento_invalido",
            "datos": {"seq": 1, "tipo": "run_iniciada", "motivos": ["payload: motivo de prueba"]},
        }

    asyncio.run(escenario())


def test_evento_invalido_conserva_los_anteriores_y_reporta_su_propio_seq(monkeypatch):
    """Si el segundo evento es inválido, el primero sigue en el buffer y el fallo apunta al seq 2."""
    respuestas = [[], ["roto"]]  # el primero pasa y el segundo se rechaza
    monkeypatch.setattr(modulo_registro, "comprobar_evento", lambda evento: respuestas.pop(0))

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecucion.emitir("sistema", "run_iniciada", {})
        with pytest.raises(EventoInvalido):
            await ejecucion.emitir("estratega", "brief_emitido", {})
        assert [e["seq"] for e in ejecucion.eventos] == [1]
        assert ejecucion.fallo["datos"]["seq"] == 2
        assert ejecucion.fallo["datos"]["tipo"] == "brief_emitido"

    asyncio.run(escenario())


def test_evento_invalido_une_los_motivos_en_el_mensaje():
    """La excepción guarda la lista de motivos y los une con '; ' en su texto."""
    error = EventoInvalido(["uno", "dos"])
    assert error.motivos == ["uno", "dos"]
    assert str(error) == "uno; dos"


# --------------------------------------------------------------------------------------
# Ejecucion.terminar / cerrar / fallar
# --------------------------------------------------------------------------------------

def test_cerrar_marca_la_ejecucion_como_terminada():
    """Cerrar con éxito deja el estado TERMINADA y sin fallo."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecucion.cerrar()
        assert ejecucion.estado == EstadoRun.TERMINADA
        assert ejecucion.fallo is None

    asyncio.run(escenario())


def test_fallar_registra_un_run_error_con_el_mensaje():
    """Un error inesperado deja FALLIDA y un fallo 'run_error' con el mensaje como único motivo."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecucion.fallar("algo salió mal")
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.fallo == {"nombre": "run_error", "datos": {"motivos": ["algo salió mal"]}}

    asyncio.run(escenario())


def test_el_primer_cierre_manda_y_no_se_pisa():
    """Cerrar y luego fallar (o al revés) conserva el primer resultado."""

    async def escenario():
        primero_cierra = hacer_ejecucion(run_id="run_cierra01")
        await primero_cierra.cerrar()
        await primero_cierra.fallar("tarde")
        assert primero_cierra.estado == EstadoRun.TERMINADA and primero_cierra.fallo is None

        primero_falla = hacer_ejecucion(run_id="run_falla001")
        await primero_falla.fallar("primero")
        await primero_falla.cerrar()
        assert primero_falla.estado == EstadoRun.FALLIDA
        assert primero_falla.fallo["datos"]["motivos"] == ["primero"]

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# Ejecucion.esperar_cambio
# --------------------------------------------------------------------------------------

def test_esperar_cambio_devuelve_true_si_ya_hay_eventos_nuevos(contrato_ok):
    """Si el buffer ya tiene más eventos que el índice, no espera."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecucion.emitir("sistema", "run_iniciada", {})
        assert await ejecucion.esperar_cambio(0, timeout=1.0) is True

    asyncio.run(escenario())


def test_esperar_cambio_devuelve_false_al_vencer_el_timeout():
    """Sin eventos nuevos y en curso, vence el timeout y devuelve False (el SSE manda un latido)."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        assert await ejecucion.esperar_cambio(0, timeout=0.05) is False

    asyncio.run(escenario())


def test_esperar_cambio_se_despierta_cuando_llega_un_evento(contrato_ok):
    """Un lector dormido despierta (True) apenas se emite un evento nuevo."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector = asyncio.create_task(ejecucion.esperar_cambio(0, timeout=2.0))
        await asyncio.sleep(0.01)  # deja que el lector se duerma primero
        assert not lector.done()
        await ejecucion.emitir("sistema", "run_iniciada", {})
        assert await lector is True

    asyncio.run(escenario())


def test_esperar_cambio_se_despierta_cuando_la_ejecucion_se_cierra():
    """Un lector dormido también despierta si la ejecución termina sin más eventos."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        lector = asyncio.create_task(ejecucion.esperar_cambio(0, timeout=2.0))
        await asyncio.sleep(0.01)
        await ejecucion.cerrar()
        assert await lector is True

    asyncio.run(escenario())


def test_esperar_cambio_en_una_ejecucion_ya_cerrada_no_espera():
    """Una ejecución cerrada responde True al instante: el lector debe ver el final."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecucion.cerrar()
        assert await ejecucion.esperar_cambio(0, timeout=0.05) is True

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# RegistroRuns: ids, crear y obtener
# --------------------------------------------------------------------------------------

def test_crear_registra_la_ejecucion_con_un_run_id_valido():
    """Cada ejecución recibe un run_id del patrón del contrato y se puede recuperar con obtener."""
    registro = RegistroRuns(max_activos=3, max_conservados=20)
    ejecucion = registro.crear({"fuente": 1}, "resolucion", "real")
    assert PATRON_RUN_ID.match(ejecucion.run_id)
    assert registro.obtener(ejecucion.run_id) is ejecucion
    # Guarda lo que recibió, sin transformarlo.
    assert (ejecucion.entrada, ejecucion.resolucion, ejecucion.origen) == ({"fuente": 1}, "resolucion", "real")
    assert ejecucion.estado == EstadoRun.EN_CURSO


def test_obtener_un_run_inexistente_devuelve_none():
    """Un id desconocido (o ya descartado) no lanza error: devuelve None."""
    assert RegistroRuns(3, 20).obtener("run_no_existe") is None


def test_el_run_id_nunca_repite_uno_en_uso(monkeypatch):
    """Si el azar produce un id ya usado, se vuelve a sortear hasta dar uno libre."""
    valores = iter(["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"])  # el segundo intento choca con el primero
    monkeypatch.setattr(modulo_registro.secrets, "token_hex", lambda n: next(valores))
    registro = RegistroRuns(max_activos=5, max_conservados=20)
    primera = registro.crear({}, None, "real")
    segunda = registro.crear({}, None, "real")
    assert (primera.run_id, segunda.run_id) == ("run_aaaaaaaa", "run_bbbbbbbb")


# --------------------------------------------------------------------------------------
# RegistroRuns: límite de ejecuciones en curso
# --------------------------------------------------------------------------------------

def test_superar_el_maximo_de_activos_lanza_limite_de_runs():
    """Con 2 en curso y máximo 2, la tercera se rechaza con un mensaje que dice cuántas hay."""
    registro = RegistroRuns(max_activos=2, max_conservados=20)
    registro.crear({}, None, "real")
    registro.crear({}, None, "real")
    with pytest.raises(LimiteDeRuns) as info:
        registro.crear({}, None, "real")
    assert "2" in str(info.value)


def test_una_ejecucion_terminada_o_fallida_libera_su_lugar():
    """Solo cuentan las EN_CURSO: al terminar (bien o mal) vuelve a haber cupo."""

    async def escenario():
        registro = RegistroRuns(max_activos=2, max_conservados=20)
        a = registro.crear({}, None, "real")
        b = registro.crear({}, None, "real")
        await a.cerrar()  # termina bien
        c = registro.crear({}, None, "real")  # cabe una nueva
        await b.fallar("error")  # termina mal
        registro.crear({}, None, "real")  # y otra más
        assert c.estado == EstadoRun.EN_CURSO

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# RegistroRuns: poda de ejecuciones terminadas
# --------------------------------------------------------------------------------------

def test_la_poda_descarta_las_terminadas_mas_viejas_por_encima_del_maximo():
    """Con máximo 2 conservadas, al crear la cuarta se descarta la terminada más vieja."""

    async def escenario():
        registro = RegistroRuns(max_activos=10, max_conservados=2)
        creadas = []
        for _ in range(3):  # tres ejecuciones que terminan una tras otra
            ejecucion = registro.crear({}, None, "real")
            await ejecucion.cerrar()
            creadas.append(ejecucion)
        cuarta = registro.crear({}, None, "real")  # aquí se poda
        assert registro.obtener(creadas[0].run_id) is None  # la más vieja se fue
        assert registro.obtener(creadas[1].run_id) is creadas[1]
        assert registro.obtener(creadas[2].run_id) is creadas[2]
        assert registro.obtener(cuarta.run_id) is cuarta

    asyncio.run(escenario())


def test_la_poda_cuenta_tambien_las_fallidas():
    """Una ejecución fallida es 'terminada' a efectos de la poda y puede descartarse."""

    async def escenario():
        registro = RegistroRuns(max_activos=10, max_conservados=1)
        fallida = registro.crear({}, None, "real")
        await fallida.fallar("error")
        buena = registro.crear({}, None, "real")
        await buena.cerrar()
        registro.crear({}, None, "real")  # dispara la poda: hay 2 terminadas y se conserva 1
        assert registro.obtener(fallida.run_id) is None
        assert registro.obtener(buena.run_id) is buena

    asyncio.run(escenario())


def test_la_poda_nunca_descarta_ejecuciones_en_curso():
    """Aunque el máximo conservado sea 0, las que siguen en curso no se tocan."""
    registro = RegistroRuns(max_activos=10, max_conservados=0)
    activas = [registro.crear({}, None, "real") for _ in range(3)]
    for ejecucion in activas:  # todas siguen disponibles
        assert registro.obtener(ejecucion.run_id) is ejecucion


# --------------------------------------------------------------------------------------
# RegistroRuns: tareas
# --------------------------------------------------------------------------------------

def test_lanzar_corre_la_corutina_y_suelta_la_tarea_al_terminar():
    """La tarea se retiene (referencia fuerte) mientras corre y se suelta sola al acabar."""

    async def escenario():
        registro = RegistroRuns(3, 20)

        async def trabajo():
            return "listo"

        tarea = registro.lanzar(trabajo())
        assert registro._tareas == {tarea}  # retenida: si no, el recolector podría borrarla
        assert await tarea == "listo"
        await asyncio.sleep(0)  # deja correr el callback que la suelta
        assert registro._tareas == set()

    asyncio.run(escenario())


def test_cancelar_todo_cancela_las_tareas_pendientes_y_espera_a_que_acaben():
    """Al apagar la app, una tarea larga se cancela y cancelar_todo no se cuelga."""

    async def escenario():
        registro = RegistroRuns(3, 20)

        async def dormilona():
            await asyncio.sleep(30)

        tarea = registro.lanzar(dormilona())
        await asyncio.sleep(0)  # deja que la tarea arranque
        await asyncio.wait_for(registro.cancelar_todo(), timeout=2.0)
        assert tarea.cancelled()

    asyncio.run(escenario())


def test_cancelar_todo_sin_tareas_no_falla():
    """Sin nada pendiente, cancelar_todo termina sin error."""
    asyncio.run(RegistroRuns(3, 20).cancelar_todo())


# --------------------------------------------------------------------------------------
# obtener_registro_runs (dependencia de FastAPI)
# --------------------------------------------------------------------------------------

def test_obtener_registro_runs_es_un_singleton_con_los_limites_de_config(registro_limpio):
    """Devuelve siempre la misma instancia y la crea con los límites de config.py."""
    registro = obtener_registro_runs()
    assert obtener_registro_runs() is registro
    assert registro.max_activos == config.MAX_RUNS_ACTIVOS
    assert registro.max_conservados == config.MAX_RUNS_CONSERVADOS


# --------------------------------------------------------------------------------------
# Con el validador y los contratos reales
# --------------------------------------------------------------------------------------

def test_real_emitir_acepta_un_run_iniciada_valido():
    """Con el esquema real, un run_iniciada correcto entra al buffer con seq 1."""

    async def escenario():
        ejecucion = hacer_ejecucion(origen="grabado", run_id="run_real0001")
        payload = {
            "entrada_ref": "run_real0001",
            "plataforma": "instagram",
            "idioma_salida": "es",
            "num_slides": 6,
            "verificacion": "sin_fuente_verificada",
            "fuente": {"tipo": "documento", "atribucion": "Autora de prueba", "licencia": "CC BY 4.0"},
        }
        evento = await ejecucion.emitir("sistema", "run_iniciada", payload)
        assert evento["seq"] == 1 and ejecucion.eventos == [evento]

    asyncio.run(escenario())


def test_real_emitir_rechaza_un_tipo_fuera_del_catalogo():
    """Con el esquema real, un tipo inventado falla con motivos y deja la ejecución FALLIDA."""

    async def escenario():
        ejecucion = hacer_ejecucion(run_id="run_real0002")
        with pytest.raises(EventoInvalido) as info:
            await ejecucion.emitir("sistema", "evento_inventado", {})
        assert info.value.motivos  # explica por qué se rechazó
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.fallo["nombre"] == "evento_invalido"
        assert ejecucion.eventos == []

    asyncio.run(escenario())

# ---------------------------- espera de la decisión humana (HITL) ----------------------------

def _ejecucion():
    from app.runs.registro import Ejecucion
    return Ejecucion("run_hitl", {}, None, "real")


def test_decision_sin_espera_abierta_se_rechaza():
    async def escenario():
        e = _ejecucion()
        return e.esperando_decision, e.registrar_decision("d")

    assert asyncio.run(escenario()) == (False, False)


def test_la_decision_despierta_la_espera_y_la_cierra():
    async def escenario():
        e = _ejecucion()
        e.abrir_decision()
        assert e.esperando_decision
        espera = asyncio.create_task(e.esperar_decision(5))
        await asyncio.sleep(0)  # deja que la espera arranque
        assert e.registrar_decision("la decisión") is True
        return await espera, e.esperando_decision

    assert asyncio.run(escenario()) == ("la decisión", False)


def test_solo_vale_la_primera_decision():
    async def escenario():
        e = _ejecucion()
        e.abrir_decision()
        return e.registrar_decision("primera"), e.registrar_decision("segunda"), await e.esperar_decision(1)

    assert asyncio.run(escenario()) == (True, False, "primera")


def test_si_vence_el_tiempo_devuelve_none_y_cierra_la_espera():
    async def escenario():
        e = _ejecucion()
        e.abrir_decision()
        resultado = await e.esperar_decision(0.01)
        return resultado, e.esperando_decision, e.registrar_decision("tarde")

    assert asyncio.run(escenario()) == (None, False, False)


def test_decision_registrada_antes_de_esperar_no_se_pierde():
    """El endpoint puede llegar entre `abrir_decision` y el inicio de la espera del orquestador."""
    async def escenario():
        e = _ejecucion()
        e.abrir_decision()
        e.registrar_decision("temprana")
        return await e.esperar_decision(1)

    assert asyncio.run(escenario()) == "temprana"
