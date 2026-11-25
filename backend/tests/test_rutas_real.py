"""Pruebas del despacho de POST /api/runs según el modo: relleno (sin contexto) o real (con contexto).

La validación, la resolución, la carga de la fuente y los orquestadores se reemplazan por falsos: aquí solo
se comprueba el CABLEADO (qué se llama, con qué argumentos y qué se responde).
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import rutas
from app.fuentes.cargador_fuente import FuenteError
from app.runs.contexto_real import ORIGEN_REAL, ContextoReal
from app.runs.registro import LimiteDeRuns, obtener_registro_runs
from app.runs.relleno import ORIGEN_RELLENO

# Entrada mínima: la validación real está reemplazada, solo importa la referencia de la fuente.
ENTRADA = {"fuente": {"referencia": "guia.txt"}}


class RegistroFalso:
    """Registro que anota cómo se crea y se lanza una ejecución."""

    def __init__(self, error_al_crear: Exception | None = None):
        self.error_al_crear = error_al_crear
        self.creadas: list[tuple] = []  # (entrada, resolucion, origen)
        self.lanzadas = 0

    def crear(self, entrada, resolucion, origen):
        """Simula la creación: falla si se pidió un error (tope de runs), si no devuelve una ejecución mínima."""
        if self.error_al_crear is not None:
            raise self.error_al_crear
        self.creadas.append((entrada, resolucion, origen))
        return SimpleNamespace(run_id="run_prueba")

    def lanzar(self, corutina):
        """Simula el lanzamiento: cuenta y cierra la corutina para que no quede sin esperar."""
        self.lanzadas += 1
        corutina.close()


@pytest.fixture
def entorno(monkeypatch):
    """Cliente de pruebas con validación, resolución, fuente y orquestadores falsos; devuelve todo lo observable."""
    registro = RegistroFalso()
    llamadas = {"real": [], "relleno": [], "fuente": []}

    # La validación y la resolución dan por buena la entrada.
    monkeypatch.setattr(rutas, "comprobar_entrada", lambda entrada: [])
    monkeypatch.setattr(rutas, "cargar_fichas", lambda: {})
    monkeypatch.setattr(rutas, "resolver", lambda entrada, fichas: (SimpleNamespace(), []))

    fuente_falsa = object()  # basta con reconocerla por identidad

    def cargar_falso(referencia):
        """Falso de cargar_fuente: anota la referencia y devuelve la fuente falsa."""
        llamadas["fuente"].append(referencia)
        return fuente_falsa

    def real_falso(*args):
        """Falso de ejecutar_run_real: anota los argumentos y devuelve una corutina que no hace nada."""
        llamadas["real"].append(args)
        return asyncio.sleep(0)

    def relleno_falso(*args):
        """Falso de ejecutar_run (relleno): anota los argumentos y devuelve una corutina que no hace nada."""
        llamadas["relleno"].append(args)
        return asyncio.sleep(0)

    monkeypatch.setattr(rutas, "cargar_fuente", cargar_falso)
    monkeypatch.setattr(rutas, "ejecutar_run_real", real_falso)
    monkeypatch.setattr(rutas, "ejecutar_run", relleno_falso)

    main.app.dependency_overrides[obtener_registro_runs] = lambda: registro
    yield SimpleNamespace(
        cliente=TestClient(main.app), registro=registro, llamadas=llamadas, fuente=fuente_falsa, monkeypatch=monkeypatch,
    )
    main.app.dependency_overrides.clear()  # no deja overrides para otras pruebas


def _con_contexto(contexto: ContextoReal) -> None:
    """Instala un contexto real como dependencia (equivale a arrancar en modo real)."""
    main.app.dependency_overrides[rutas.obtener_contexto] = lambda: contexto


def test_sin_contexto_lanza_el_relleno(entorno):
    """Modo relleno: origen de relleno, orquestador de relleno y la fuente ni se toca."""
    respuesta = entorno.cliente.post("/api/runs", json=ENTRADA)

    assert respuesta.status_code == 201
    assert respuesta.json() == {"run_id": "run_prueba", "url_eventos": "/api/runs/run_prueba/eventos"}
    assert entorno.registro.creadas[0][2] == ORIGEN_RELLENO
    assert len(entorno.llamadas["relleno"]) == 1
    assert entorno.llamadas["real"] == []
    assert entorno.llamadas["fuente"] == []  # el relleno no carga la fuente


def test_con_contexto_lanza_el_orquestador_real(entorno):
    """Modo real: origen real y el orquestador real recibe ejecución, fuente, cliente y una COPIA del kit."""
    cliente_llm = object()
    contexto = ContextoReal(cliente=cliente_llm, kit={"paleta": {"fondo": "#000000"}})
    _con_contexto(contexto)

    respuesta = entorno.cliente.post("/api/runs", json=ENTRADA)

    assert respuesta.status_code == 201
    assert entorno.registro.creadas[0][2] == ORIGEN_REAL
    assert entorno.llamadas["fuente"] == ["guia.txt"]  # carga la referencia de la entrada
    assert entorno.llamadas["relleno"] == []
    assert len(entorno.llamadas["real"]) == 1
    ejecucion, fuente, cliente, kit = entorno.llamadas["real"][0]
    assert ejecucion.run_id == "run_prueba"
    assert fuente is entorno.fuente
    assert cliente is cliente_llm
    assert kit == contexto.kit and kit is not contexto.kit  # igual en contenido, pero copia propia
    assert entorno.registro.lanzadas == 1


def test_fuente_invalida_responde_422_sin_crear_la_ejecucion(entorno):
    """Si la fuente no carga, 422 con su mensaje; no se consume un cupo ni se lanza nada."""
    _con_contexto(ContextoReal(cliente=object(), kit={"k": 1}))

    def falla(referencia):
        """Falso de cargar_fuente que rechaza la referencia."""
        raise FuenteError("no_encontrada", "No existe la fuente «guia.txt» en la carpeta del servidor.")

    entorno.monkeypatch.setattr(rutas, "cargar_fuente", falla)

    respuesta = entorno.cliente.post("/api/runs", json=ENTRADA)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"motivos": ["No existe la fuente «guia.txt» en la carpeta del servidor."]}
    assert entorno.registro.creadas == []
    assert entorno.registro.lanzadas == 0
    assert entorno.llamadas["real"] == []


def test_tope_de_runs_responde_429_en_modo_real(entorno):
    """El tope de ejecuciones sigue dando 429 con Retry-After, y no se lanza el orquestador."""
    _con_contexto(ContextoReal(cliente=object(), kit={"k": 1}))
    entorno.registro.error_al_crear = LimiteDeRuns("Hay demasiadas ejecuciones en curso.")

    respuesta = entorno.cliente.post("/api/runs", json=ENTRADA)

    assert respuesta.status_code == 429
    assert respuesta.headers["Retry-After"] == "10"
    assert entorno.registro.lanzadas == 0
    assert entorno.llamadas["real"] == []