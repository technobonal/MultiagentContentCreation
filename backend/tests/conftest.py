"""conftest.py — Los tests no esperan una decisión humana salvo que lo pidan (`esperar_aprobacion=True`)."""
import pytest

from app import config


@pytest.fixture(autouse=True)
def _sin_aprobacion_humana_por_defecto(monkeypatch):
    monkeypatch.setattr(config, "APROBACION_HUMANA", False)


@pytest.fixture(autouse=True)
def _sin_fotos_por_defecto(monkeypatch):
    """La licencia de las fotos está bloqueada por defecto: ningún test coloca una foto salvo que la libere."""
    monkeypatch.setattr(config, "FOTOS_LICENCIA", "")
