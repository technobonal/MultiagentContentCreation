"""Pruebas del redactor: campos, mensajes, validación (incluida la cita literal) y redactar_slide con cliente falso.

Incluye el degradado de citas: en el último intento una cita que no es literal se descarta
(con aviso en el log) en vez de abortar el run; los errores de estructura siguen abortando.
"""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.agentes.cliente_llm import RespuestaLLM
from app.agentes.comun import AgenteError
from app.agentes.estratega import Brief
from app.agentes.redactor import (
    HECHO_MAX_CHARS,
    MAX_HECHOS,
    MAX_TOKENS_REDACTOR,
    TextoSlide,
    campos_del_redactor,
    construir_mensajes,
    redactar_slide,
    validar_redaccion,
)

# Entrada mínima: solo los campos que lee el redactor.
ENTRADA = {"destino": {"red": "linkedin"}, "fuente": {"idioma_salida": "es"}}

# Fuente sintética de dos fragmentos (el segundo empieza tras una línea en blanco).
P0 = "El Sprint dura un mes como máximo. El equipo tiene 10 personas o menos."
P1 = "El Product Owner ordena el Product Backlog.\nEl Scrum Master ayuda al equipo."
TEXTO = P0 + "\n\n" + P1
INICIO_P1 = len(P0) + 2
FRAGMENTOS = (
    SimpleNamespace(indice=0, texto=P0, inicio=0),
    SimpleNamespace(indice=1, texto=P1, inicio=INICIO_P1),
)
FUENTE = SimpleNamespace(fragmentos=FRAGMENTOS)

# Slide 1: dos campos de texto del LLM y una imagen del usuario. Slide 2: solo valores del usuario o calculados.
SLIDE_GANCHO = {
    "numero": 1,
    "rol": "gancho",
    "campos": [
        {"nombre": "{{titulo}}", "tipo": "texto", "obligatorio": True, "origen_valor": "llm", "longitud_max": 60},
        {"nombre": "{{cuerpo}}", "tipo": "texto", "obligatorio": True, "origen_valor": "llm", "longitud_max": 160},
        {"nombre": "{{imagen_producto}}", "tipo": "imagen", "obligatorio": False, "origen_valor": "usuario"},
    ],
}
SLIDE_FUENTES = {
    "numero": 2,
    "rol": "fuentes",
    "campos": [
        {"nombre": "{{fuente_atribucion}}", "tipo": "texto", "obligatorio": True, "origen_valor": "usuario", "longitud_max": 120},
        {"nombre": "{{sello_revision}}", "tipo": "texto", "obligatorio": True, "origen_valor": "calculado", "longitud_max": 60},
    ],
}
RESOLUCION = SimpleNamespace(
    num_slides=2, ficha={"tipo_mensaje": "lista_de_pasos", "slides": [SLIDE_GANCHO, SLIDE_FUENTES]}
)
CAMPOS = campos_del_redactor(SLIDE_GANCHO)  # [("titulo", 60), ("cuerpo", 160)]


def _brief(asignados=None) -> Brief:
    """Brief mínimo: el slide 1 apunta a los fragmentos indicados (por defecto, solo el 0)."""
    return Brief(
        angulo="idea central", tono="didáctico",
        fragmentos_por_slide={1: asignados if asignados is not None else (0,)},
        modelo="m1", fallback=False,
    )


def _resp(**cambios) -> str:
    """Respuesta válida del redactor; `cambios` pisa claves de primer nivel para armar casos inválidos."""
    base = {
        "campos": {"titulo": "Sprints de un mes", "cuerpo": "Duran un mes como máximo."},
        "hechos": ["El Sprint dura un mes como máximo."],
    }
    base.update(cambios)
    return json.dumps(base)


