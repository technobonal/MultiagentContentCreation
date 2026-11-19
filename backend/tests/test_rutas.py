"""Pruebas de app/api/rutas.py y app/main.py: POST /api/runs, SSE en vivo, 429, run_error, apagado y CORS.

Cómo están hechas:
  - Las pruebas son síncronas y envuelven su escenario en asyncio.run (igual que test_canal_sse.py).
    Dentro llaman a la app con httpx.AsyncClient + ASGITransport: así el cliente, la ejecución en
    segundo plano y el SSE comparten UN bucle y la prueba decide cuándo llega cada evento.
  - El apagado (lifespan) y el CORS usan TestClient / un subproceso, porque ahí hay que arrancar la app.
  - Todo lleva un tope de tiempo: ninguna prueba espera de verdad ni puede colgarse.
  - Las unitarias reemplazan el validador de entrada, la resolución y el validador de eventos por
    colaboradores controlados, con un registro nuevo en cada prueba; las que llevan "real" en el
    nombre usan el esquema, el catálogo, el kit y los ejemplos reales de contracts/.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import rutas
from app.events.cargador import RunNoEncontrado
from app.events.emisor import LATIDO_SSE, flujo_sse, flujo_vivo
from app.events.validador import comprobar_evento
from app.main import app
from app.resolution import Resolucion
from app.runs import registro as modulo_registro
from app.runs import relleno
from app.runs.registro import EstadoRun, RegistroRuns, obtener_registro_runs
from app.runs.relleno import ORIGEN_RELLENO

BACKEND = Path(__file__).resolve().parents[1]  # carpeta backend/ (para lanzar el subproceso del CORS)
PATRON_RUN_ID = re.compile(r"^run_[a-z0-9_]{3,40}$")  # patrón del contrato (common.schema.json)
PLANTILLA_MVP = "ig_carrusel_pasos_oscuro_6slides"
SECRETO = "clave-secreta-interna"  # texto que jamás debe llegar al cliente


# --------------------------------------------------------------------------------------
# Ayudas y fixtures
# --------------------------------------------------------------------------------------

def parsear_sse(texto: str) -> list[dict]:
    """Convierte el texto SSE en mensajes {id, event, data}; los latidos (comentarios) se ignoran."""
    mensajes = []
    for bloque in texto.split("\n\n"):  # los mensajes se separan por línea en blanco
        # El final del texto deja un bloque vacío y los latidos empiezan por ":": no son mensajes.
        if not bloque.strip() or bloque.startswith(":"):
            continue
        msg = {"id": None, "event": "message", "data": None}
        for linea in bloque.split("\n"):  # cada línea es "campo: valor"
            campo, _, valor = linea.partition(": ")
            if campo == "id":
                msg["id"] = int(valor)
            elif campo == "event":
                msg["event"] = valor
            elif campo == "data":
                msg["data"] = json.loads(valor)
        mensajes.append(msg)
    return mensajes


def ids_de(respuesta: httpx.Response) -> list[int]:
    """Los id de los mensajes SSE de una respuesta, en orden."""
    return [m["id"] for m in parsear_sse(respuesta.text) if m["id"] is not None]


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


def hacer_resolucion() -> Resolucion:
    """Resolución sobre la ficha sintética."""
    ficha = hacer_ficha()
    return Resolucion(ficha=ficha, plantilla_id=ficha["id"], modo_plantilla="auto", num_slides=3)


def hacer_entrada() -> dict:
    """Entrada mínima con la forma que lee el relleno."""
    return {
        "fuente": {
            "tipo": "documento", "referencia": "guia.md", "idioma_salida": "es",
            "atribucion": "Autora de Prueba", "licencia": "CC BY 4.0",
        },
        "destino": {"red": "instagram", "formato": "carrusel_1080x1350"},
    }


def hacer_evento(seq: int, segundos: int = 0) -> dict:
    """Evento mínimo de una grabación falsa; `segundos` lo separa del instante base (20:00:00)."""
    return {
        "seq": seq,
        "tipo": "run_iniciada",
        "timestamp": f"2026-11-11T20:00:{segundos:02d}-03:00",
        "origen": "grabado",
        "payload": {"n": seq},
    }


def correr(escenario, limite: float = 10.0):
    """Corre la corutina de la prueba en un bucle nuevo con tope de tiempo: si algo se cuelga, la prueba falla."""
    return asyncio.run(asyncio.wait_for(escenario, limite))


def cliente_http() -> httpx.AsyncClient:
    """Cliente que habla directo con la app (sin red), en el bucle de asyncio que lo use."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://prueba")


async def esperar_ejecuciones(registro: RegistroRuns) -> None:
    """Espera a que terminen todas las ejecuciones lanzadas en segundo plano (con tope de 5 s)."""
    await asyncio.wait_for(asyncio.gather(*list(registro._tareas)), timeout=5.0)


@pytest.fixture
def ajustes() -> dict:
    """Valores que las dependencias entregan a las rutas; cada prueba puede cambiarlos."""
    return {"ritmo": 0.0, "latido": 0.05, "brecha": 0.0}


