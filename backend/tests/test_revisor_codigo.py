"""Pruebas del revisor determinista: Hallazgo, con_ids, contraste WCAG, estructura, longitud y atribución/licencia."""

from types import SimpleNamespace

import pytest

from app.agentes.comun import AgenteError
from app.agentes.redactor import TextoSlide
from app.agentes.revisor_codigo import (
    MAX_HALLAZGOS,
    TEXTO_MAX,
    Hallazgo,
    comprobar_atribucion_licencia,
    comprobar_contraste,
    comprobar_estructura,
    comprobar_longitud,
    con_ids,
    crear_hallazgo,
    ordenar_hallazgos,
    razon_contraste,
    recortar_texto,
    revisar_codigo,
)


def _campo(nombre, maximo=60, obligatorio=True, origen="llm", tipo="texto"):
    """Campo de la ficha con el nombre entre llaves, como en card.json."""
    return {"nombre": "{{%s}}" % nombre, "tipo": tipo, "obligatorio": obligatorio,
            "origen_valor": origen, "longitud_max": maximo}


# Ficha mínima: gancho, un paso, cierre y fuentes (este último sin campos del LLM).
S1 = {"numero": 1, "rol": "gancho", "campos": [_campo("titulo", 20), _campo("subtitulo", 40, obligatorio=False)]}
S2 = {"numero": 2, "rol": "paso", "campos": [_campo("cuerpo", 50)]}
S3 = {"numero": 3, "rol": "cierre", "campos": [_campo("cta", 30)]}
S4 = {"numero": 4, "rol": "fuentes", "campos": [_campo("fuente_atribucion", 120, origen="usuario"),
                                                 _campo("sello_revision", 60, origen="calculado")]}


def _res(*slides):
    """Resolución mínima: solo la ficha con sus slides (por defecto, los cuatro)."""
    return SimpleNamespace(ficha={"slides": list(slides or (S1, S2, S3, S4))})


def _texto(numero, **campos):
    """TextoSlide del redactor con los campos dados (sin llaves)."""
    return TextoSlide(numero, campos, (), "m1", False)


def _textos_ok():
    """Textos válidos para los slides 1 a 3."""
    return [_texto(1, titulo="Sprints de un mes", subtitulo=""), _texto(2, cuerpo="Duran un mes."),
            _texto(3, cta="Guárdalo")]


# Kit del MVP (paleta real) y un kit con texto gris sobre fondo gris.
KIT = {"paleta": {"fondo": "#0F172A", "texto": "#F8FAFC", "acento": "#38BDF8", "texto_sobre_acento": "#0F172A"}}
KIT_MALO = {"paleta": {"fondo": "#888888", "texto": "#777777"}}
ENTRADA = {"fuente": {"atribucion": "Schwaber y Sutherland", "licencia": "CC BY-SA 4.0"}}


def _h(**cambios):
    """Hallazgo válido; `cambios` pisa campos para armar casos inválidos u ordenaciones."""
    base = dict(dimension="fidelidad", gravedad="mayor", slide=1, evidencia="e", explicacion="x",
                accion="a", responsable="redactor")
    base.update(cambios)
    return Hallazgo(**base)


# ---------------------------- recortar_texto y crear_hallazgo ----------------------------

def test_recortar_aplana_blancos_y_saltos_de_linea():
    assert recortar_texto("a\n  b\t c") == "a b c"


def test_recortar_corta_con_elipsis_en_el_tope():
    t = recortar_texto("x" * 1000)
    assert len(t) == TEXTO_MAX and t.endswith("…")
    assert recortar_texto("abcdef", 4) == "abc…"


def test_recortar_no_toca_lo_que_ya_cabe():
    assert recortar_texto("x" * TEXTO_MAX) == "x" * TEXTO_MAX


def test_crear_hallazgo_recorta_los_tres_textos():
    h = crear_hallazgo("fidelidad", "mayor", 1, "e" * 900, "x" * 900, "a" * 900, "redactor")
    assert len(h.evidencia) == len(h.explicacion) == len(h.accion) == TEXTO_MAX


# ---------------------------- Hallazgo ----------------------------

def test_hallazgo_valido_y_en_el_limite():
    assert _h(accion="x" * TEXTO_MAX).accion == "x" * TEXTO_MAX


@pytest.mark.parametrize("cambio", [
    {"dimension": "otra"},
    {"gravedad": "grave"},
    {"responsable": "humano"},
    {"slide": 0},
    {"slide": True},
    {"slide": "1"},
    {"evidencia": ""},
    {"explicacion": "   "},
    {"accion": "x" * (TEXTO_MAX + 1)},
])
def test_hallazgo_rechaza_valores_fuera_del_contrato(cambio):
    with pytest.raises(AgenteError) as e:
        _h(**cambio)
    assert e.value.codigo == "hallazgo_invalido"


# ---------------------------- ordenar_hallazgos ----------------------------