class ClienteFalso:
    """Respuestas guionadas; registra el rol, los mensajes y los parámetros de cada llamada."""

    def __init__(self, respuestas, modelo="m1", fallback=False):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []
        self.modelo, self.fallback = modelo, fallback

    async def completar(self, rol, mensajes, **kw):
        self.llamadas.append({"rol": rol, "mensajes": mensajes, **kw})
        item = self.respuestas.pop(0)
        texto, motivo = item if isinstance(item, tuple) else (item, "stop")
        return RespuestaLLM(texto, self.modelo, "m1", self.fallback, motivo, None, 0.0)


def _redactar(cliente, numero=1, brief=None):
    return asyncio.run(redactar_slide(cliente, ENTRADA, RESOLUCION, FUENTE, brief or _brief(), numero))


def _validar(dato):
    return validar_redaccion(dato, CAMPOS, FRAGMENTOS)


# ---------------------------- campos_del_redactor ----------------------------

def test_campos_solo_texto_del_llm_sin_llaves_y_con_su_limite():
    assert CAMPOS == [("titulo", 60), ("cuerpo", 160)]  # la imagen del usuario no entra


def test_slide_sin_campos_del_llm_da_lista_vacia():
    assert campos_del_redactor(SLIDE_FUENTES) == []


# ---------------------------- construir_mensajes ----------------------------

def test_mensajes_prompt_fijo_primero_y_variable_al_final():
    m = construir_mensajes(ENTRADA, _brief(), SLIDE_GANCHO, CAMPOS, [FRAGMENTOS[0]])
    assert [x["role"] for x in m] == ["system", "user"]
    # Nada variable en el prefijo fijo (el que cachea Groq): ni ángulo ni fragmentos.
    assert "idea central" not in m[0]["content"] and P0 not in m[0]["content"]
    assert "idea central" in m[1]["content"] and P0 in m[1]["content"]


def test_mensaje_de_usuario_lista_campos_limites_y_fragmentos_numerados():
    u = construir_mensajes(ENTRADA, _brief(), SLIDE_GANCHO, CAMPOS, list(FRAGMENTOS))[1]["content"]
    assert "- titulo (máximo 60 caracteres)" in u and "- cuerpo (máximo 160 caracteres)" in u
    assert "[Fragmento 0]" in u and "[Fragmento 1]" in u
    assert "Idioma de salida: es" in u and "rol: gancho" in u


def test_prompt_del_redactor_explica_como_copiar_las_citas():
    """El prompt fijo trae la regla de copia exacta y los comentarios HTML no llegan al modelo."""
    prompt = construir_mensajes(ENTRADA, _brief(), SLIDE_GANCHO, CAMPOS, [FRAGMENTOS[0]])[0]["content"]
    assert "Cómo copiar bien una cita" in prompt and "<!--" not in prompt


# ---------------------------- validar_redaccion ----------------------------

def test_validar_redaccion_correcta():
    assert _validar(json.loads(_resp())) == []


def test_validar_no_objeto():
    assert _validar(["no", "objeto"]) == ["la respuesta debe ser un objeto JSON"]


def test_validar_acepta_cita_con_salto_de_linea_aplanado():
    hecho = "El Product Owner ordena el Product Backlog. El Scrum Master ayuda al equipo."
    assert _validar(json.loads(_resp(hechos=[hecho]))) == []


@pytest.mark.parametrize("cambio, fragmento_motivo", [
    ({"campos": "texto"}, "'campos' debe ser un objeto"),
    ({"campos": {"titulo": "x"}}, "exactamente estas claves"),                           # falta 'cuerpo'
    ({"campos": {"titulo": "x", "cuerpo": "y", "extra": "z"}}, "exactamente estas claves"),
    ({"campos": {"titulo": "   ", "cuerpo": "y"}}, "no vacío"),
    ({"campos": {"titulo": 5, "cuerpo": "y"}}, "no vacío"),
    ({"campos": {"titulo": "x" * 61, "cuerpo": "y"}}, "supera 60"),
    ({"hechos": "no es lista"}, "lista de textos"),
    ({"hechos": [1]}, "lista de textos"),
    ({"hechos": None}, "lista de textos"),
    ({"hechos": ["El Sprint dura un mes como máximo."] * (MAX_HECHOS + 1)}, f"el máximo es {MAX_HECHOS}"),
    ({"hechos": ["a" * (HECHO_MAX_CHARS + 1)]}, f"más de {HECHO_MAX_CHARS}"),
    ({"hechos": ["El Sprint dura dos meses."]}, "no aparece literal"),
])
def test_validar_rechaza(cambio, fragmento_motivo):
    motivos = _validar({**json.loads(_resp()), **cambio})
    assert any(fragmento_motivo in m for m in motivos), motivos


