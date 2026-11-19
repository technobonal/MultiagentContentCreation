"""Pruebas de app/runs/relleno.py: color de fondo y guion de relleno del paso 1.

Dos bloques:
  1. Unitarias con una ficha sintética de 3 slides (no dependen del catálogo real).
  2. Las que llevan "real" en el nombre usan la plantilla del MVP, el kit real y el validador real:
     comprueban que el guion de 6 slides son 32 eventos y que todos cumplen el contrato.
"""

import asyncio
import copy
import json

import pytest

from app import config
from app.resolution import Resolucion, cargar_fichas, resolver
from app.runs.registro import Ejecucion
from app.runs.relleno import ORIGEN_RELLENO, _texto_de_relleno, color_de_fondo, construir_guion

RUN_ID = "run_prueba01"
PLANTILLA_MVP = "ig_carrusel_pasos_oscuro_6slides"


# --------------------------------------------------------------------------------------
# Ayudas para armar datos de prueba
# --------------------------------------------------------------------------------------

def hacer_ficha(longitud_titulo: int = 30) -> dict:
    """Ficha sintética de 3 slides con los tipos de campo que distingue el relleno.

    Slide 1: un texto del LLM y una imagen. Slide 2: un texto del LLM.
    Slide 3: atribución y licencia (valores del usuario), un sello calculado y un dato ajeno a la entrada.
    """
    return {
        "id": "plantilla_prueba_3slides",
        "tipo_mensaje": "lista_de_pasos",
        "slides": [
            {"numero": 1, "rol": "gancho", "campos": [
                {"nombre": "{{titulo}}", "tipo": "texto", "origen_valor": "llm", "longitud_max": longitud_titulo},
                {"nombre": "{{imagen_producto}}", "tipo": "imagen", "origen_valor": "usuario"},
            ]},
            {"numero": 2, "rol": "desarrollo", "campos": [
                {"nombre": "{{cuerpo}}", "tipo": "texto", "origen_valor": "llm", "longitud_max": 200},
            ]},
            {"numero": 3, "rol": "fuentes", "campos": [
                {"nombre": "{{fuente_atribucion}}", "tipo": "texto", "origen_valor": "usuario", "longitud_max": 100},
                {"nombre": "{{fuente_licencia}}", "tipo": "texto", "origen_valor": "usuario", "longitud_max": 100},
                {"nombre": "{{sello_revision}}", "tipo": "texto", "origen_valor": "calculado", "longitud_max": 40},
                {"nombre": "{{otro_dato}}", "tipo": "texto", "origen_valor": "usuario", "longitud_max": 40},
            ]},
        ],
    }


def hacer_entrada() -> dict:
    """Entrada mínima con la forma que lee el relleno."""
    return {
        "fuente": {
            "tipo": "documento", "referencia": "guia.md", "idioma_salida": "es",
            "atribucion": "Autora de Prueba", "licencia": "CC BY 4.0",
        },
        "destino": {"red": "instagram", "formato": "carrusel_1080x1350"},
    }


def hacer_resolucion(modo: str = "auto", ficha: dict | None = None) -> Resolucion:
    """Resolución sobre la ficha sintética (o la dada) con el modo de plantilla pedido."""
    ficha = ficha or hacer_ficha()
    return Resolucion(ficha=ficha, plantilla_id=ficha["id"], modo_plantilla=modo, num_slides=len(ficha["slides"]))


def guion_de_prueba(modo: str = "auto", color: str = "#112233") -> list[dict]:
    """Guion completo de la ficha sintética."""
    return construir_guion(RUN_ID, hacer_entrada(), hacer_resolucion(modo), color)


def pasos_del_slide(guion: list[dict], slide: int) -> list[dict]:
    """Pasos del guion que pertenecen a un slide."""
    return [p for p in guion if p.get("slide") == slide]


# --------------------------------------------------------------------------------------
# color_de_fondo
# --------------------------------------------------------------------------------------

@pytest.fixture
def kit_de_prueba(tmp_path, monkeypatch):
    """Apunta la configuración a un kit temporal con fondo #112233 (así no se toca el kit real)."""
    (tmp_path / "kit_prueba.json").write_text(json.dumps({"paleta": {"fondo": "#112233"}}), encoding="utf-8")
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)
    monkeypatch.setattr(config, "KIT_MARCA", "kit_prueba")


