"""Pruebas del canal SSE: orden por seq, reanudación, rechazo de eventos inválidos y brecha con tope."""

import asyncio
import copy
import json
import random

import pytest
from fastapi.testclient import TestClient

from app.api.rutas import obtener_brecha_max
from app.events.cargador import cargar_eventos, ordenar_por_seq
from app.events.emisor import flujo_sse
from app.events.validador import comprobar_evento
from app.main import app

RUN_ID = "run_b5_cifra_inventada"
URL = f"/api/runs/{RUN_ID}/eventos"


def parsear_sse(texto: str) -> list[dict]:
    """Convierte el texto SSE en mensajes {id, event, data} para poder inspeccionarlos."""
    mensajes = []
    for bloque in texto.split("\n\n"):  # los mensajes se separan por línea en blanco
        if not bloque.strip():
            continue  # el final del texto deja un bloque vacío
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


def recolectar(eventos: list, brecha_max: float = 0.0, dormir=None) -> list[dict]:
    """Ejecuta flujo_sse hasta agotarlo y devuelve los mensajes ya parseados."""

    async def _correr() -> list[str]:
        # Si no se inyecta `dormir`, se usa el valor por defecto del emisor (asyncio.sleep).
        generador = flujo_sse(eventos, brecha_max) if dormir is None else flujo_sse(eventos, brecha_max, dormir)
        return [mensaje async for mensaje in generador]  # junta cada mensaje emitido

    return parsear_sse("".join(asyncio.run(_correr())))


@pytest.fixture
def cliente():
    """Cliente de pruebas con la brecha en 0 para que el flujo termine al instante."""
    app.dependency_overrides[obtener_brecha_max] = lambda: 0.0
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()  # no contamina otras pruebas


@pytest.fixture
def eventos():
    """Eventos reales de la grabación b5, ordenados por seq."""
    return cargar_eventos(RUN_ID)


def test_todos_los_eventos_de_la_grabacion_son_validos(eventos):
    """Control positivo: ningún evento de la grabación debe ser rechazado."""
    for evento in eventos:  # cada evento debe pasar tamaño y esquema
        assert comprobar_evento(evento) == [], f"seq {evento['seq']} fue rechazado"


def test_ordenar_por_seq_corrige_un_desorden(eventos):
    """Aunque el archivo venga barajado, el cargador entrega orden por seq."""
    barajados = copy.deepcopy(eventos)
    random.Random(7).shuffle(barajados)  # semilla fija: la prueba es repetible
    assert [e["seq"] for e in ordenar_por_seq(barajados)] == list(range(1, len(eventos) + 1))


def test_flujo_completo_sale_en_orden_con_id_seq(cliente, eventos):
    """Primera conexión: todos los eventos, en orden, con id = seq y origen grabado."""
    r = cliente.get(URL)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    mensajes = parsear_sse(r.text)
    assert [m["id"] for m in mensajes] == list(range(1, len(eventos) + 1))
    for m in mensajes:  # el servidor no debe reescribir el origen
        assert m["data"]["origen"] == "grabado"
        assert m["data"]["seq"] == m["id"]


def test_reanudacion_desde_un_seq_intermedio(cliente, eventos):
    """Con Last-Event-ID: 10 solo llegan los eventos con seq mayor que 10."""
    r = cliente.get(URL, headers={"Last-Event-ID": "10"})
    assert r.status_code == 200
    assert [m["id"] for m in parsear_sse(r.text)] == list(range(11, len(eventos) + 1))


def test_reconexion_sin_pendientes_devuelve_204(cliente, eventos):
    """Si ya se recibió todo, 204 evita que EventSource reconecte en bucle."""
    r = cliente.get(URL, headers={"Last-Event-ID": str(len(eventos))})
    assert r.status_code == 204


def test_run_inexistente_devuelve_404(cliente):
    """Un run_id que no existe en las grabaciones responde 404."""
    assert cliente.get("/api/runs/run_que_no_existe/eventos").status_code == 404


def test_last_event_id_no_numerico_devuelve_400(cliente):
    """Una cabecera Last-Event-ID inválida es un error del cliente."""
    assert cliente.get(URL, headers={"Last-Event-ID": "abc"}).status_code == 400


def test_evento_invalido_emite_error_visible_y_detiene_el_flujo(eventos):
    """Un evento fuera del catálogo produce evento_invalido y nada después."""
    rotos = copy.deepcopy(eventos)
    rotos[4]["tipo"] = "evento_inventado"  # el seq 5 deja de cumplir el contrato
    mensajes = recolectar(rotos)
    normales = [m for m in mensajes if m["event"] == "message"]
    assert [m["id"] for m in normales] == [1, 2, 3, 4]  # salen solo los previos
    ultimo = mensajes[-1]  # el error es lo último que se emite
    assert ultimo["event"] == "evento_invalido"
    assert ultimo["id"] is None  # no mueve el Last-Event-ID del cliente
    assert ultimo["data"]["seq"] == 5
    assert ultimo["data"]["motivos"]  # explica por qué se rechazó


def test_evento_demasiado_grande_se_rechaza_con_error_visible(eventos):
    """Un evento por encima del tope de 64 KB se rechaza y se avisa."""
    grandes = copy.deepcopy(eventos[:3])
    grandes[1]["payload"]["relleno"] = "x" * 70_000
    mensajes = recolectar(grandes)
    assert mensajes[-1]["event"] == "evento_invalido"
    assert "bytes" in mensajes[-1]["data"]["motivos"][0]


def test_la_brecha_se_limita_al_tope(eventos):
    """Una brecha original de 30 s se recorta a 2 s; con tope 0 no se espera nada."""
    tres = copy.deepcopy(eventos[:3])
    # Brechas originales: 1 s entre el primero y el segundo, 30 s entre el segundo y el tercero.
    tres[0]["timestamp"] = "2026-11-11T20:00:00-03:00"
    tres[1]["timestamp"] = "2026-11-11T20:00:01-03:00"
    tres[2]["timestamp"] = "2026-11-11T20:00:31-03:00"

    esperas = []

    async def dormir_falso(segundos: float) -> None:
        """Registra la espera pedida en vez de dormir de verdad."""
        esperas.append(segundos)

    recolectar(tres, brecha_max=2.0, dormir=dormir_falso)
    assert esperas == [1.0, 2.0]  # la de 30 s quedó en el tope

    esperas.clear()
    recolectar(tres, brecha_max=0.0, dormir=dormir_falso)
    assert esperas == []  # con tope 0 nunca se duerme