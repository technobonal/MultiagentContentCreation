"""Pruebas del director de arte: fondo desde el kit, textos desde el redactor, orden y errores del contrato."""

import copy
from types import SimpleNamespace

import pytest

from app.agentes.comun import AgenteError
from app.agentes.director_arte import (
    AGENTE,
    TEXTO_MAX_CONTRATO,
    EventoArte,
    componer_carrusel,
    componer_slide,
    payload_fondo,
)
from app.agentes.redactor import TextoSlide

# Kit de marca del MVP (solo la paleta importa aquí; el resto va para que el kit sea realista).
KIT = {
    "nombre": "MVP MultiagentContentCreation",
    "version": "0.1.0",
    "paleta": {"fondo": "#0F172A", "texto": "#F8FAFC", "acento": "#38BDF8", "texto_sobre_acento": "#0F172A"},
}


def _campo(nombre, origen="llm", tipo="texto", maximo=60):
    """Campo de ficha mínimo con las claves que lee el módulo."""
    return {"nombre": "{{%s}}" % nombre, "tipo": tipo, "obligatorio": True, "origen_valor": origen, "longitud_max": maximo}


# Tres slides: gancho (dos campos del LLM), desarrollo (uno) y fuentes (solo usuario o calculado).
SLIDES = [
    {"numero": 1, "rol": "gancho", "campos": [_campo("titulo"), _campo("subtitulo", maximo=120)]},
    {"numero": 2, "rol": "desarrollo", "campos": [_campo("titulo"), _campo("cuerpo", maximo=220),
                                                  _campo("imagen_producto", origen="usuario", tipo="imagen")]},
    {"numero": 3, "rol": "fuentes", "campos": [_campo("fuente_atribucion", origen="usuario"),
                                                 _campo("sello_revision", origen="calculado")]},
]
RESOLUCION = SimpleNamespace(num_slides=3, ficha={"tipo_mensaje": "lista_de_pasos", "slides": SLIDES})


def _texto(numero, **campos) -> TextoSlide:
    """TextoSlide del redactor con los campos dados (el resto de datos no influye en el director)."""
    return TextoSlide(numero=numero, campos=campos, hechos=(), modelo="m1", fallback=False)


# ---------------------------- payload_fondo ----------------------------

def test_fondo_usa_el_color_de_la_paleta():
    assert payload_fondo(KIT) == {"fondo": {"tipo": "color", "valor": "#0F172A"}}


@pytest.mark.parametrize("kit", [
    {},
    {"paleta": {}},
    {"paleta": {"fondo": "rojo"}},
    {"paleta": {"fondo": "#12345"}},
    {"paleta": {"fondo": "#0F172A\n"}},  # un salto de línea final no es un color válido
    {"paleta": {"fondo": 5}},
    {"paleta": "oscura"},
    None,
])
def test_fondo_rechaza_kit_sin_color_valido(kit):
    with pytest.raises(AgenteError) as e:
        payload_fondo(kit)
    assert e.value.codigo == "kit_invalido"


# ---------------------------- componer_slide ----------------------------

def test_slide_con_texto_pone_primero_el_fondo_y_luego_los_campos_en_orden():
    ev = componer_slide(SLIDES[0], KIT, _texto(1, titulo="Sprints de un mes", subtitulo="Cómo funcionan"))
    assert [e.tipo for e in ev] == ["colocar_fondo", "escribir_texto", "escribir_texto"]
    assert [e.payload.get("campo") for e in ev[1:]] == ["titulo", "subtitulo"]
    assert ev[1].payload == {"campo": "titulo", "texto": "Sprints de un mes"}
    assert all(e.slide == 1 and e.agente == AGENTE == "director_arte" for e in ev)


def test_slide_sin_texto_solo_coloca_el_fondo():
    assert componer_slide(SLIDES[0], KIT, None) == [EventoArte("colocar_fondo", 1, payload_fondo(KIT))]