def test_paleta_fija_con_roles_se_respeta_sin_leer_el_kit(tmp_path, monkeypatch):
    """Con paleta fija de cuatro roles el fondo es el del usuario; el kit ni se abre (carpeta vacía)."""
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)  # sin ningún kit dentro: leerlo daría error
    entrada = {"diseno": {"paleta": {"modo": "fijo", "valor": {
        "fondo": "#0F172A", "texto": "#F8FAFC", "acento": "#38BDF8", "texto_sobre_acento": "#0F172A",
    }}}}
    assert color_de_fondo(entrada) == "#0F172A"


def test_paleta_auto_usa_el_fondo_del_kit(kit_de_prueba):
    """Con paleta en auto el fondo sale del kit de marca configurado."""
    assert color_de_fondo({"diseno": {"paleta": {"modo": "auto"}}}) == "#112233"


def test_sin_diseno_usa_el_fondo_del_kit(kit_de_prueba):
    """Una entrada sin 'diseno' se trata como auto."""
    assert color_de_fondo({}) == "#112233"


def test_preset_de_paleta_por_nombre_todavia_usa_el_kit(kit_de_prueba):
    """Un preset por nombre no se resuelve en el paso 1: se usa el kit (documentado en el módulo)."""
    entrada = {"diseno": {"paleta": {"modo": "fijo", "valor": "preset_oscuro"}}}
    assert color_de_fondo(entrada) == "#112233"


def test_kit_inexistente_sube_el_error(tmp_path, monkeypatch):
    """Un kit que no existe es un error visible, no un color por defecto inventado."""
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)
    monkeypatch.setattr(config, "KIT_MARCA", "no_existe")
    with pytest.raises(FileNotFoundError):
        color_de_fondo({})


def test_real_el_kit_del_mvp_da_el_fondo_oscuro():
    """Con el kit real (templates/brand-kits/mvp.json) y sin paleta fija, el fondo es #0F172A."""
    assert color_de_fondo({}) == "#0F172A"


# --------------------------------------------------------------------------------------
# _texto_de_relleno
# --------------------------------------------------------------------------------------

def test_texto_de_relleno_dice_slide_y_campo():
    """El marcador identifica el slide y el campo."""
    assert _texto_de_relleno(2, "cuerpo", 200) == "Relleno · slide 2 · cuerpo"


def test_texto_de_relleno_se_recorta_a_la_longitud_maxima():
    """Nunca supera la longitud máxima del campo."""
    assert _texto_de_relleno(2, "cuerpo", 10) == "Relleno · "
    assert len(_texto_de_relleno(1, "titulo_muy_largo", 12)) == 12


# --------------------------------------------------------------------------------------
# construir_guion: estructura general
# --------------------------------------------------------------------------------------

def test_el_guion_abre_con_tres_eventos_y_cierra_con_run_finalizada():
    """Orden fijo: run_iniciada, brief_emitido, plantilla_elegida ... run_finalizada."""
    guion = guion_de_prueba()
    assert [p["tipo"] for p in guion[:3]] == ["run_iniciada", "brief_emitido", "plantilla_elegida"]
    assert guion[-1]["tipo"] == "run_finalizada"


def test_el_guion_de_la_ficha_sintetica_tiene_13_pasos():
    """3 de apertura + 3 por slide (3 slides) + 1 de cierre."""
    assert len(guion_de_prueba()) == 13


def test_cada_paso_solo_trae_las_claves_esperadas():
    """Un paso es {agente, tipo, payload} y, si es de slide, también 'slide'."""
    for paso in guion_de_prueba():  # revisa cada paso del guion
        assert {"agente", "tipo", "payload"} <= set(paso) <= {"agente", "tipo", "payload", "slide"}


