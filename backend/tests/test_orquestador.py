"""Pruebas de app/runs/orquestador.py: ejecutar_run emite el guion, respeta el ritmo y maneja los fallos.

Cómo están hechas:
  - Las pruebas son síncronas y envuelven su escenario en asyncio.run (igual que test_canal_sse.py),
    así no hace falta pytest-asyncio.
  - `dormir` se inyecta con un reloj falso: ninguna prueba espera de verdad.
  - Las unitarias usan una ficha sintética de 3 slides (guion de 13 eventos) y un validador
    controlado; las que llevan "real" en el nombre usan la plantilla, el kit y el validador reales.
"""

import asyncio
import inspect
import json
import logging

import pytest

from app import config
from app.resolution import Resolucion, cargar_fichas, resolver
from app.runs import orquestador
from app.runs import registro as modulo_registro
from app.runs.orquestador import ejecutar_run
from app.runs.registro import Ejecucion, EstadoRun, RegistroRuns
from app.runs.relleno import color_de_fondo, construir_guion

RUN_ID = "run_prueba01"
LOGGER = "app.runs.orquestador"


# --------------------------------------------------------------------------------------
# Ayudas y fixtures
# --------------------------------------------------------------------------------------

def hacer_ficha() -> dict:
    """Ficha sintética de 3 slides: da un guion de 13 eventos (3 de apertura, 3 por slide y el cierre)."""
    return {
        "id": "plantilla_prueba_3slides",
        "tipo_mensaje": "lista_de_pasos",
        "slides": [
            {"numero": 1, "rol": "gancho", "campos": [
                {"nombre": "{{titulo}}", "tipo": "texto", "origen_valor": "llm", "longitud_max": 30},
            ]},
            {"numero": 2, "rol": "desarrollo", "campos": [
                {"nombre": "{{cuerpo}}", "tipo": "texto", "origen_valor": "llm", "longitud_max": 200},
            ]},
            {"numero": 3, "rol": "fuentes", "campos": [
                {"nombre": "{{fuente_atribucion}}", "tipo": "texto", "origen_valor": "usuario", "longitud_max": 100},
                {"nombre": "{{fuente_licencia}}", "tipo": "texto", "origen_valor": "usuario", "longitud_max": 100},
            ]},
        ],
    }


def hacer_entrada() -> dict:
    """Entrada mínima con la forma que lee el relleno."""
    return {
        "fuente": {
            "tipo": "documento", "referencia": "guia.md", "idioma_salida": "es",
            "atribucion": "Autora de Prueba", "licencia": "CC BY 4.0",
        },
        "destino": {"red": "instagram", "formato": "carrusel_1080x1350"},
    }


def hacer_ejecucion() -> Ejecucion:
    """Ejecución grabada sobre la ficha sintética (debe crearse dentro del bucle de asyncio)."""
    ficha = hacer_ficha()
    resolucion = Resolucion(ficha=ficha, plantilla_id=ficha["id"], modo_plantilla="auto", num_slides=3)
    return Ejecucion(RUN_ID, hacer_entrada(), resolucion, "grabado")


def reloj_falso() -> tuple[list[float], object]:
    """Devuelve (esperas, dormir): `dormir` anota la espera pedida en vez de dormir de verdad."""
    esperas: list[float] = []

    async def dormir(segundos: float) -> None:
        """Registra la espera pedida."""
        esperas.append(segundos)

    return esperas, dormir


@pytest.fixture
def kit_de_prueba(tmp_path, monkeypatch):
    """Apunta la configuración a un kit temporal con fondo #112233."""
    (tmp_path / "kit_prueba.json").write_text(json.dumps({"paleta": {"fondo": "#112233"}}), encoding="utf-8")
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)
    monkeypatch.setattr(config, "KIT_MARCA", "kit_prueba")