@pytest.fixture
def registro(ajustes):
    """Registro nuevo por prueba, instalado con dependency_overrides junto con ritmo, latido y brecha."""
    nuevo = RegistroRuns(max_activos=3, max_conservados=20)
    app.dependency_overrides[obtener_registro_runs] = lambda: nuevo
    app.dependency_overrides[rutas.obtener_ritmo_relleno] = lambda: ajustes["ritmo"]
    app.dependency_overrides[rutas.obtener_latido] = lambda: ajustes["latido"]
    app.dependency_overrides[rutas.obtener_brecha_max] = lambda: ajustes["brecha"]
    yield nuevo
    app.dependency_overrides.clear()  # no contamina otras pruebas


@pytest.fixture
def kit_de_prueba(tmp_path, monkeypatch):
    """Apunta la configuración a un kit temporal con fondo #112233 (así no se toca el kit real)."""
    (tmp_path / "kit_prueba.json").write_text(json.dumps({"paleta": {"fondo": "#112233"}}), encoding="utf-8")
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)
    monkeypatch.setattr(config, "KIT_MARCA", "kit_prueba")


@pytest.fixture
def falsos(registro, monkeypatch, kit_de_prueba):
    """Colaboradores controlados: valida la entrada, resuelve y valida eventos sin leer contracts/ ni el catálogo.

    Devuelve un objeto con lo que se puede configurar (motivos de rechazo, evento a rechazar) y lo que se vio.
    """
    estado = SimpleNamespace(
        motivos_forma=[],  # si no está vacía, comprobar_entrada rechaza con estos motivos
        motivos_resolucion=[],  # si no está vacía, resolver rechaza con estos motivos
        rechazar_evento_n=None,  # número de evento (1, 2, ...) que el validador rechaza
        eventos_vistos=0,  # cuántos eventos ha validado el registro
        entradas_vistas=[],  # entradas que llegaron al validador de forma
        llamadas_resolver=0,  # veces que se llamó a resolver
    )

    def comprobar_entrada_falso(entrada) -> list[str]:
        """Anota la entrada y devuelve los motivos configurados (vacío = válida)."""
        estado.entradas_vistas.append(entrada)
        return list(estado.motivos_forma)

    def resolver_falso(entrada, fichas):
        """Devuelve la resolución sintética, o (None, motivos) si la prueba pidió rechazo."""
        estado.llamadas_resolver += 1
        # Con motivos configurados, la resolución falla igual que la real (sin resolución).
        if estado.motivos_resolucion:
            return None, list(estado.motivos_resolucion)
        return hacer_resolucion(), []

    def comprobar_evento_falso(evento: dict) -> list[str]:
        """Acepta todo evento salvo el número `rechazar_evento_n`, que rechaza con un motivo."""
        estado.eventos_vistos += 1
        return ["motivo falso"] if estado.eventos_vistos == estado.rechazar_evento_n else []

    monkeypatch.setattr(rutas, "comprobar_entrada", comprobar_entrada_falso)
    monkeypatch.setattr(rutas, "cargar_fichas", lambda: {})
    monkeypatch.setattr(rutas, "resolver", resolver_falso)
    monkeypatch.setattr(modulo_registro, "comprobar_evento", comprobar_evento_falso)
    # El emisor valida las grabaciones con su propio validador: aquí acepta todo.
    monkeypatch.setattr("app.events.emisor.comprobar_evento", lambda evento: [])
    return estado


async def terminar_run(registro: RegistroRuns, eventos: int = 13, cerrar: bool = True):
    """Crea una ejecución a mano con `eventos` eventos y, si se pide, la deja TERMINADA."""
    ejecucion = registro.crear(hacer_entrada(), hacer_resolucion(), ORIGEN_RELLENO)
    for _ in range(eventos):  # un evento por vuelta, con el validador falso
        await ejecucion.emitir("sistema", "run_iniciada", {})
    # Sin cerrar, la ejecución queda EN_CURSO para que la prueba la maneje.
    if cerrar:
        await ejecucion.cerrar()
    return ejecucion


# --------------------------------------------------------------------------------------
# Dependencias
# --------------------------------------------------------------------------------------

def test_las_dependencias_entregan_los_valores_de_config(monkeypatch):
    """Brecha, ritmo y latido salen de config.py (las pruebas los reemplazan con dependency_overrides)."""
    monkeypatch.setattr(config, "BRECHA_MAX_SEG", 1.5)
    monkeypatch.setattr(config, "RITMO_RELLENO_SEG", 0.25)
    monkeypatch.setattr(config, "LATIDO_SEG", 7.0)
    assert (rutas.obtener_brecha_max(), rutas.obtener_ritmo_relleno(), rutas.obtener_latido()) == (1.5, 0.25, 7.0)


# --------------------------------------------------------------------------------------
# POST /api/runs: camino feliz
# --------------------------------------------------------------------------------------

def test_post_valido_responde_201_con_run_id_y_url_de_eventos(falsos, registro):
    """Una entrada válida devuelve 201 con un run_id del contrato y la URL de su canal de eventos."""

    async def escenario():
        async with cliente_http() as c:
            respuesta = await c.post("/api/runs", json=hacer_entrada())
        await esperar_ejecuciones(registro)
        return respuesta

    respuesta = correr(escenario())
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"run_id", "url_eventos"}
    assert PATRON_RUN_ID.match(cuerpo["run_id"])
    assert cuerpo["url_eventos"] == f"/api/runs/{cuerpo['run_id']}/eventos"


