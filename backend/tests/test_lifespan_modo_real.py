"""Pruebas del ciclo de vida de la app (lifespan de main.py) según el modo de ejecución.

El contexto real, el registro de runs y `construir_contexto` se reemplazan por falsos que anotan el ORDEN de
las llamadas: aquí solo se comprueba el cableado (qué se arma al arrancar y qué se cierra, y en qué orden, al apagar).
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.runs.contexto_real import ContextoRealError
from app.runs.registro import obtener_registro_runs


class ContextoFalso:
    """Contexto real falso: anota cuándo se cierra."""

    def __init__(self, orden: list[str]):
        self.orden = orden

    async def cerrar(self) -> None:
        """Simula el cierre del cliente HTTP y lo deja anotado."""
        self.orden.append("contexto.cerrar")


class RegistroFalso:
    """Registro falso: anota cuándo se cancelan las ejecuciones y puede fallar al hacerlo."""

    def __init__(self, orden: list[str], error: Exception | None = None):
        self.orden = orden
        self.error = error

    async def cancelar_todo(self) -> None:
        """Simula la cancelación de runs: la anota y, si se pidió, falla."""
        self.orden.append("registro.cancelar_todo")
        if self.error is not None:
            raise self.error


@pytest.fixture
def entorno(monkeypatch):
    """Prepara la app con un registro falso y devuelve lo observable: el orden y una función para fijar el modo."""
    orden: list[str] = []
    registro = RegistroFalso(orden)
    main.app.dependency_overrides[obtener_registro_runs] = lambda: registro

    def fijar_modo(modo: str) -> None:
        """Cambia MODO_RUN solo para esta prueba (main lo lee al arrancar, no al importarse)."""
        monkeypatch.setattr(main.config, "MODO_RUN", modo)

    yield SimpleEntorno(orden, registro, fijar_modo, monkeypatch)
    main.app.dependency_overrides.clear()  # no deja overrides para otras pruebas
    main.app.state.contexto = None  # ni un contexto colgado de una prueba que falló


class SimpleEntorno:
    """Agrupa lo que las pruebas necesitan del fixture."""

    def __init__(self, orden, registro, fijar_modo, monkeypatch):
        self.orden = orden
        self.registro = registro
        self.fijar_modo = fijar_modo
        self.monkeypatch = monkeypatch


def test_modo_real_arma_el_contexto_al_arrancar_y_lo_suelta_al_apagar(entorno):
    """En modo real el contexto queda en app.state mientras la app corre y vuelve a None al apagar."""
    contexto = ContextoFalso(entorno.orden)
    entorno.fijar_modo("real")
    entorno.monkeypatch.setattr(main, "construir_contexto", lambda: contexto)

    with TestClient(main.app):
        assert main.app.state.contexto is contexto  # armado durante el arranque

    assert main.app.state.contexto is None  # no queda para otra arrancada de la misma app


def test_al_apagar_se_cancelan_los_runs_antes_de_cerrar_el_cliente(entorno):
    """El cliente HTTP se cierra DESPUÉS de cancelar las ejecuciones: ninguna lo usa ya cerrado."""
    entorno.fijar_modo("real")
    entorno.monkeypatch.setattr(main, "construir_contexto", lambda: ContextoFalso(entorno.orden))

    with TestClient(main.app):
        pass

    assert entorno.orden == ["registro.cancelar_todo", "contexto.cerrar"]


def test_el_cliente_se_cierra_aunque_falle_la_cancelacion(entorno):
    """Si cancelar los runs falla, el contexto se cierra igual, el error se ve y el estado queda limpio."""
    entorno.registro.error = RuntimeError("falló la cancelación")
    entorno.fijar_modo("real")
    entorno.monkeypatch.setattr(main, "construir_contexto", lambda: ContextoFalso(entorno.orden))

    # El error del apagado no se traga: sale al salir del bloque.
    with pytest.raises(RuntimeError, match="falló la cancelación"):
        with TestClient(main.app):
            pass

    assert entorno.orden == ["registro.cancelar_todo", "contexto.cerrar"]
    assert main.app.state.contexto is None


def test_modo_relleno_no_construye_contexto(entorno):
    """En modo relleno no se construye nada, el contexto es None y al apagar solo se cancelan los runs."""
    llamadas: list[str] = []

    def no_debe_llamarse():
        """Falso de construir_contexto: si se llama en modo relleno, la prueba falla."""
        llamadas.append("construir_contexto")
        raise AssertionError("construir_contexto no debe llamarse en modo relleno")

    entorno.fijar_modo("relleno")
    entorno.monkeypatch.setattr(main, "construir_contexto", no_debe_llamarse)

    with TestClient(main.app):
        assert main.app.state.contexto is None

    assert llamadas == []
    assert entorno.orden == ["registro.cancelar_todo"]


def test_un_fallo_al_construir_el_contexto_impide_arrancar(entorno):
    """Sin clave de Groq o sin kit el servidor no arranca (error visible al inicio, no a mitad de un run)."""

    def falla():
        """Falso de construir_contexto: simula un kit de marca inexistente."""
        raise ContextoRealError("kit_no_encontrado", "No existe el kit de marca «mvp».")

    entorno.fijar_modo("real")
    entorno.monkeypatch.setattr(main, "construir_contexto", falla)

    with pytest.raises(ContextoRealError):
        with TestClient(main.app):
            pass

    assert entorno.orden == []  # no llegó a haber nada que cancelar ni que cerrar
    assert main.app.state.contexto is None


def test_una_segunda_arrancada_no_reutiliza_el_contexto_anterior(entorno):
    """Tras apagar una app en modo real, arrancarla en relleno no hereda el contexto previo."""
    entorno.fijar_modo("real")
    entorno.monkeypatch.setattr(main, "construir_contexto", lambda: ContextoFalso(entorno.orden))
    with TestClient(main.app):
        pass

    entorno.fijar_modo("relleno")
    with TestClient(main.app):
        assert main.app.state.contexto is None