def test_orden_por_gravedad_y_luego_por_slide():
    hs = [_h(gravedad="mayor", slide=1), _h(gravedad="bloqueante", slide=3),
          _h(gravedad="bloqueante", slide=2), _h(gravedad="menor", slide=1)]
    assert [(h.gravedad, h.slide) for h in ordenar_hallazgos(hs)] == [
        ("bloqueante", 2), ("bloqueante", 3), ("mayor", 1), ("menor", 1)]


# ---------------------------- con_ids ----------------------------

def test_con_ids_numera_y_deja_el_slide_en_el_sobre():
    eventos = con_ids([_h(slide=2), _h(slide=4)])
    assert [e["payload"]["hallazgo_id"] for e in eventos] == ["h1", "h2"]
    assert [e["slide"] for e in eventos] == [2, 4]
    # El payload tiene exactamente las claves del contrato hallazgo_abierto (sin `slide`).
    assert set(eventos[0]["payload"]) == {
        "hallazgo_id", "dimension", "gravedad", "evidencia", "explicacion", "accion", "responsable"}


def test_con_ids_sigue_la_numeracion_existente():
    assert con_ids([_h()], primer_numero=5)[0]["payload"]["hallazgo_id"] == "h5"


def test_con_ids_vacio():
    assert con_ids([]) == []


def test_con_ids_respeta_el_tope_de_999():
    assert con_ids([_h()], primer_numero=MAX_HALLAZGOS)[0]["payload"]["hallazgo_id"] == "h999"
    with pytest.raises(AgenteError) as e:
        con_ids([_h(), _h()], primer_numero=MAX_HALLAZGOS)
    assert e.value.codigo == "demasiados_hallazgos"


# ---------------------------- contraste ----------------------------