def test_post_registra_la_ejecucion_con_la_entrada_la_resolucion_y_el_origen_de_relleno(falsos, registro):
    """La ejecución guarda la entrada recibida, la resolución decidida y el origen 'grabado' del relleno."""

    async def escenario():
        async with cliente_http() as c:
            respuesta = await c.post("/api/runs", json=hacer_entrada())
        await esperar_ejecuciones(registro)
        return respuesta.json()["run_id"]

    run_id = correr(escenario())
    ejecucion = registro.obtener(run_id)
    assert ejecucion.entrada == hacer_entrada()  # el cuerpo llegó completo al registro
    assert ejecucion.resolucion.plantilla_id == "plantilla_prueba_3slides"
    assert ejecucion.origen == ORIGEN_RELLENO == "grabado"
    assert falsos.entradas_vistas == [hacer_entrada()]  # y ese mismo cuerpo fue el que se validó


def test_post_lanza_el_orquestador_y_la_ejecucion_termina(falsos, registro):
    """Tras el POST el orquestador corre en segundo plano: 13 eventos y la ejecución TERMINADA."""

    async def escenario():
        async with cliente_http() as c:
            respuesta = await c.post("/api/runs", json=hacer_entrada())
        await esperar_ejecuciones(registro)
        return registro.obtener(respuesta.json()["run_id"])

    ejecucion = correr(escenario())
    assert ejecucion.estado == EstadoRun.TERMINADA
    assert ejecucion.fallo is None
    assert [e["seq"] for e in ejecucion.eventos] == list(range(1, 14))


def test_post_pasa_el_ritmo_de_la_dependencia_al_orquestador(falsos, registro, ajustes, monkeypatch):
    """El ritmo que entrega la dependencia es el que recibe ejecutar_run (y la ejecución es la recién creada)."""
    recibido = []

    async def ejecutar_run_falso(ejecucion, ritmo_seg):
        """Anota con qué se lo llamó en vez de emitir el guion."""
        recibido.append((ejecucion.run_id, ritmo_seg))

    monkeypatch.setattr(rutas, "ejecutar_run", ejecutar_run_falso)
    ajustes["ritmo"] = 0.6

    async def escenario():
        async with cliente_http() as c:
            respuesta = await c.post("/api/runs", json=hacer_entrada())
        await esperar_ejecuciones(registro)
        return respuesta.json()["run_id"]

    run_id = correr(escenario())
    assert recibido == [(run_id, 0.6)]


def test_post_y_get_en_vivo_mientras_la_ejecucion_corre(falsos, registro, ajustes):
    """Con un ritmo real (aunque corto), el SSE abierto durante la ejecución recibe los 13 eventos y cierra."""
    ajustes["ritmo"] = 0.01  # unos 0,12 s en total: la ejecución sigue en curso cuando llega el GET

    async def escenario():
        async with cliente_http() as c:
            creada = await c.post("/api/runs", json=hacer_entrada())
            ejecucion = registro.obtener(creada.json()["run_id"])
            assert ejecucion.estado == EstadoRun.EN_CURSO  # el GET llega a una ejecución viva
            eventos = await asyncio.wait_for(c.get(creada.json()["url_eventos"]), timeout=5.0)
        await esperar_ejecuciones(registro)
        return eventos

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    assert ids_de(respuesta) == list(range(1, 14))
    assert parsear_sse(respuesta.text)[-1]["data"]["tipo"] == "run_finalizada"


def test_dos_post_crean_ejecuciones_distintas(falsos, registro):
    """Cada POST recibe su propio run_id."""

    async def escenario():
        async with cliente_http() as c:
            a = await c.post("/api/runs", json=hacer_entrada())
            b = await c.post("/api/runs", json=hacer_entrada())
        await esperar_ejecuciones(registro)
        return a.json()["run_id"], b.json()["run_id"]

    a, b = correr(escenario())
    assert a != b


# --------------------------------------------------------------------------------------
# POST /api/runs: rechazos 422
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("cuerpo", [
    b"",  # cuerpo vacío
    b"esto no es json",  # texto cualquiera
    b'{"fuente": ',  # JSON cortado
    b"\xff\xfe\x00",  # bytes que no son una codificación válida
], ids=["vacio", "texto", "json_cortado", "bytes_invalidos"])
def test_post_con_cuerpo_que_no_es_json_devuelve_422_sin_crear_ejecucion(falsos, registro, cuerpo):
    """Un cuerpo ilegible se rechaza con un motivo claro; no llega a validarse ni se crea ninguna ejecución."""

    async def escenario():
        async with cliente_http() as c:
            return await c.post("/api/runs", content=cuerpo, headers={"content-type": "application/json"})

    respuesta = correr(escenario())
    assert respuesta.status_code == 422
    assert respuesta.headers["content-type"] == "application/json"
    assert respuesta.json() == {"motivos": ["el cuerpo no es un JSON válido"]}
    assert falsos.entradas_vistas == []  # no se llegó a validar la forma
    assert registro._runs == {}  # ni se creó una ejecución


def test_post_con_forma_invalida_devuelve_422_con_los_motivos_sin_resolver_ni_crear(falsos, registro):
    """Si la forma no cumple el esquema, salen los motivos tal cual y no se resuelve ni se crea nada."""
    falsos.motivos_forma = ["fuente: falta el campo tipo", "destino/red: valor no permitido"]

    async def escenario():
        async with cliente_http() as c:
            return await c.post("/api/runs", json={"basura": True})

    respuesta = correr(escenario())
    assert respuesta.status_code == 422
    assert respuesta.json() == {"motivos": ["fuente: falta el campo tipo", "destino/red: valor no permitido"]}
    assert falsos.entradas_vistas == [{"basura": True}]  # el validador recibió el cuerpo recibido
    assert falsos.llamadas_resolver == 0  # la resolución solo corre con una forma válida
    assert registro._runs == {}


