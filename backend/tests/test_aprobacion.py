"""Pruebas de la aprobación humana: textos vigentes y validación de la decisión. Sin red ni servidor."""

import pytest

from app.runs.aprobacion import Decision, DecisionInvalida, Edicion, textos_vigentes, validar_decision


def _campo(nombre, maximo, tipo="texto", origen="llm"):
    return {"nombre": "{{" + nombre + "}}", "tipo": tipo, "origen_valor": origen, "longitud_max": maximo}


# Ficha mínima: el slide 1 tiene título y cuerpo del redactor; el 2 solo un cta y una imagen del usuario.
FICHA = {
    "slides": [
        {"numero": 1, "campos": [_campo("titulo", 20), _campo("cuerpo", 50)]},
        {"numero": 2, "campos": [_campo("cta", 30), _campo("foto", 0, tipo="imagen", origen="usuario")]},
    ]
}


def _ev(tipo, slide, **payload):
    return {"tipo": tipo, "slide": slide, "payload": payload}


EVENTOS = [
    _ev("escribir_texto", 1, campo="titulo", texto="Salud para todos"),
    _ev("escribir_texto", 1, campo="cuerpo", texto="Un derecho de todas las personas."),
    _ev("escribir_texto", 2, campo="cta", texto="Pide tu cita"),
]


def _validar(cuerpo, eventos=EVENTOS):
    return validar_decision(cuerpo, eventos, FICHA)


def _motivos(cuerpo):
    with pytest.raises(DecisionInvalida) as e:
        _validar(cuerpo)
    return e.value.motivos


# ---------------------------- textos_vigentes ----------------------------

def test_textos_vigentes_toma_el_ultimo_escribir_texto_y_la_ultima_edicion():
    eventos = [
        _ev("escribir_texto", 1, campo="titulo", texto="Primero"),
        _ev("escribir_texto", 1, campo="titulo", texto="Corregido"),
        _ev("editada", 1, campo="titulo", texto_antes="Corregido", texto_despues="De la persona"),
        {"tipo": "run_iniciada", "payload": {}},  # sin slide: se ignora
    ]
    assert textos_vigentes(eventos) == {(1, "titulo"): "De la persona"}


# ---------------------------- decisión válida ----------------------------

def test_aprobar_sin_cambios_es_valido():
    assert _validar({}) == Decision((), None)
    assert _validar({"ediciones": [], "comentario": "  "}) == Decision((), None)


def test_una_edicion_valida_lleva_el_antes_de_lo_dibujado():
    d = _validar({"ediciones": [{"slide": 1, "campo": "titulo", "texto": "  Salud y bienestar  "}], "comentario": " Listo. "})
    assert d.ediciones == (Edicion(1, "titulo", "Salud para todos", "Salud y bienestar"),)
    assert d.comentario == "Listo."


def test_una_edicion_sin_cambio_real_se_ignora():
    d = _validar({"ediciones": [{"slide": 1, "campo": "titulo", "texto": "Salud para todos"}]})
    assert d.ediciones == ()


def test_el_antes_sigue_las_ediciones_anteriores():
    eventos = [*EVENTOS, _ev("editada", 1, campo="titulo", texto_antes="Salud para todos", texto_despues="Nuevo")]
    d = validar_decision({"ediciones": [{"slide": 1, "campo": "titulo", "texto": "Otro"}]}, eventos, FICHA)
    assert d.ediciones[0].texto_antes == "Nuevo"


# ---------------------------- decisión inválida ----------------------------

@pytest.mark.parametrize("cuerpo", [None, [], "texto", 5])
def test_el_cuerpo_debe_ser_un_objeto(cuerpo):
    assert "objeto JSON" in _motivos(cuerpo)[0]


def test_claves_desconocidas_se_rechazan():
    assert any("«aprobar»" in m for m in _motivos({"aprobar": True}))


@pytest.mark.parametrize("edicion, fragmento", [
    ({"slide": 1, "campo": "inexistente", "texto": "x"}, "no tiene un campo editable"),
    ({"slide": 9, "campo": "titulo", "texto": "x"}, "no tiene un campo editable"),
    ({"slide": 2, "campo": "foto", "texto": "x"}, "no tiene un campo editable"),  # no lo escribe el redactor
    ({"slide": True, "campo": "titulo", "texto": "x"}, "necesita"),
    ({"slide": "1", "campo": "titulo", "texto": "x"}, "necesita"),
    ({"slide": 1, "campo": "titulo"}, "necesita"),
    ({"slide": 1, "campo": "titulo", "texto": "   "}, "no puede quedar vacío"),
    ({"slide": 1, "campo": "titulo", "texto": "x" * 21}, "supera 20 caracteres (21)"),
    ("texto suelto", "debe ser un objeto"),
])
def test_ediciones_invalidas(edicion, fragmento):
    assert any(fragmento in m for m in _motivos({"ediciones": [edicion]}))


def test_el_limite_de_la_ficha_se_cumple_justo():
    d = _validar({"ediciones": [{"slide": 1, "campo": "titulo", "texto": "x" * 20}]})
    assert len(d.ediciones[0].texto_despues) == 20


def test_un_campo_repetido_se_rechaza():
    edicion = {"slide": 1, "campo": "titulo", "texto": "Uno"}
    assert any("más de una vez" in m for m in _motivos({"ediciones": [edicion, {**edicion, "texto": "Dos"}]}))


def test_se_informan_todos_los_motivos_juntos():
    motivos = _motivos({"ediciones": [{"slide": 9, "campo": "x", "texto": "y"}, {"slide": 1, "campo": "titulo", "texto": ""}], "comentario": 5})
    assert len(motivos) == 3


def test_comentario_demasiado_largo_o_no_texto():
    assert any("supera 400" in m for m in _motivos({"comentario": "x" * 401}))
    assert any("debe ser un texto" in m for m in _motivos({"comentario": 5}))


def test_ediciones_debe_ser_una_lista():
    assert any("debe ser una lista" in m for m in _motivos({"ediciones": {"slide": 1}}))