def test_slide_de_fuentes_con_redaccion_vacia_solo_coloca_el_fondo():
    # El redactor devuelve un TextoSlide sin campos para el slide de fuentes.
    ev = componer_slide(SLIDES[2], KIT, _texto(3))
    assert [e.tipo for e in ev] == ["colocar_fondo"]


def test_el_texto_se_limpia_de_espacios():
    ev = componer_slide(SLIDES[0], KIT, _texto(1, titulo="  Hola  "))
    assert ev[1].payload["texto"] == "Hola"


@pytest.mark.parametrize("campo", ["fuente_atribucion", "imagen_producto", "inventado"])
def test_campo_que_no_es_del_redactor_se_rechaza(campo):
    # Atribución (usuario), imagen (usuario) o un nombre que la ficha no tiene.
    with pytest.raises(AgenteError) as e:
        componer_slide(SLIDES[1] if campo == "imagen_producto" else SLIDES[2] if campo == "fuente_atribucion" else SLIDES[0],
                       KIT, _texto(1, **{campo: "x"}))
    assert e.value.codigo == "campo_desconocido"


@pytest.mark.parametrize("valor", ["", "   ", "x" * (TEXTO_MAX_CONTRATO + 1), 7, None])
def test_texto_vacio_largo_o_no_textual_se_rechaza(valor):
    with pytest.raises(AgenteError) as e:
        componer_slide(SLIDES[0], KIT, _texto(1, titulo=valor))
    assert e.value.codigo == "texto_invalido"


def test_texto_en_el_limite_exacto_del_contrato_se_acepta():
    ev = componer_slide(SLIDES[0], KIT, _texto(1, titulo="x" * TEXTO_MAX_CONTRATO))
    assert len(ev[1].payload["texto"]) == TEXTO_MAX_CONTRATO


def test_kit_invalido_falla_aunque_no_haya_texto():
    with pytest.raises(AgenteError) as e:
        componer_slide(SLIDES[0], {}, None)
    assert e.value.codigo == "kit_invalido"


# ---------------------------- componer_carrusel ----------------------------

def test_carrusel_un_fondo_por_slide_y_textos_en_su_slide():
    textos = {1: _texto(1, titulo="A", subtitulo="B"), 2: _texto(2, titulo="C", cuerpo="D"), 3: _texto(3)}
    ev = componer_carrusel(RESOLUCION, KIT, textos)
    # Slide por slide: fondo y luego sus textos.
    assert [(e.slide, e.tipo) for e in ev] == [
        (1, "colocar_fondo"), (1, "escribir_texto"), (1, "escribir_texto"),
        (2, "colocar_fondo"), (2, "escribir_texto"), (2, "escribir_texto"),
        (3, "colocar_fondo"),
    ]


def test_carrusel_sin_textos_todavia_solo_trae_los_fondos():
    ev = componer_carrusel(RESOLUCION, KIT, {})
    assert [(e.slide, e.tipo) for e in ev] == [(1, "colocar_fondo"), (2, "colocar_fondo"), (3, "colocar_fondo")]


def test_carrusel_con_redaccion_parcial_dibuja_solo_lo_que_hay():
    ev = componer_carrusel(RESOLUCION, KIT, {1: _texto(1, titulo="A")})
    assert sum(e.tipo == "escribir_texto" for e in ev) == 1 and sum(e.tipo == "colocar_fondo" for e in ev) == 3


def test_carrusel_con_slide_que_la_ficha_no_tiene_falla():
    with pytest.raises(AgenteError) as e:
        componer_carrusel(RESOLUCION, KIT, {9: _texto(9, titulo="A")})
    assert e.value.codigo == "slide_desconocido"


def test_no_modifica_el_kit_ni_la_redaccion():
    kit, textos = copy.deepcopy(KIT), {1: _texto(1, titulo=" A ")}
    componer_carrusel(RESOLUCION, kit, textos)
    assert kit == KIT and textos[1].campos == {"titulo": " A "}  # el texto original no se toca


def test_los_eventos_son_inmutables():
    ev = componer_slide(SLIDES[0], KIT, None)[0]
    with pytest.raises(Exception):  # FrozenInstanceError
        ev.slide = 5