def test_post_con_resolucion_invalida_devuelve_422_con_los_motivos_sin_crear(falsos, registro):
    """Si las reglas que cruzan archivos fallan (plantilla inexistente, idioma, ...) también es 422 y no se crea nada."""
    falsos.motivos_resolucion = ["plantilla fija inexistente en templates/catalog: no_existe"]

    async def escenario():
        async with cliente_http() as c:
            return await c.post("/api/runs", json=hacer_entrada())

    respuesta = correr(escenario())
    assert respuesta.status_code == 422
    assert respuesta.json() == {"motivos": ["plantilla fija inexistente en templates/catalog: no_existe"]}
    assert falsos.llamadas_resolver == 1
    assert registro._runs == {}


def test_la_ruta_de_runs_solo_acepta_post(falsos, registro):
    """GET sobre /api/runs no existe (405) y /api/runs/<id> sin /eventos tampoco (404)."""

    async def escenario():
        async with cliente_http() as c:
            return await c.get("/api/runs"), await c.get("/api/runs/run_abc12345")

    lista, uno = correr(escenario())
    assert lista.status_code == 405
    assert uno.status_code == 404


# --------------------------------------------------------------------------------------
# POST /api/runs: límite de ejecuciones (429)
# --------------------------------------------------------------------------------------

def test_post_por_encima_del_maximo_de_activos_devuelve_429_con_retry_after(falsos, registro, ajustes):
    """Con 2 en curso y máximo 2, la tercera recibe 429, Retry-After: 10 y el motivo del registro; no se crea."""
    registro.max_activos = 2
    ajustes["ritmo"] = 30.0  # las dos primeras siguen en curso durante toda la prueba

    async def escenario():
        async with cliente_http() as c:
            primeras = [await c.post("/api/runs", json=hacer_entrada()) for _ in range(2)]  # caben las dos
            tercera = await c.post("/api/runs", json=hacer_entrada())
        await registro.cancelar_todo()  # no dejar tareas dormidas al cerrar el bucle
        return primeras, tercera

    primeras, tercera = correr(escenario())
    assert [p.status_code for p in primeras] == [201, 201]
    assert tercera.status_code == 429
    assert tercera.headers["retry-after"] == "10"
    assert tercera.json() == {"motivos": ["ya hay 2 ejecuciones en curso (máximo 2)"]}
    assert len(registro._runs) == 2  # la rechazada no dejó rastro


def test_una_ejecucion_terminada_libera_su_cupo_para_el_siguiente_post(falsos, registro):
    """Con máximo 1: tras terminar la primera, un nuevo POST vuelve a dar 201."""
    registro.max_activos = 1

    async def escenario():
        async with cliente_http() as c:
            primera = await c.post("/api/runs", json=hacer_entrada())
            await esperar_ejecuciones(registro)  # la primera termina (ritmo 0)
            segunda = await c.post("/api/runs", json=hacer_entrada())
        await esperar_ejecuciones(registro)
        return primera, segunda

    primera, segunda = correr(escenario())
    assert (primera.status_code, segunda.status_code) == (201, 201)
    assert primera.json()["run_id"] != segunda.json()["run_id"]


def test_el_429_no_se_confunde_con_el_422_de_validacion(falsos, registro, ajustes):
    """Una entrada inválida recibe 422 aunque el registro esté lleno: la validación va antes del límite."""
    registro.max_activos = 1
    ajustes["ritmo"] = 30.0

    async def escenario():
        async with cliente_http() as c:
            await c.post("/api/runs", json=hacer_entrada())  # ocupa el único cupo
            falsos.motivos_forma = ["roto"]
            invalida = await c.post("/api/runs", json={})
        await registro.cancelar_todo()
        return invalida

    assert correr(escenario()).status_code == 422


# --------------------------------------------------------------------------------------
# GET /api/runs/{run_id}/eventos: ejecuciones en memoria
# --------------------------------------------------------------------------------------

def test_get_de_una_ejecucion_terminada_entrega_todo_con_las_cabeceras_sse(falsos, registro):
    """200, text/event-stream, sin caché y sin buffer de Nginx; los 13 eventos en orden con id = seq."""

    async def escenario():
        ejecucion = await terminar_run(registro)
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos")

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/event-stream")
    assert respuesta.headers["cache-control"] == "no-cache"
    assert respuesta.headers["x-accel-buffering"] == "no"
    assert ids_de(respuesta) == list(range(1, 14))
    assert LATIDO_SSE not in respuesta.text  # una ejecución cerrada no manda latidos


def test_get_en_vivo_recibe_los_eventos_que_llegan_despues_de_conectar(falsos, registro):
    """El GET abierto sobre una ejecución en curso se queda esperando y entrega lo que se emite luego."""

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=1, cerrar=False)
        async with cliente_http() as c:
            lector = asyncio.create_task(c.get(f"/api/runs/{ejecucion.run_id}/eventos"))
            await asyncio.sleep(0.1)  # el cliente ya recibió el 1 y espera más
            assert not lector.done()  # sigue abierto mientras la ejecución está en curso
            for _ in range(2):  # llegan dos eventos más
                await ejecucion.emitir("sistema", "run_iniciada", {})
            await ejecucion.cerrar()
            return await asyncio.wait_for(lector, timeout=2.0)

    assert ids_de(correr(escenario())) == [1, 2, 3]


