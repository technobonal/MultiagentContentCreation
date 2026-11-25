"""Pruebas del ciclo de vida de la app según MODO_RUN: contexto al arrancar y cierre al apagar."""

import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.runs.registro import obtener_registro_runs


class RegistroFalso:
    """Registro mínimo: anota en `eventos` cuándo se cancelan las ejecuciones."""

    def __init__(self, eventos: list[str]):
        self.eventos = eventos

    async def cancelar_todo(self) -> None:
        """Simula la cancelación de ejecuciones al apagar."""
        self.eventos.append("cancelar_todo")


class ContextoFalso:
    """Contexto real de mentira: anota cuándo se cierra."""

    def __init__(self, eventos: list[str]):
        self.eventos = eventos

    async def cerrar(self) -> None:
        """Simula el cierre del cliente HTTP."""
        self.eventos.append("cerrar")


@pytest.fixture
def eventos():
    """Bitácora compartida y registro falso instalado; se limpia al terminar la prueba."""
    bitacora: list[str] = []
    main.app.dependency_overrides[obtener_registro_runs] = lambda: RegistroFalso(bitacora)
    yield bitacora
    main.app.dependency_overrides.pop(obtener_registro_runs, None)


def test_modo_relleno_no_construye_contexto(monkeypatch, eventos):
    """En relleno no se llama a construir_contexto y app.state.contexto es None."""
    monkeypatch.setattr(config, "MODO_RUN", "relleno")
    llamadas = []
    monkeypatch.setattr(main, "construir_contexto", lambda: llamadas.append(1))

    with TestClient(main.app):
        assert main.app.state.contexto is None

    assert llamadas == []  # nunca se construyó
    assert eventos == ["cancelar_todo"]  # y no hay nada que cerrar


def test_modo_real_guarda_el_contexto_y_lo_cierra_al_apagar(monkeypatch, eventos):
    """En real el contexto queda en app.state y se cierra DESPUÉS de cancelar las ejecuciones."""
    monkeypatch.setattr(config, "MODO_RUN", "real")
    contexto = ContextoFalso(eventos)
    monkeypatch.setattr(main, "construir_contexto", lambda: contexto)

    with TestClient(main.app):
        assert main.app.state.contexto is contexto

    assert eventos == ["cancelar_todo", "cerrar"]  # el orden importa


def test_modo_real_falla_al_arrancar_si_falta_algo(monkeypatch, eventos):
    """Si construir_contexto falla (sin clave o sin kit), la app no arranca."""
    monkeypatch.setattr(config, "MODO_RUN", "real")

    def falla():
        raise RuntimeError("falta GROQ_API_KEY")

    monkeypatch.setattr(main, "construir_contexto", falla)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        with TestClient(main.app):
            pass  # no debe llegar aquí

    assert eventos == []  # no hubo arranque, así que tampoco apagado