def test_validar_informa_cada_cita_inventada_por_separado():
    motivos = _validar(json.loads(_resp(hechos=["inventado uno", "inventado dos"])))
    assert sum("no aparece literal" in m for m in motivos) == 2


def test_validar_rechaza_cita_con_la_mayuscula_cambiada():
    """Caso real: el modelo «arregla» el inicio de la cita (aquí baja la mayúscula) y deja de ser literal."""
    motivos = _validar(json.loads(_resp(hechos=["el Product Owner ordena el Product Backlog."])))
    assert any("no aparece literal" in m for m in motivos), motivos


# ---------------------------- validar_redaccion: modo tolerante (último intento) ----------------------------

def test_validar_tolerante_no_rechaza_citas_no_literales():
    """En modo tolerante una cita inventada ya no es motivo de rechazo (se descartará al ubicarla)."""
    dato = json.loads(_resp(hechos=["El Sprint dura dos meses.", "inventada"]))
    assert validar_redaccion(dato, CAMPOS, FRAGMENTOS, exigir_citas=False) == []
    # Y el modo estricto (el de por defecto) sigue rechazándolas.
    assert any("no aparece literal" in m for m in _validar(dato))


@pytest.mark.parametrize("cambio, fragmento_motivo", [
    ({"campos": {"titulo": "x"}}, "exactamente estas claves"),
    ({"hechos": "no es lista"}, "lista de textos"),
    ({"hechos": ["El Sprint dura un mes como máximo."] * (MAX_HECHOS + 1)}, f"el máximo es {MAX_HECHOS}"),
])
def test_validar_tolerante_sigue_exigiendo_la_estructura(cambio, fragmento_motivo):
    """El modo tolerante perdona las citas y el exceso de longitud (se recorta): claves, tipos y cantidad se exigen siempre."""
    motivos = validar_redaccion({**json.loads(_resp()), **cambio}, CAMPOS, FRAGMENTOS, exigir_citas=False)
    assert any(fragmento_motivo in m for m in motivos), motivos


def test_cita_demasiado_larga_se_rechaza_en_modo_estricto_y_se_perdona_en_el_tolerante():
    dato = {**json.loads(_resp()), "hechos": ["a" * (HECHO_MAX_CHARS + 1)]}
    assert any(f"más de {HECHO_MAX_CHARS}" in m for m in _validar(dato))
    assert validar_redaccion(dato, CAMPOS, FRAGMENTOS, exigir_citas=False) == []


# ---------------------------- redactar_slide ----------------------------

def test_redacta_a_la_primera_y_ubica_los_hechos():
    c = ClienteFalso([_resp(campos={"titulo": "  Sprints de un mes  ", "cuerpo": "Duran un mes."})])
    r = _redactar(c)
    assert r.numero == 1 and r.campos == {"titulo": "Sprints de un mes", "cuerpo": "Duran un mes."}  # sin espacios sobrantes
    assert len(r.hechos) == 1 and TEXTO[r.hechos[0].inicio:r.hechos[0].fin] == r.hechos[0].texto
    llamada = c.llamadas[0]
    assert llamada["rol"] == "redactor" and llamada["max_tokens"] == MAX_TOKENS_REDACTOR
    assert llamada["permitir_fallback"] is True


def test_posicion_absoluta_cuando_el_hecho_esta_en_el_segundo_fragmento():
    c = ClienteFalso([_resp(hechos=["El Scrum Master ayuda al equipo."])])
    h = _redactar(c, brief=_brief((1,))).hechos[0]
    assert h.fragmento == 1 and h.inicio >= INICIO_P1 and TEXTO[h.inicio:h.fin] == h.texto