def test_get_en_curso_manda_latidos_y_cierra_al_terminar(falsos, registro, ajustes):
    """Sin eventos nuevos el SSE manda ': ping' cada intervalo (el latido de la dependencia) y cierra al terminar."""
    ajustes["latido"] = 0.02

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=0, cerrar=False)
        async with cliente_http() as c:
            lector = asyncio.create_task(c.get(f"/api/runs/{ejecucion.run_id}/eventos"))
            await asyncio.sleep(0.15)
            await ejecucion.cerrar()
            return await asyncio.wait_for(lector, timeout=2.0)

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    assert respuesta.text.count(LATIDO_SSE) >= 2
    assert parsear_sse(respuesta.text) == []  # solo latidos, ningún evento


@pytest.mark.parametrize("cabeceras, parametros, esperados", [
    ({"Last-Event-ID": "5"}, {}, list(range(6, 14))),  # solo la cabecera
    ({}, {"desde": 5}, list(range(6, 14))),  # solo ?desde
    ({"Last-Event-ID": "8"}, {"desde": 3}, list(range(9, 14))),  # si llegan las dos, manda la cabecera
    ({"Last-Event-ID": "0"}, {}, list(range(1, 14))),  # 0 = desde el principio
    ({}, {"desde": 0}, list(range(1, 14))),
], ids=["cabecera", "desde", "cabecera_manda", "cabecera_cero", "desde_cero"])
def test_get_reanuda_solo_con_los_eventos_posteriores(falsos, registro, cabeceras, parametros, esperados):
    """Last-Event-ID y ?desde=N entregan solo los eventos con seq mayor; la cabecera tiene prioridad."""

    async def escenario():
        ejecucion = await terminar_run(registro)
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos", headers=cabeceras, params=parametros)

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    assert ids_de(respuesta) == esperados


@pytest.mark.parametrize("cabeceras, parametros", [
    ({"Last-Event-ID": "13"}, {}),  # justo el último
    ({"Last-Event-ID": "99"}, {}),  # más allá del último
    ({}, {"desde": 13}),
    ({}, {"desde": 99}),
], ids=["cabecera_total", "cabecera_mayor", "desde_total", "desde_mayor"])
def test_get_de_una_ejecucion_terminada_sin_pendientes_devuelve_204(falsos, registro, cabeceras, parametros):
    """Si ya se recibió todo, 204 con cuerpo vacío: así EventSource deja de reconectar."""

    async def escenario():
        ejecucion = await terminar_run(registro)
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos", headers=cabeceras, params=parametros)

    respuesta = correr(escenario())
    assert respuesta.status_code == 204
    assert respuesta.content == b""


def test_get_primera_conexion_a_una_ejecucion_terminada_sin_eventos_no_da_204(falsos, registro):
    """Con desde 0 nunca hay 204: una ejecución cerrada sin eventos responde 200 y un cuerpo vacío."""

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=0)
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos")

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    assert respuesta.content == b""


def test_get_reconexion_a_una_ejecucion_en_curso_sin_pendientes_espera_y_no_da_204(falsos, registro):
    """En curso, 'sin pendientes' no es 'terminó': el SSE espera y entrega solo el evento que llega después."""

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=2, cerrar=False)
        async with cliente_http() as c:
            lector = asyncio.create_task(
                c.get(f"/api/runs/{ejecucion.run_id}/eventos", headers={"Last-Event-ID": "2"})
            )
            await asyncio.sleep(0.1)
            assert not lector.done()  # no respondió 204: sigue esperando
            await ejecucion.emitir("sistema", "run_iniciada", {})
            await ejecucion.cerrar()
            return await asyncio.wait_for(lector, timeout=2.0)

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    assert ids_de(respuesta) == [3]


def test_get_reconexion_a_una_ejecucion_fallida_sin_pendientes_reentrega_el_error(falsos, registro):
    """Una ejecución fallida no da 204: el error no lleva id y pudo perderse, así que se vuelve a enviar."""

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=2, cerrar=False)
        await ejecucion.fallar("fallo de prueba")
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos", headers={"Last-Event-ID": "2"})

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    mensajes = parsear_sse(respuesta.text)
    assert [(m["event"], m["id"]) for m in mensajes] == [("run_error", None)]
    assert mensajes[0]["data"] == {"motivos": ["fallo de prueba"]}


# --------------------------------------------------------------------------------------
# GET /api/runs/{run_id}/eventos: validación de la reanudación y ejecuciones inexistentes
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor, detalle", [
    ("abc", "Last-Event-ID debe ser un entero"),
    ("1.5", "Last-Event-ID debe ser un entero"),
    ("-1", "Last-Event-ID no puede ser negativo"),
])
def test_get_con_last_event_id_invalido_devuelve_400(falsos, registro, valor, detalle):
    """Una cabecera Last-Event-ID que no es un entero >= 0 es un error del cliente, con su detalle."""

    async def escenario():
        ejecucion = await terminar_run(registro)
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos", headers={"Last-Event-ID": valor})

    respuesta = correr(escenario())
    assert respuesta.status_code == 400
    assert respuesta.json() == {"detail": detalle}