def test_razon_contraste_valores_conocidos():
    assert razon_contraste("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert razon_contraste("#123456", "#123456") == pytest.approx(1.0)
    assert razon_contraste("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)  # el gris clásico que no llega a AA


def test_razon_contraste_es_simetrica():
    assert razon_contraste("#0F172A", "#F8FAFC") == pytest.approx(razon_contraste("#F8FAFC", "#0F172A"))


@pytest.mark.parametrize("malo", ["rojo", "#FFF", "#GGGGGG", "FFFFFF", None, 123])
def test_razon_contraste_color_invalido_es_error_de_kit(malo):
    with pytest.raises(AgenteError) as e:
        razon_contraste(malo, "#FFFFFF")
    assert e.value.codigo == "kit_invalido"


def test_kit_del_mvp_cumple_aa():
    assert comprobar_contraste(KIT) == []


def test_kit_con_poco_contraste_abre_un_hallazgo_para_el_director_de_arte():
    (h,) = comprobar_contraste(KIT_MALO)
    assert (h.dimension, h.gravedad, h.responsable) == ("contraste", "bloqueante", "director_arte")
    assert "#777777" in h.evidencia and "1,2" in h.evidencia  # la razón se escribe con coma decimal


def test_basta_con_un_par_declarado():
    assert comprobar_contraste({"paleta": {"fondo": "#000000", "texto": "#FFFFFF"}}) == []


def test_kit_sin_ningun_par_es_error_no_visto_bueno():
    with pytest.raises(AgenteError) as e:
        comprobar_contraste({"paleta": {"acento": "#38BDF8"}})
    assert e.value.codigo == "kit_invalido"


def test_kit_sin_paleta_es_error():
    with pytest.raises(AgenteError):
        comprobar_contraste({"nombre": "sin paleta"})


def test_color_roto_en_un_par_declarado_es_error():
    with pytest.raises(AgenteError) as e:
        comprobar_contraste({"paleta": {"fondo": "#000000", "texto": "blanco"}})
    assert e.value.codigo == "kit_invalido"


# ---------------------------- estructura ----------------------------

def test_estructura_completa_sin_hallazgos():
    assert comprobar_estructura(_res(), _textos_ok()) == []


def test_un_rol_cualquiera_cuenta_como_desarrollo():
    # En la ficha de pasos el rol es «paso», no «desarrollo»: no debe marcarse como falta.
    assert comprobar_estructura(_res(S1, S2, S3, S4), _textos_ok()) == []


def test_falta_el_gancho():
    (h,) = comprobar_estructura(_res(S2, S3, S4), [_texto(2, cuerpo="x"), _texto(3, cta="x")])
    assert (h.dimension, h.gravedad, h.responsable) == ("estructura", "bloqueante", "estratega")
    assert "gancho" in h.explicacion


def test_falta_el_desarrollo():
    (h,) = comprobar_estructura(_res(S1, S3, S4), [_texto(1, titulo="x"), _texto(3, cta="x")])
    assert "desarrollo" in h.explicacion and h.responsable == "estratega"


def test_faltan_cierre_y_fuentes():
    hs = comprobar_estructura(_res(S1, S2), [_texto(1, titulo="x"), _texto(2, cuerpo="x")])
    assert sorted("cierre" in h.explicacion or "fuentes" in h.explicacion for h in hs) == [True, True]


def test_slide_con_campos_del_llm_sin_texto_es_del_redactor():
    (h,) = comprobar_estructura(_res(), [_texto(1, titulo="x"), _texto(2, cuerpo="x")])
    assert (h.slide, h.responsable, h.gravedad) == (3, "redactor", "bloqueante")


def test_slide_de_fuentes_no_necesita_texto_del_redactor():
    # El slide 4 solo tiene valores del usuario o calculados: no se le exige texto.
    assert all(h.slide != 4 for h in comprobar_estructura(_res(), _textos_ok()))


# ---------------------------- longitud ----------------------------

def test_longitud_correcta_sin_hallazgos():
    assert comprobar_longitud(_res(), _textos_ok()) == []


def test_en_el_limite_exacto_no_hay_hallazgo():
    assert comprobar_longitud(_res(S1), [_texto(1, titulo="x" * 20)]) == []


def test_texto_demasiado_largo_es_mayor_para_el_redactor():
    (h,) = comprobar_longitud(_res(S1), [_texto(1, titulo="x" * 21)])
    assert (h.dimension, h.gravedad, h.slide, h.responsable) == ("longitud", "mayor", 1, "redactor")
    assert "21 caracteres (máximo 20)" in h.evidencia


@pytest.mark.parametrize("campos", [{"titulo": "   "}, {"titulo": ""}, {}, {"titulo": None}])
def test_campo_obligatorio_vacio_o_ausente_es_bloqueante(campos):
    (h,) = comprobar_longitud(_res(S1), [_texto(1, **campos)])
    assert (h.dimension, h.gravedad) == ("longitud", "bloqueante") and "«titulo»" in h.evidencia


def test_campo_opcional_vacio_esta_permitido():
    assert comprobar_longitud(_res(S1), [_texto(1, titulo="ok", subtitulo="")]) == []


def test_no_se_revisan_los_campos_del_usuario_ni_calculados():
    # El slide 4 tiene campos obligatorios, pero no son del LLM.
    assert comprobar_longitud(_res(S4), [_texto(4)]) == []


def test_slide_sin_texto_no_se_duplica_con_estructura():
    assert comprobar_longitud(_res(S1, S2), [_texto(1, titulo="ok")]) == []


def test_acepta_textos_con_atributo_slide_en_vez_de_numero():
    t = SimpleNamespace(slide=1, campos={"titulo": "x" * 21})
    assert len(comprobar_longitud(_res(S1), [t])) == 1


def test_nombres_con_llaves_en_el_texto_se_reconocen():
    assert len(comprobar_longitud(_res(S1), [_texto(1, **{"{{titulo}}": "x" * 21})])) == 1


# ---------------------------- atribución y licencia ----------------------------

def test_atribucion_y_licencia_presentes():
    assert comprobar_atribucion_licencia(_res(), ENTRADA) == []


def test_falta_la_licencia_en_el_slide_de_fuentes():
    (h,) = comprobar_atribucion_licencia(_res(), {"fuente": {"atribucion": "A", "licencia": ""}})
    assert (h.dimension, h.gravedad, h.slide) == ("atribucion_licencia", "bloqueante", 4)
    assert "licencia" in h.evidencia


def test_faltan_ambas():
    hs = comprobar_atribucion_licencia(_res(), {})
    assert [("atribución" in h.evidencia, "licencia" in h.evidencia) for h in hs] == [(True, False), (False, True)]


def test_en_blanco_cuenta_como_ausente():
    assert len(comprobar_atribucion_licencia(_res(), {"fuente": {"atribucion": "  ", "licencia": "CC"}})) == 1


def test_acepta_los_datos_en_la_raiz_de_la_entrada():
    assert comprobar_atribucion_licencia(_res(), {"atribucion": "A", "licencia": "CC"}) == []


def test_sin_slide_de_fuentes_se_usa_el_ultimo():
    (h,) = comprobar_atribucion_licencia(_res(S1, S2, S3), {"fuente": {"atribucion": "A"}})
    assert h.slide == 3


# ---------------------------- revisar_codigo ----------------------------

def test_todo_correcto_da_lista_vacia():
    assert revisar_codigo(_res(), KIT, _textos_ok(), ENTRADA) == []


def test_junta_las_comprobaciones_y_ordena_por_gravedad():
    textos = [_texto(1, titulo="x" * 21), _texto(2, cuerpo="ok"), _texto(3, cta="ok")]
    entrada = {"fuente": {"atribucion": "A", "licencia": ""}}
    hs = revisar_codigo(_res(), KIT_MALO, textos, entrada)
    # Bloqueantes primero (contraste en slide 1, licencia en slide 4) y después el mayor (longitud).
    assert [h.dimension for h in hs] == ["contraste", "atribucion_licencia", "longitud"]


def test_los_hallazgos_del_codigo_caben_en_el_contrato():
    hs = revisar_codigo(_res(), KIT_MALO, [_texto(1, titulo="x" * 21)], {})
    eventos = con_ids(hs)
    assert [e["payload"]["hallazgo_id"] for e in eventos] == [f"h{i}" for i in range(1, len(hs) + 1)]