"""Pruebas del reintento del redactor ante una respuesta vacía o cortada (`_pedir_redaccion`)."""

import asyncio

import pytest

from app.agentes import redactor
from app.agentes.comun import AgenteError


def _correr(corutina):
    """Ejecuta una corutina desde una prueba síncrona."""
    return asyncio.run(corutina)


def _pedir_falso(resultados: list):
    """Falso de `pedir_json`: devuelve o lanza, en orden, lo que haya en `resultados`; anota las temperaturas."""
    temperaturas: list[float] = []

    async def falso(cliente, rol, mensajes, validar, **kw):
        """Consume el siguiente resultado: una excepción se lanza y cualquier otro valor se devuelve."""
        temperaturas.append(kw["temperatura"])
        siguiente = resultados.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente

    return falso, temperaturas


def _truncada() -> AgenteError:
    """Error de respuesta vacía o cortada, como el que lanza `pedir_json`."""
    return AgenteError("salida_truncada", "La respuesta del modelo se cortó o llegó vacía.")


def test_reintenta_una_vez_y_sube_la_temperatura(monkeypatch):
    """Si el primer intento llega vacío, el segundo sale bien y usa la temperatura de reintento."""
    falso, temperaturas = _pedir_falso([_truncada(), ({"campos": {}}, "respuesta")])
    monkeypatch.setattr(redactor, "pedir_json", falso)

    dato, resp = _correr(redactor._pedir_redaccion(object(), [], lambda d: []))

    assert (dato, resp) == ({"campos": {}}, "respuesta")
    assert temperaturas == [redactor.TEMPERATURA_REDACTOR, redactor.TEMPERATURA_REINTENTO]


def test_falla_si_el_reintento_tambien_llega_vacio(monkeypatch):
    """Agotado el reintento, el error de salida truncada se propaga (no hay un tercer intento)."""
    falso, temperaturas = _pedir_falso([_truncada(), _truncada()])
    monkeypatch.setattr(redactor, "pedir_json", falso)

    with pytest.raises(AgenteError) as info:
        _correr(redactor._pedir_redaccion(object(), [], lambda d: []))

    assert info.value.codigo == "salida_truncada"
    assert len(temperaturas) == 1 + redactor.REINTENTOS_SALIDA_TRUNCADA


def test_otros_errores_no_se_reintentan(monkeypatch):
    """Un JSON inválido (u otro error) se propaga de inmediato, sin repetir la llamada."""
    falso, temperaturas = _pedir_falso([AgenteError("salida_invalida", "no es JSON")])
    monkeypatch.setattr(redactor, "pedir_json", falso)

    with pytest.raises(AgenteError) as info:
        _correr(redactor._pedir_redaccion(object(), [], lambda d: []))

    assert info.value.codigo == "salida_invalida"
    assert temperaturas == [redactor.TEMPERATURA_REDACTOR]  # una sola llamada


def test_a_la_primera_no_reintenta(monkeypatch):
    """Con una respuesta buena a la primera, hay una sola llamada y con la temperatura normal."""
    falso, temperaturas = _pedir_falso([({"campos": {}}, "ok")])
    monkeypatch.setattr(redactor, "pedir_json", falso)

    _correr(redactor._pedir_redaccion(object(), [], lambda d: []))

    assert temperaturas == [redactor.TEMPERATURA_REDACTOR]