def test_get_valida_la_cabecera_antes_de_buscar_la_ejecucion(falsos, registro):
    """Con una cabecera inválida el error es 400 aunque el run no exista (y no 404)."""

    async def escenario():
        async with cliente_http() as c:
            return await c.get("/api/runs/run_no_existe/eventos", headers={"Last-Event-ID": "abc"})

    assert correr(escenario()).status_code == 400


@pytest.mark.parametrize("valor", ["-1", "abc", "1.5"])
def test_get_con_desde_invalido_devuelve_422(falsos, registro, valor):
    """?desde negativo, no numérico o decimal lo rechaza la validación de FastAPI."""

    async def escenario():
        async with cliente_http() as c:
            return await c.get("/api/runs/run_cualquiera/eventos", params={"desde": valor})

    assert correr(escenario()).status_code == 422


def test_get_de_un_run_que_no_esta_en_memoria_ni_grabado_devuelve_404(falsos, registro, monkeypatch):
    """Ni en el registro ni en las grabaciones: 404 con el run_id en el detalle."""

    def no_existe(run_id: str):
        """Imita al cargador cuando ninguna grabación tiene ese run_id."""
        raise RunNoEncontrado(run_id)

    monkeypatch.setattr(rutas, "cargar_eventos", no_existe)

    async def escenario():
        async with cliente_http() as c:
            return await c.get("/api/runs/run_no_existe/eventos")

    respuesta = correr(escenario())
    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "No existe la ejecución run_no_existe"}


# --------------------------------------------------------------------------------------
# GET /api/runs/{run_id}/eventos: grabaciones
# --------------------------------------------------------------------------------------

def test_get_de_una_grabacion_usa_el_cargador_y_reanuda(falsos, registro, monkeypatch):
    """Un run que no está en memoria se sirve desde las grabaciones, con reanudación y 204 al final."""
    grabados = [hacer_evento(n) for n in range(1, 5)]
    monkeypatch.setattr(rutas, "cargar_eventos", lambda run_id: grabados)

    async def escenario():
        async with cliente_http() as c:
            url = "/api/runs/run_grabado01/eventos"
            return (
                await c.get(url),
                await c.get(url, headers={"Last-Event-ID": "2"}),
                await c.get(url, headers={"Last-Event-ID": "4"}),
            )

    todo, desde_2, al_final = correr(escenario())
    assert ids_de(todo) == [1, 2, 3, 4]
    assert ids_de(desde_2) == [3, 4]
    assert al_final.status_code == 204


def test_get_prefiere_la_ejecucion_en_memoria_a_una_grabacion_con_el_mismo_id(falsos, registro, monkeypatch):
    """Si el run está en el registro, no se consulta el cargador: se sirve en vivo."""

    def no_debe_llamarse(run_id: str):
        """Falla la prueba si la ruta busca en las grabaciones pudiendo servir la ejecución viva."""
        raise AssertionError("no debía consultar las grabaciones")

    monkeypatch.setattr(rutas, "cargar_eventos", no_debe_llamarse)

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=3)
        async with cliente_http() as c:
            return await c.get(f"/api/runs/{ejecucion.run_id}/eventos")

    assert ids_de(correr(escenario())) == [1, 2, 3]


def test_get_pasa_la_brecha_y_el_latido_de_las_dependencias_a_los_flujos(falsos, registro, ajustes, monkeypatch):
    """La brecha va a flujo_sse (grabaciones) y el latido a flujo_vivo (ejecuciones en memoria)."""
    ajustes["brecha"] = 1.25
    ajustes["latido"] = 0.5
    vistos = {}

    def flujo_sse_espia(eventos, brecha_max, *args):
        """Anota la brecha recibida y delega en el flujo real."""
        vistos["brecha"] = brecha_max
        return flujo_sse(eventos, brecha_max, *args)

    def flujo_vivo_espia(ejecucion, desde_seq, latido_seg):
        """Anota desde_seq y latido recibidos y delega en el flujo real."""
        vistos["desde"], vistos["latido"] = desde_seq, latido_seg
        return flujo_vivo(ejecucion, desde_seq, latido_seg)

    monkeypatch.setattr(rutas, "flujo_sse", flujo_sse_espia)
    monkeypatch.setattr(rutas, "flujo_vivo", flujo_vivo_espia)
    monkeypatch.setattr(rutas, "cargar_eventos", lambda run_id: [hacer_evento(1)])

    async def escenario():
        ejecucion = await terminar_run(registro, eventos=2)
        async with cliente_http() as c:
            await c.get("/api/runs/run_grabado01/eventos")  # grabación
            await c.get(f"/api/runs/{ejecucion.run_id}/eventos", headers={"Last-Event-ID": "1"})  # en memoria

    correr(escenario())
    assert vistos == {"brecha": 1.25, "desde": 1, "latido": 0.5}


# --------------------------------------------------------------------------------------
# Fallos visibles de punta a punta (POST + GET)
# --------------------------------------------------------------------------------------