def test_run_iniciada_resume_la_entrada_y_declara_la_fuente_sin_verificar():
    """El payload copia lo que dio el usuario y marca 'sin_fuente_verificada' (nada se verificó)."""
    payload = guion_de_prueba()[0]["payload"]
    assert payload == {
        "entrada_ref": RUN_ID,
        "plataforma": "instagram",
        "idioma_salida": "es",
        "num_slides": 3,
        "verificacion": "sin_fuente_verificada",
        "fuente": {"tipo": "documento", "atribucion": "Autora de Prueba", "licencia": "CC BY 4.0"},
    }


def test_brief_emitido_lleva_los_roles_de_la_ficha_en_orden():
    """El brief toma tipo de mensaje, número de slides y roles de la ficha."""
    paso = guion_de_prueba()[1]
    assert paso["agente"] == "estratega"
    assert paso["payload"]["roles"] == ["gancho", "desarrollo", "fuentes"]
    assert paso["payload"]["num_slides"] == 3
    assert paso["payload"]["tipo_mensaje"] == "lista_de_pasos"


@pytest.mark.parametrize("modo, motivo", [
    ("fijo", "Se respetó la plantilla fijada por el usuario"),
    ("auto", "Plantilla compatible del catálogo (elección de relleno, sin LLM)"),
])
def test_plantilla_elegida_explica_el_modo(modo, motivo):
    """El motivo cambia según la plantilla la haya fijado el usuario o el sistema."""
    paso = guion_de_prueba(modo=modo)[2]
    assert paso["agente"] == "director_arte"
    assert paso["payload"] == {
        "plantilla_id": "plantilla_prueba_3slides", "modo": modo, "motivo": motivo, "confianza": 1.0,
    }


def test_run_finalizada_pide_un_humano_con_sello_vacio():
    """Nada se verificó: estado requiere_humano, ledger referenciado por run_id y sello 0 de 0."""
    assert guion_de_prueba()[-1]["payload"] == {
        "estado_final": "requiere_humano",
        "fact_ledger_ref": f"{RUN_ID}/fact_ledger",
        "sello": {"afirmaciones_respaldadas": 0, "afirmaciones_totales": 0},
    }


def test_el_relleno_no_inventa_fuente_indexada_ni_aprobacion():
    """No se lee ninguna fuente (sin sha256) ni hay revisor todavía (sin aprobación)."""
    tipos = {p["tipo"] for p in guion_de_prueba()}
    assert "fuente_indexada" not in tipos
    assert "aprobacion_solicitada" not in tipos


def test_el_origen_del_relleno_es_grabado():
    """El lienzo debe mostrar la marca visible de 'grabado' en los eventos de relleno."""
    assert ORIGEN_RELLENO == "grabado"


# --------------------------------------------------------------------------------------
# construir_guion: eventos por slide
# --------------------------------------------------------------------------------------

def test_cada_slide_ordena_texto_propuesto_fondo_y_escribir_texto():
    """En un slide con texto del LLM: el redactor propone, el director coloca el fondo y escribe."""
    tipos = [p["tipo"] for p in pasos_del_slide(guion_de_prueba(), 1)]
    assert tipos == ["texto_propuesto", "colocar_fondo", "escribir_texto"]


def test_el_texto_escrito_es_el_propuesto_por_el_redactor():
    """El director de arte escribe exactamente el texto que propuso el redactor, del mismo campo."""
    propuesto, _, escrito = pasos_del_slide(guion_de_prueba(), 1)
    assert propuesto["agente"] == "redactor" and escrito["agente"] == "director_arte"
    assert propuesto["payload"] == escrito["payload"] == {"campo": "titulo", "texto": "Relleno · slide 1 · titulo"}


def test_el_texto_propuesto_respeta_la_longitud_maxima_del_campo():
    """Con longitud_max 10 el texto de relleno se recorta a 10 caracteres."""
    ficha = hacer_ficha(longitud_titulo=10)
    guion = construir_guion(RUN_ID, hacer_entrada(), hacer_resolucion(ficha=ficha), "#112233")
    propuesto = pasos_del_slide(guion, 1)[0]
    assert len(propuesto["payload"]["texto"]) == 10


def test_los_campos_de_imagen_y_los_calculados_no_generan_eventos():
    """La imagen (paso 3) y el sello (lo calcula código) no se escriben en el relleno."""
    campos = {p["payload"].get("campo") for p in guion_de_prueba() if "campo" in p["payload"]}
    assert "imagen_producto" not in campos
    assert "sello_revision" not in campos