def test_solo_los_fragmentos_asignados_llegan_al_prompt():
    c = ClienteFalso([_resp()])
    _redactar(c, brief=_brief((0,)))
    usuario = c.llamadas[0]["mensajes"][1]["content"]
    assert "El Sprint dura" in usuario and "Product Owner" not in usuario


def test_slide_sin_campos_no_llama_al_modelo():
    c = ClienteFalso([])
    r = _redactar(c, numero=2)  # el brief ni siquiera asigna fragmentos al slide 2
    assert r == TextoSlide(2, {}, (), "", False) and c.llamadas == []


def test_una_cita_inventada_no_provoca_reintento_y_se_descarta():
    """Reintentar por una cita cuesta ~1.500 tokens y nada aguas abajo usa las citas del redactor: se descarta."""
    c = ClienteFalso([_resp(hechos=["El Sprint dura dos meses."])])
    r = _redactar(c)
    assert len(c.llamadas) == 1
    assert r.hechos == () and r.campos["titulo"] == "Sprints de un mes"  # cita descartada, texto intacto


def test_se_conservan_solo_las_citas_literales_en_una_sola_llamada():
    buena = "El Sprint dura un mes como máximo."
    c = ClienteFalso([_resp(hechos=["inventada", buena])])
    r = _redactar(c)
    assert len(c.llamadas) == 1
    assert [h.texto for h in r.hechos] == [buena]  # la mala se descarta y la buena queda ubicada


def test_una_cita_demasiado_larga_no_provoca_reintento_y_se_descarta(caplog):
    """Con una fuente larga (PDF) el modelo copia pasajes enteros: la cita larga se descarta, el slide se conserva."""
    buena = "El Sprint dura un mes como máximo."
    larga = "x" * (HECHO_MAX_CHARS + 1)
    c = ClienteFalso([_resp(hechos=[larga, buena])])
    with caplog.at_level(logging.WARNING, logger="app.agentes.redactor"):
        r = _redactar(c)
    assert len(c.llamadas) == 1
    assert [h.texto for h in r.hechos] == [buena] and r.campos["titulo"] == "Sprints de un mes"
    assert "descartada" in caplog.text


def test_el_reintento_por_longitud_no_menciona_las_citas():
    """Si hay que reintentar por longitud, el motivo que recibe el modelo no le pide corregir citas."""
    c = ClienteFalso([_resp(campos={"titulo": "x" * 66, "cuerpo": "y"}, hechos=["inventada"]), _resp()])
    _redactar(c)
    motivo = c.llamadas[1]["mensajes"][-1]["content"]
    assert "supera 60" in motivo and "no aparece literal" not in motivo


def test_cita_descartada_deja_aviso_en_el_log(caplog):
    c = ClienteFalso([_resp(hechos=["inventada"])])
    with caplog.at_level(logging.WARNING, logger="app.agentes.redactor"):
        _redactar(c)
    # El aviso dice qué slide y qué cita se descartó, para poder revisarlo en el log del servidor.
    assert "descartada" in caplog.text and "inventada" in caplog.text and "slide 1" in caplog.text


def test_reintento_tras_json_roto():
    c = ClienteFalso(['{"campos"', _resp()])
    assert _redactar(c).campos["titulo"] == "Sprints de un mes" and len(c.llamadas) == 2


def test_salida_truncada_falla_tras_un_reintento():
    # Dos respuestas cortadas: el intento inicial y su único reintento.
    c = ClienteFalso([(_resp()[:30], "length"), (_resp()[:30], "length")])
    with pytest.raises(AgenteError) as e:
        _redactar(c)
    assert e.value.codigo == "salida_truncada" and len(c.llamadas) == 2


