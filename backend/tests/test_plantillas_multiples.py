"""Varias plantillas en el catálogo: la de por defecto gana en modo auto y cada slide puede declarar su fondo."""
import pytest

from app import config
from app.agentes.director_arte import componer_slide
from app.resolution import cargar_fichas, resolver

KIT = {"paleta": {"fondo": "#112233"}}
OSCURO = "ig_carrusel_pasos_oscuro_6slides"


def ficha(pid):
    return {"id": pid, "plataforma": "instagram", "formato": "carrusel_1080x1350", "idiomas": ["es"],
            "tipo_mensaje": "lista_de_pasos", "slides": [{"numero": n, "campos": []} for n in range(1, 7)]}


ENTRADA = {"destino": {"red": "instagram", "formato": "carrusel_1080x1350"}, "fuente": {"idioma_salida": "es"}}


def test_en_auto_gana_la_plantilla_por_defecto_aunque_otra_vaya_antes_por_orden():
    fichas = {p: ficha(p) for p in ("aaaaa_primera", OSCURO)}
    resolucion, errores = resolver(ENTRADA, fichas)
    assert errores == [] and resolucion.plantilla_id == OSCURO and resolucion.modo_plantilla == "auto"


def test_si_la_de_por_defecto_no_esta_gana_la_primera_compatible_por_id(monkeypatch):
    monkeypatch.setattr(config, "PLANTILLA_POR_DEFECTO", "no_existe")
    resolucion, _ = resolver(ENTRADA, {p: ficha(p) for p in ("bbbbb_b", "aaaaa_a")})
    assert resolucion.plantilla_id == "aaaaa_a"


def test_con_el_catalogo_real_el_modo_auto_sigue_eligiendo_la_plantilla_de_siempre():
    assert config.PLANTILLA_POR_DEFECTO == OSCURO and OSCURO in cargar_fichas()


@pytest.mark.parametrize("fondo, esperado", [("#3B49DF", "#3B49DF"), (None, "#112233")])
def test_el_director_de_arte_usa_el_fondo_del_slide_o_el_del_kit(fondo, esperado):
    slide = {"numero": 1, "campos": []} | ({"fondo": fondo} if fondo else {})
    [evento] = componer_slide(slide, KIT, None)
    assert evento.payload == {"fondo": {"tipo": "color", "valor": esperado}}