def test_los_valores_del_usuario_se_escriben_sin_pasar_por_el_redactor():
    """Atribución y licencia salen tal cual de la entrada: solo escribir_texto, sin texto_propuesto."""
    pasos = pasos_del_slide(guion_de_prueba(), 3)
    assert [p["tipo"] for p in pasos] == ["colocar_fondo", "escribir_texto", "escribir_texto"]
    assert [p["payload"] for p in pasos[1:]] == [
        {"campo": "fuente_atribucion", "texto": "Autora de Prueba"},
        {"campo": "fuente_licencia", "texto": "CC BY 4.0"},
    ]


def test_un_campo_ajeno_a_la_entrada_y_sin_llm_se_ignora():
    """'otro_dato' no es del LLM ni un valor conocido del usuario: no se inventa su texto."""
    campos = {p["payload"].get("campo") for p in guion_de_prueba()}
    assert "otro_dato" not in campos


def test_cada_slide_recibe_su_fondo_de_color():
    """Un colocar_fondo por slide, de tipo color y con el color recibido."""
    fondos = [p for p in guion_de_prueba(color="#ABCDEF") if p["tipo"] == "colocar_fondo"]
    assert [p["slide"] for p in fondos] == [1, 2, 3]
    for paso in fondos:  # todos con el mismo color pedido
        assert paso["payload"] == {"fondo": {"tipo": "color", "valor": "#ABCDEF"}}


def test_los_pasos_de_slide_llevan_el_numero_de_su_slide_en_orden():
    """Los pasos de slide avanzan 1, 2, 3 sin volver atrás."""
    numeros = [p["slide"] for p in guion_de_prueba() if "slide" in p]
    assert numeros == sorted(numeros) and set(numeros) == {1, 2, 3}


def test_construir_guion_es_puro():
    """Mismo input, mismo guion, y la entrada no se modifica."""
    entrada = hacer_entrada()
    copia = copy.deepcopy(entrada)
    resolucion = hacer_resolucion()
    primero = construir_guion(RUN_ID, entrada, resolucion, "#112233")
    segundo = construir_guion(RUN_ID, entrada, resolucion, "#112233")
    assert primero == segundo
    assert entrada == copia


# --------------------------------------------------------------------------------------
# Con la plantilla, el kit y el validador reales
# --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def guion_real():
    """Entrada mínima real resuelta contra el catálogo real, con su guion de relleno y su resolución."""
    ruta = config.CONTRATOS_DIR / "input" / "examples" / "valido_minimo_todo_auto.json"
    with open(ruta, encoding="utf-8") as f:
        entrada = json.load(f)
    entrada.pop("$comment", None)  # el esquema no declara el comentario raíz
    resolucion, errores = resolver(entrada, cargar_fichas())
    assert errores == []
    return construir_guion("run_real_relleno", entrada, resolucion, color_de_fondo(entrada)), resolucion, entrada


def test_real_el_guion_de_la_plantilla_de_6_slides_son_32_eventos(guion_real):
    """La plantilla del MVP produce el guion de 32 eventos (unos 19 s al ritmo de 0,6 s)."""
    guion, resolucion, _ = guion_real
    assert resolucion.plantilla_id == PLANTILLA_MVP
    assert len(guion) == 32


def test_real_todo_el_guion_cumple_el_contrato(guion_real):
    """Cada paso, emitido como evento real, pasa el validador del contrato; el seq sale 1..32."""
    guion, resolucion, entrada = guion_real

    async def escenario():
        ejecucion = Ejecucion("run_real_relleno", entrada, resolucion, ORIGEN_RELLENO)
        for paso in guion:  # cada paso pasa por emitir, que valida contra el esquema real
            await ejecucion.emitir(paso["agente"], paso["tipo"], paso["payload"], slide=paso.get("slide"))
        return ejecucion

    ejecucion = asyncio.run(escenario())  # un EventoInvalido haría fallar la prueba con sus motivos
    assert [e["seq"] for e in ejecucion.eventos] == list(range(1, 33))
    assert {e["origen"] for e in ejecucion.eventos} == {"grabado"}