@pytest.fixture
def contrato_ok(monkeypatch, kit_de_prueba):
    """Validador que acepta todo evento (aísla el orquestador de los esquemas); incluye el kit de prueba."""
    monkeypatch.setattr(modulo_registro, "comprobar_evento", lambda evento: [])


# --------------------------------------------------------------------------------------
# Camino feliz
# --------------------------------------------------------------------------------------

def test_emite_el_guion_completo_y_cierra_la_ejecucion(contrato_ok):
    """Se emiten los 13 eventos del guion, con seq 1..13, y la ejecución queda TERMINADA sin fallo."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        _, dormir = reloj_falso()
        await ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir)
        assert ejecucion.estado == EstadoRun.TERMINADA
        assert ejecucion.fallo is None
        assert [e["seq"] for e in ejecucion.eventos] == list(range(1, 14))
        assert ejecucion.eventos[0]["tipo"] == "run_iniciada"
        assert ejecucion.eventos[-1]["tipo"] == "run_finalizada"

    asyncio.run(escenario())


def test_los_eventos_emitidos_son_los_del_guion_de_relleno(contrato_ok):
    """El orquestador no cambia nada del guion: mismo orden, agentes, tipos, slides y payloads."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        guion = construir_guion(RUN_ID, ejecucion.entrada, ejecucion.resolucion, "#112233")
        _, dormir = reloj_falso()
        await ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir)
        assert len(ejecucion.eventos) == len(guion)
        for evento, paso in zip(ejecucion.eventos, guion):  # evento a evento contra su paso
            assert (evento["agente"], evento["tipo"], evento["payload"]) == (paso["agente"], paso["tipo"], paso["payload"])
            assert evento.get("slide") == paso.get("slide")
            assert evento["origen"] == "grabado"  # el origen lo fija la ejecución, no el orquestador

    asyncio.run(escenario())


def test_usa_el_color_de_fondo_del_kit(contrato_ok):
    """El color de los fondos sale de color_de_fondo (aquí, el kit de prueba)."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        _, dormir = reloj_falso()
        await ejecutar_run(ejecucion, ritmo_seg=0, dormir=dormir)
        fondos = [e["payload"]["fondo"]["valor"] for e in ejecucion.eventos if e["tipo"] == "colocar_fondo"]
        assert fondos == ["#112233"] * 3

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# Ritmo
# --------------------------------------------------------------------------------------

def test_hay_una_pausa_entre_eventos_pero_no_antes_del_primero(contrato_ok):
    """13 eventos llevan 12 pausas, todas del ritmo pedido."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        esperas, dormir = reloj_falso()
        await ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir)
        assert esperas == [0.6] * 12

    asyncio.run(escenario())