def test_salida_invalida_tras_agotar_reintentos():
    """La estructura inválida sigue abortando el run aunque el último intento sea tolerante con las citas."""
    mala = json.dumps({"campos": {}, "hechos": []})
    c = ClienteFalso([mala, mala])
    with pytest.raises(AgenteError) as e:
        _redactar(c)
    assert e.value.codigo == "salida_invalida" and len(c.llamadas) == 2
    assert "respuesta válida" in e.value.mensaje  # el mensaje ya no dice «JSON válido» (el JSON sí era válido)


def test_hechos_repetidos_se_ubican_una_sola_vez():
    c = ClienteFalso([_resp(hechos=["El Sprint dura un mes", "El  Sprint dura un mes"])])
    assert len(_redactar(c).hechos) == 1


def test_registra_modelo_y_fallback():
    r = _redactar(ClienteFalso([_resp()], modelo="otro", fallback=True))
    assert r.modelo == "otro" and r.fallback is True

def test_campo_que_se_pasa_del_limite_se_corrige_en_un_reintento_con_el_motivo():
    """Con una fuente larga el modelo se pasa del límite; el reintento le dice cuánto y lo corrige sin abortar el run."""
    c = ClienteFalso([_resp(campos={"titulo": "x" * 66, "cuerpo": "Duran un mes."}), _resp()])
    r = _redactar(c)
    assert len(c.llamadas) == 2 and r.campos["titulo"] == "Sprints de un mes"
    assert "supera 60 caracteres (66)" in c.llamadas[1]["mensajes"][-1]["content"]


def test_campo_que_se_pasa_del_limite_dos_veces_se_recorta_sin_abortar(caplog):
    """Antes abortaba el run (salida_invalida); ahora el último intento recorta el campo y deja aviso en el log."""
    titulo = "Los derechos del paciente. Incluyen trato digno, información clara y medicamentos"  # 81 > 60
    mala = _resp(campos={"titulo": titulo, "cuerpo": "Duran un mes."})
    c = ClienteFalso([mala, mala])
    with caplog.at_level(logging.WARNING, logger="app.agentes.redactor"):
        r = _redactar(c)
    assert len(c.llamadas) == 2
    # La primera oración (26) deja menos de la mitad del límite (60): se corta en la coma y se conserva más texto.
    assert r.campos["titulo"] == "Los derechos del paciente. Incluyen trato digno…"
    assert titulo.startswith(r.campos["titulo"].removesuffix("…"))
    assert "recortado" in caplog.text and "titulo" in caplog.text


# ---------------------------- recortar_a_limite ----------------------------

from app.agentes.redactor import recortar_a_limite  # noqa: E402


def test_recorte_un_texto_que_cabe_no_cambia():
    assert recortar_a_limite("  Corto.  ", 20) == "Corto."


def test_recorte_prefiere_la_ultima_oracion_completa():
    texto = "El Sprint dura un mes. El equipo tiene diez personas. Se revisa al final."
    assert recortar_a_limite(texto, 55) == "El Sprint dura un mes. El equipo tiene diez personas."


def test_recorte_en_una_coma_si_la_oracion_deja_poco():
    texto = "Derechos: trato digno, información clara, medicamentos necesarios y quejas"
    r = recortar_a_limite(texto, 50)
    assert len(r) <= 50 and r.endswith("…") and texto.startswith(r[:-1])
    assert r == "Derechos: trato digno, información clara…"


def test_recorte_en_un_espacio_si_no_hay_comas():
    texto = "palabra " * 20
    r = recortar_a_limite(texto, 30)
    assert len(r) <= 30 and r.endswith("…") and not r[:-1].endswith(" ")


def test_recorte_en_seco_como_ultimo_recurso():
    r = recortar_a_limite("x" * 100, 10)
    assert r == "x" * 9 + "…" and len(r) == 10


@pytest.mark.parametrize("maximo", [20, 60, 100, 220])
def test_recorte_nunca_pasa_del_limite_y_siempre_es_prefijo(maximo):
    texto = ("El artículo 4° garantiza la salud, el acceso a medicamentos; y la atención. " * 6).strip()
    r = recortar_a_limite(texto, maximo)
    assert len(r) <= maximo
    assert texto.startswith(r.removesuffix("…"))