def test_un_fallo_inesperado_llega_al_cliente_como_run_error_sin_detalles_internos(falsos, registro, monkeypatch):
    """POST válido, el relleno explota: el SSE trae solo run_error con el tipo de error y sin el texto interno."""

    def explota(entrada: dict) -> str:
        """Simula un fallo interno con un dato que no debe llegar al cliente."""
        raise RuntimeError(SECRETO)

    monkeypatch.setattr(relleno, "color_de_fondo", explota)

    async def escenario():
        async with cliente_http() as c:
            creada = await c.post("/api/runs", json=hacer_entrada())
            assert creada.status_code == 201  # el POST responde bien: el fallo ocurre después, en segundo plano
            return await asyncio.wait_for(c.get(creada.json()["url_eventos"]), timeout=5.0)

    respuesta = correr(escenario())
    assert respuesta.status_code == 200
    mensajes = parsear_sse(respuesta.text)
    assert [(m["event"], m["id"]) for m in mensajes] == [("run_error", None)]  # sin eventos y sin id
    assert "RuntimeError" in mensajes[0]["data"]["motivos"][0]
    assert SECRETO not in respuesta.text  # el detalle se queda en el log del servidor


def test_un_evento_invalido_llega_al_cliente_como_evento_invalido_tras_los_validos(falsos, registro):
    """POST válido, el 3.er evento rompe el contrato: el SSE trae 2 eventos y luego evento_invalido con seq 3."""
    falsos.rechazar_evento_n = 3

    async def escenario():
        async with cliente_http() as c:
            creada = await c.post("/api/runs", json=hacer_entrada())
            return await asyncio.wait_for(c.get(creada.json()["url_eventos"]), timeout=5.0)

    respuesta = correr(escenario())
    mensajes = parsear_sse(respuesta.text)
    assert [(m["event"], m["id"]) for m in mensajes] == [("message", 1), ("message", 2), ("evento_invalido", None)]
    assert mensajes[-1]["data"] == {"seq": 3, "tipo": "plantilla_elegida", "motivos": ["motivo falso"]}


# --------------------------------------------------------------------------------------
# Apagado (main.py: ciclo_de_vida)
# --------------------------------------------------------------------------------------

def test_al_apagar_la_app_se_cancelan_las_ejecuciones_en_curso(falsos, registro, ajustes, monkeypatch):
    """Al salir del lifespan se llama a cancelar_todo y esa llamada deja la ejecución FALLIDA con run_error."""
    ajustes["ritmo"] = 30.0  # la ejecución se queda dormida entre eventos
    observado = {}  # estado de la ejecución justo antes y justo después de cancelar_todo
    cancelar_original = registro.cancelar_todo

    async def cancelar_todo_espia() -> None:
        """Anota el estado de la ejecución antes y después de la cancelación real."""
        observado["antes"] = ejecucion.estado
        await cancelar_original()
        observado["despues"] = ejecucion.estado

    with TestClient(app) as cliente:
        creada = cliente.post("/api/runs", json=hacer_entrada())
        assert creada.status_code == 201
        ejecucion = registro.obtener(creada.json()["run_id"])
        monkeypatch.setattr(registro, "cancelar_todo", cancelar_todo_espia)
        limite = time.monotonic() + 2.0
        # Espera (con tope) a que el orquestador emita el primer evento y se duerma en la primera pausa.
        while not ejecucion.eventos and time.monotonic() < limite:
            time.sleep(0.01)
        assert ejecucion.estado == EstadoRun.EN_CURSO
    # Al salir del `with` se ejecutó el apagado: el registro del override es el que se canceló.
    assert observado == {"antes": EstadoRun.EN_CURSO, "despues": EstadoRun.FALLIDA}
    assert ejecucion.fallo["nombre"] == "run_error"
    assert "canceló" in ejecucion.fallo["datos"]["motivos"][0]
    assert registro._tareas == set()


def test_apagar_la_app_sin_ejecuciones_no_falla(falsos, registro):
    """El apagado sin nada en curso termina sin errores."""
    with TestClient(app):  # arrancar y salir ejecuta el ciclo de vida completo
        assert registro._runs == {}
    assert registro._tareas == set()


# --------------------------------------------------------------------------------------
# CORS (main.py): se decide al importar, así que cada caso corre en un subproceso con su entorno
# --------------------------------------------------------------------------------------

CODIGO_PREFLIGHT = """
import json, sys
from fastapi.testclient import TestClient
from app.main import app

origen = sys.argv[1]
r = TestClient(app).options(
    "/api/runs",
    headers={
        "Origin": origen,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type, last-event-id",
    },
)
print(json.dumps({"estado": r.status_code, "cabeceras": {k.lower(): v for k, v in r.headers.items()}}))
"""


