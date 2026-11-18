"""Pruebas de la reanudación con ?desde=N y de su prioridad frente a Last-Event-ID."""

import pytest
from fastapi.testclient import TestClient

from app.api.rutas import obtener_brecha_max
from app.events.cargador import cargar_eventos
from app.main import app

RUN_ID = "run_b5_cifra_inventada"
URL = f"/api/runs/{RUN_ID}/eventos"


def ids_de(texto: str) -> list[int]:
    """Extrae los valores de las líneas `id: N` de un texto SSE."""
    # Cada mensaje SSE del contrato lleva una línea "id: <seq>".
    return [int(linea[4:]) for linea in texto.splitlines() if linea.startswith("id: ")]


@pytest.fixture
def cliente():
    """Cliente de pruebas con la brecha en 0 para que el flujo termine al instante."""
    app.dependency_overrides[obtener_brecha_max] = lambda: 0.0
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()  # no contamina otras pruebas


@pytest.fixture
def total():
    """Cantidad de eventos de la grabación b5."""
    return len(cargar_eventos(RUN_ID))


def test_desde_en_la_url_reanuda_como_la_cabecera(cliente, total):
    """?desde=10 entrega solo los eventos con seq mayor que 10."""
    r = cliente.get(URL, params={"desde": 10})
    assert r.status_code == 200
    assert ids_de(r.text) == list(range(11, total + 1))


def test_la_cabecera_manda_sobre_desde(cliente, total):
    """Si llegan las dos, gana Last-Event-ID."""
    r = cliente.get(URL, params={"desde": 3}, headers={"Last-Event-ID": "20"})
    assert ids_de(r.text) == list(range(21, total + 1))


def test_desde_igual_al_total_devuelve_204(cliente, total):
    """Con ?desde al final no queda nada: 204 para que EventSource no reconecte."""
    assert cliente.get(URL, params={"desde": total}).status_code == 204


def test_desde_negativo_devuelve_422(cliente):
    """Un valor negativo no es válido para el parámetro."""
    assert cliente.get(URL, params={"desde": -1}).status_code == 422


def test_desde_no_numerico_devuelve_422(cliente):
    """Un valor que no es entero lo rechaza la validación de FastAPI."""
    assert cliente.get(URL, params={"desde": "abc"}).status_code == 422