@pytest.mark.parametrize("ritmo", [0, 0.0, -1.0])
def test_con_ritmo_cero_o_negativo_nunca_se_duerme(contrato_ok, ritmo):
    """Un ritmo que no es positivo emite todo de corrido, sin llamar a dormir."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        esperas, dormir = reloj_falso()
        await ejecutar_run(ejecucion, ritmo_seg=ritmo, dormir=dormir)
        assert esperas == []
        assert ejecucion.estado == EstadoRun.TERMINADA

    asyncio.run(escenario())


def test_por_defecto_dormir_es_asyncio_sleep():
    """Sin inyectar nada, el orquestador duerme de verdad con asyncio.sleep."""
    assert inspect.signature(ejecutar_run).parameters["dormir"].default is asyncio.sleep


def test_un_lector_concurrente_ve_todos_los_eventos_y_el_cierre(contrato_ok):
    """Un lector que espera cambios (como el SSE) recibe los 13 eventos y detecta el final."""

    async def escenario():
        ejecucion = hacer_ejecucion()

        async def sin_pausa(segundos: float) -> None:
            """Cede el control un instante, para que el lector intercale su lectura."""
            await asyncio.sleep(0)

        async def lector() -> int:
            """Lee como el SSE: espera cambios hasta que la ejecución se cierra y no queda nada por leer."""
            vistos = 0
            while True:  # se repite hasta ver el final
                await ejecucion.esperar_cambio(vistos, timeout=1.0)
                if ejecucion.estado != EstadoRun.EN_CURSO and vistos == len(ejecucion.eventos):
                    return vistos
                vistos = len(ejecucion.eventos)

        tarea_lector = asyncio.create_task(lector())
        await ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=sin_pausa)
        assert await asyncio.wait_for(tarea_lector, timeout=2.0) == 13

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# Evento inválido
# --------------------------------------------------------------------------------------

def test_un_evento_invalido_corta_la_ejecucion_sin_lanzar_la_excepcion(monkeypatch, kit_de_prueba, caplog):
    """El 3.er evento rompe el contrato: quedan 2 en el buffer, el fallo es evento_invalido y no se emite más."""
    llamadas = []

    def rechaza_el_tercero(evento: dict) -> list[str]:
        """Acepta los dos primeros eventos y rechaza el tercero."""
        llamadas.append(evento["seq"])
        return ["motivo falso"] if len(llamadas) == 3 else []

    monkeypatch.setattr(modulo_registro, "comprobar_evento", rechaza_el_tercero)

    async def escenario():
        ejecucion = hacer_ejecucion()
        esperas, dormir = reloj_falso()
        resultado = await ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir)  # no debe lanzar
        assert resultado is None
        assert [e["seq"] for e in ejecucion.eventos] == [1, 2]
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.fallo == {
            "nombre": "evento_invalido",
            "datos": {"seq": 3, "tipo": "plantilla_elegida", "motivos": ["motivo falso"]},
        }
        assert llamadas == [1, 2, 3]  # después del rechazo no se intenta ningún evento más
        assert esperas == [0.6, 0.6]  # dos pausas: antes del 2.º y del 3.er evento

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        asyncio.run(escenario())
    assert "Evento inválido" in caplog.text and RUN_ID in caplog.text


# --------------------------------------------------------------------------------------
# Fallos inesperados
# --------------------------------------------------------------------------------------

def test_un_fallo_inesperado_deja_run_error_sin_filtrar_el_detalle(contrato_ok, monkeypatch, caplog):
    """Una excepción inesperada marca run_error con el tipo de error, pero no con su mensaje interno."""

    def explota(entrada: dict) -> str:
        """Simula un fallo interno con un dato que no debe llegar al cliente."""
        raise RuntimeError("clave-secreta-interna")

    monkeypatch.setattr(orquestador.relleno, "color_de_fondo", explota)

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecutar_run(ejecucion, ritmo_seg=0)  # no debe lanzar
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.eventos == []
        assert ejecucion.fallo["nombre"] == "run_error"
        mensaje = ejecucion.fallo["datos"]["motivos"][0]
        assert "RuntimeError" in mensaje
        assert "clave-secreta-interna" not in mensaje  # el detalle queda solo en el log del servidor

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        asyncio.run(escenario())
    # El detalle sí queda en el registro del servidor, con el run_id.
    assert "Fallo inesperado" in caplog.text and RUN_ID in caplog.text
    assert "clave-secreta-interna" in caplog.text


def test_un_kit_de_marca_inexistente_termina_en_run_error(contrato_ok, monkeypatch):
    """Sin kit en disco, el relleno falla con FileNotFoundError y la ejecución termina en run_error visible."""
    monkeypatch.setattr(config, "KIT_MARCA", "no_existe")

    async def escenario():
        ejecucion = hacer_ejecucion()
        await ejecutar_run(ejecucion, ritmo_seg=0)
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert "FileNotFoundError" in ejecucion.fallo["datos"]["motivos"][0]

    asyncio.run(escenario())


def test_un_fallo_a_mitad_de_camino_conserva_los_eventos_ya_emitidos(contrato_ok):
    """Si falla la 3.ª pausa, los 3 eventos ya emitidos siguen en el buffer y la ejecución queda en run_error."""

    async def escenario():
        ejecucion = hacer_ejecucion()
        pausas = []

        async def dormir_que_falla(segundos: float) -> None:
            """Falla en la tercera pausa."""
            pausas.append(segundos)
            if len(pausas) == 3:  # la tercera pausa explota
                raise ValueError("fallo de prueba")

        await ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir_que_falla)
        assert [e["seq"] for e in ejecucion.eventos] == [1, 2, 3]
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert "ValueError" in ejecucion.fallo["datos"]["motivos"][0]

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# Cancelación (apagado del servidor)
# --------------------------------------------------------------------------------------

def test_cancelar_marca_run_error_y_propaga_la_cancelacion(contrato_ok):
    """Al cancelar la tarea, los lectores reciben run_error y la cancelación se propaga (no se traga)."""

    async def escenario():
        ejecucion = hacer_ejecucion()

        async def dormir_eterno(segundos: float) -> None:
            """Se queda dormido hasta que lo cancelen."""
            await asyncio.sleep(30)

        tarea = asyncio.create_task(ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir_eterno))
        await asyncio.sleep(0.05)  # emite el primer evento y se duerme en la primera pausa
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
        assert [e["seq"] for e in ejecucion.eventos] == [1]
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.fallo["nombre"] == "run_error"
        assert "canceló" in ejecucion.fallo["datos"]["motivos"][0]

    asyncio.run(escenario())


def test_cancelar_todo_del_registro_cierra_la_ejecucion_con_run_error(contrato_ok):
    """El apagado real (RegistroRuns.cancelar_todo) deja la ejecución en run_error sin colgarse."""

    async def escenario():
        registro = RegistroRuns(max_activos=3, max_conservados=20)
        ejecucion = hacer_ejecucion()

        async def dormir_eterno(segundos: float) -> None:
            """Se queda dormido hasta que lo cancelen."""
            await asyncio.sleep(30)

        registro.lanzar(ejecutar_run(ejecucion, ritmo_seg=0.6, dormir=dormir_eterno))
        await asyncio.sleep(0.05)
        await asyncio.wait_for(registro.cancelar_todo(), timeout=2.0)
        assert ejecucion.estado == EstadoRun.FALLIDA
        assert ejecucion.fallo["nombre"] == "run_error"

    asyncio.run(escenario())


# --------------------------------------------------------------------------------------
# Con la plantilla, el kit y el validador reales
# --------------------------------------------------------------------------------------

def test_real_una_ejecucion_completa_emite_32_eventos_validos():
    """Entrada mínima real, plantilla real del MVP y validador real: 32 eventos, TERMINADA y sin fallo."""
    ruta = config.CONTRATOS_DIR / "input" / "examples" / "valido_minimo_todo_auto.json"
    with open(ruta, encoding="utf-8") as f:
        entrada = json.load(f)
    entrada.pop("$comment", None)  # el esquema no declara el comentario raíz
    resolucion, errores = resolver(entrada, cargar_fichas())
    assert errores == []

    async def escenario():
        ejecucion = Ejecucion("run_real_orquesta", entrada, resolucion, "grabado")
        await ejecutar_run(ejecucion, ritmo_seg=0)
        return ejecucion

    ejecucion = asyncio.run(escenario())
    assert ejecucion.fallo is None, ejecucion.fallo  # si falla, el motivo sale en el mensaje
    assert ejecucion.estado == EstadoRun.TERMINADA
    assert [e["seq"] for e in ejecucion.eventos] == list(range(1, 33))
    assert ejecucion.eventos[-1]["payload"]["estado_final"] == "requiere_humano"
    # El fondo de todos los slides es el del kit real.
    assert {e["payload"]["fondo"]["valor"] for e in ejecucion.eventos if e["tipo"] == "colocar_fondo"} == {color_de_fondo(entrada)}