def preflight(cors_origenes: str, origen: str) -> dict:
    """Lanza un Python nuevo con CORS_ORIGENES dado y devuelve estado y cabeceras de un preflight de POST /api/runs."""
    entorno = {**os.environ, "CORS_ORIGENES": cors_origenes, "PYTHONPATH": str(BACKEND)}
    resultado = subprocess.run(
        [sys.executable, "-c", CODIGO_PREFLIGHT, origen],
        env=entorno, cwd=BACKEND, capture_output=True, text=True, timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    return json.loads(resultado.stdout.strip().splitlines()[-1])  # la última línea es el JSON


def test_sin_cors_configurado_no_se_agregan_cabeceras_cors():
    """Sin CORS_ORIGENES (desarrollo con el proxy de Vite) la app no responde cabeceras Access-Control-*."""
    respuesta = preflight("", "http://localhost:5173")
    assert "access-control-allow-origin" not in respuesta["cabeceras"]


def test_con_cors_configurado_el_preflight_del_post_se_acepta():
    """Con un origen permitido, el preflight autoriza POST y las cabeceras Content-Type y Last-Event-ID."""
    respuesta = preflight("http://lienzo.ejemplo.com, http://otro.ejemplo.com,", "http://lienzo.ejemplo.com")
    assert respuesta["estado"] == 200
    cabeceras = respuesta["cabeceras"]
    assert cabeceras["access-control-allow-origin"] == "http://lienzo.ejemplo.com"
    metodos = cabeceras["access-control-allow-methods"].upper()
    assert "POST" in metodos and "GET" in metodos
    permitidas = cabeceras["access-control-allow-headers"].lower()
    assert "content-type" in permitidas and "last-event-id" in permitidas


def test_con_cors_configurado_un_origen_no_listado_se_rechaza():
    """Un origen que no está en CORS_ORIGENES no pasa el preflight (400)."""
    respuesta = preflight("http://lienzo.ejemplo.com", "http://intruso.ejemplo.com")
    assert respuesta["estado"] == 400
    assert "access-control-allow-origin" not in respuesta["cabeceras"]


# --------------------------------------------------------------------------------------
# Con el esquema, el catálogo, el kit y los ejemplos reales
# --------------------------------------------------------------------------------------

def cargar_ejemplo(nombre: str) -> dict:
    """Lee un ejemplo de entrada sin su $comment raíz (el esquema no lo declara)."""
    with open(config.CONTRATOS_DIR / "input" / "examples" / nombre, encoding="utf-8") as f:
        ejemplo = json.load(f)
    ejemplo.pop("$comment", None)
    return ejemplo


def ejemplos_reales() -> list[Path]:
    """Lista las rutas de todos los ejemplos de entrada (para parametrizar la prueba contra el POST)."""
    return sorted((config.CONTRATOS_DIR / "input" / "examples").glob("*.json"))


@pytest.mark.parametrize("ruta", ejemplos_reales(), ids=lambda r: r.name)
def test_real_post_de_cada_ejemplo_coincide_con_su_nombre(registro, ruta):
    """valido_* responde 201 e invalido_* responde 422 con motivos (a lo sumo 6, como limita el validador)."""
    entrada = cargar_ejemplo(ruta.name)

    async def escenario():
        async with cliente_http() as c:
            respuesta = await c.post("/api/runs", json=entrada)
        await esperar_ejecuciones(registro)  # si arrancó una ejecución, que termine antes de cerrar el bucle
        return respuesta

    respuesta = correr(escenario())
    # El prefijo del nombre es la convención del proyecto (la misma de test_resolution.py).
    if ruta.name.startswith("valido_"):
        assert respuesta.status_code == 201, respuesta.text
        assert PATRON_RUN_ID.match(respuesta.json()["run_id"])
    else:
        assert respuesta.status_code == 422, respuesta.text
        motivos = respuesta.json()["motivos"]
        assert motivos and len(motivos) <= 6
        assert all(isinstance(m, str) and m for m in motivos)


@pytest.mark.parametrize("cuerpo", ["[]", '"texto"', "123", "null", "{}"], ids=["lista", "texto", "numero", "nulo", "vacio"])
def test_real_post_con_un_json_que_no_es_una_entrada_devuelve_422(registro, cuerpo):
    """JSON válido pero que no cumple el esquema de entrada: 422 con motivos y sin ejecución creada."""

    async def escenario():
        async with cliente_http() as c:
            return await c.post("/api/runs", content=cuerpo, headers={"content-type": "application/json"})

    respuesta = correr(escenario())
    assert respuesta.status_code == 422
    assert respuesta.json()["motivos"]
    assert registro._runs == {}


def test_real_post_y_sse_de_punta_a_punta_con_la_entrada_minima(registro):
    """Entrada mínima real: el SSE trae los 32 eventos válidos, con origen grabado, y cierra con run_finalizada."""

    async def escenario():
        async with cliente_http() as c:
            creada = await c.post("/api/runs", json=cargar_ejemplo("valido_minimo_todo_auto.json"))
            assert creada.status_code == 201, creada.text
            return await asyncio.wait_for(c.get(creada.json()["url_eventos"]), timeout=10.0)

    respuesta = correr(escenario())
    mensajes = parsear_sse(respuesta.text)
    assert [m["id"] for m in mensajes] == list(range(1, 33))
    for mensaje in mensajes:  # cada evento cumple el contrato real y conserva el origen del relleno
        assert comprobar_evento(mensaje["data"]) == []
        assert mensaje["data"]["origen"] == "grabado"
    assert mensajes[-1]["data"]["tipo"] == "run_finalizada"
    assert mensajes[-1]["data"]["payload"]["estado_final"] == "requiere_humano"


def test_real_post_con_plantilla_fija_resuelve_en_modo_fijo(registro):
    """valido_url_con_fijos: el POST da 201 y la ejecución guarda la plantilla fija del MVP."""

    async def escenario():
        async with cliente_http() as c:
            creada = await c.post("/api/runs", json=cargar_ejemplo("valido_url_con_fijos.json"))
        await esperar_ejecuciones(registro)
        return creada

    creada = correr(escenario())
    assert creada.status_code == 201, creada.text
    resolucion = registro.obtener(creada.json()["run_id"]).resolucion
    assert (resolucion.plantilla_id, resolucion.modo_plantilla) == (PLANTILLA_MVP, "fijo")