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


@pytest.fixture(autouse=True)
def _sin_pausa_entre_fotos(monkeypatch):
    """Los tests no esperan entre foto y foto (salvo el que prueba la pausa, que la fija a mano)."""
    monkeypatch.setattr(config, "FOTOS_PAUSA_SEG", 0.0)


@pytest.fixture(autouse=True)
def _sin_escribir_en_el_registro_real(tmp_path, monkeypatch):
    """Ningún test toca el registro de rechazos de la persona: de ahí van a aprender los agentes."""
    monkeypatch.setattr(config, "RECHAZOS_ARCHIVO", tmp_path / "rechazos.jsonl")
