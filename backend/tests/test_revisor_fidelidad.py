"""Pruebas del revisor de fidelidad: afirmaciones, citas literales, cifras, hallazgos y revisar_fidelidad."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.agentes.revisor_fidelidad as rf
from app.agentes.cliente_llm import RespuestaLLM
from app.agentes.comun import AgenteError
from app.agentes.comun import cargar_prompt as cargar_prompt_real
from app.agentes.estratega import Brief
from app.agentes.redactor import TextoSlide
from app.agentes.revisor_fidelidad import (
    CITA_MAX_CHARS,
    MAX_TOKENS_REVISOR,
    Afirmacion,
    hallazgo_de_afirmacion,
    hallazgos_por_cifras,
    revisar_fidelidad,
)

# Fuente sintética de dos fragmentos (el segundo empieza tras una línea en blanco), como en test_redactor.
P0 = "El Sprint dura un mes como máximo. El equipo tiene 10 personas o menos."
P1 = "El Product Owner ordena el Product Backlog.\nEl Scrum Master ayuda al equipo."
TEXTO = P0 + "\n\n" + P1
INICIO_P1 = len(P0) + 2
FRAGMENTOS = (
    SimpleNamespace(indice=0, texto=P0, inicio=0),
    SimpleNamespace(indice=1, texto=P1, inicio=INICIO_P1),
)
FUENTE = SimpleNamespace(texto=TEXTO, fragmentos=FRAGMENTOS)

CITA_P0 = "El Sprint dura un mes como máximo."
CITA_P1 = "El Scrum Master ayuda al equipo."


@pytest.fixture(autouse=True)
def _prompt_falso(monkeypatch):
    """Evita depender del archivo revisor.md en casi todos los tests (uno aparte comprueba el real)."""
    monkeypatch.setattr(rf, "cargar_prompt", lambda nombre: "<!-- c -->SISTEMA FIJO")


def _brief(asignados=None) -> Brief:
    """Brief mínimo: por defecto el slide 1 apunta al fragmento 0."""
    return Brief(angulo="idea", tono="didáctico",
                 fragmentos_por_slide=asignados if asignados is not None else {1: (0,)},
                 modelo="m1", fallback=False)


def _texto(numero=1, **campos) -> TextoSlide:
    """TextoSlide del redactor; sin campos dados trae una sola frase sin cifras."""
    campos = campos or {"titulo": "Duran un mes como máximo."}
    return TextoSlide(numero, campos, (), "m1", False)


def _a(frase=1, tipo="factual", veredicto="respaldada", cita=CITA_P0, motivo="ok"):
    """Juicio crudo como lo devolvería el modelo: señala el número de la frase."""
    return {"frase": frase, "tipo": tipo, "veredicto": veredicto, "cita": cita, "motivo": motivo}


# Un slide de dos frases, para los tests que necesitan dos juicios.
DOS_FRASES = {"titulo": "Duran un mes como máximo.", "cuerpo": "El equipo es pequeño."}


class PedirFalso:
    """Sustituye al modelo: devuelve respuestas guionadas y guarda (sistema, usuario) de cada llamada."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[tuple[str, str]] = []

    async def __call__(self, sistema, usuario):
        self.llamadas.append((sistema, usuario))
        return self.respuestas.pop(0)


class ClienteFalso:
    """Respuestas guionadas para el cliente real; registra rol, mensajes y parámetros de cada llamada."""

    def __init__(self, respuestas, modelo="m1", fallback=False):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []
        self.modelo, self.fallback = modelo, fallback

    async def completar(self, rol, mensajes, **kw):
        self.llamadas.append({"rol": rol, "mensajes": mensajes, **kw})
        item = self.respuestas.pop(0)
        texto, motivo = item if isinstance(item, tuple) else (item, "stop")
        return RespuestaLLM(texto, self.modelo, "m1", self.fallback, motivo, None, 0.0)


def _revisar(pedir, textos=None, brief=None):
    """Ejecuta revisar_fidelidad con el modelo falso (sin cliente)."""
    return asyncio.run(revisar_fidelidad(None, brief or _brief(), FUENTE, textos or [_texto()], pedir))


def _una(*afirmaciones, **kw):
    """Revisa el slide 1 con un modelo falso que devuelve esas afirmaciones; devuelve el resultado."""
    return _revisar(PedirFalso({"afirmaciones": list(afirmaciones)}), **kw)


# ---------------------------- afirmación respaldada ----------------------------

def test_respaldada_con_cita_literal_ubicada_en_la_fuente():
    r = _una(_a())
    (a,) = r.afirmaciones
    assert (a.afirmacion_id, a.slide, a.clasificacion, a.veredicto) == ("a1", 1, "factual", "respaldada")
    assert TEXTO[a.cita["inicio"]:a.cita["fin"]] == a.cita["fragmento"] == CITA_P0
    assert r.hallazgos == []
    assert r.sello == {"slides_verificados": 1, "slides_sin_fragmentos": 0, "afirmaciones_factuales": 1,
                       "respaldadas": 1, "no_verificadas": 0, "hallazgos": 0}


def test_la_cita_guardada_es_el_trozo_real_de_la_fuente_aunque_el_modelo_cambie_espacios():
    (a,) = _una(_a(cita="El Sprint dura   un\nmes como máximo.")).afirmaciones
    assert a.veredicto == "respaldada" and a.cita["fragmento"] == CITA_P0


def test_posicion_absoluta_cuando_la_cita_esta_en_el_segundo_fragmento():
    r = _una(_a(cita=CITA_P1), brief=_brief({1: (1,)}))
    c = r.afirmaciones[0].cita
    assert c["inicio"] >= INICIO_P1 and TEXTO[c["inicio"]:c["fin"]] == c["fragmento"]


# ---------------------------- citas que no sirven ----------------------------

@pytest.mark.parametrize("cita", [
    "texto que no está en la fuente",
    "El Sprint dura un mes ... como máximo.",
    "El Sprint dura un mes… como máximo.",
    "x" * (CITA_MAX_CHARS + 1),
    "",
    "   ",
    None,
    42,
])
def test_respaldo_sin_cita_literal_pasa_a_no_verificada_y_no_abre_hallazgo(cita):
    r = _una(_a(cita=cita))
    (a,) = r.afirmaciones
    assert a.veredicto == "no_verificada" and a.cita is None and "no es literal" in a.motivo
    assert r.hallazgos == [] and r.sello["no_verificadas"] == 1


def test_cita_literal_pero_de_un_fragmento_no_asignado_no_vale():
    # El Product Owner está en el fragmento 1, pero el slide 1 solo tiene asignado el 0.
    (a,) = _una(_a(cita="El Product Owner ordena el Product Backlog.")).afirmaciones
    assert a.veredicto == "no_verificada"


def test_parcialmente_respaldada_tambien_exige_cita():
    (a,) = _una(_a(veredicto="parcialmente_respaldada", cita="inventada")).afirmaciones
    assert a.veredicto == "no_verificada"


@pytest.mark.parametrize("veredicto", [None, "quizas", "", 3])
def test_factual_sin_veredicto_valido_es_no_verificada(veredicto):
    (a,) = _una(_a(veredicto=veredicto, cita=None)).afirmaciones
    assert a.veredicto == "no_verificada" and a.cita is None


def test_no_respaldada_conserva_la_cita_si_es_literal_y_la_descarta_si_no():
    a1, a2 = _una(_a(veredicto="no_respaldada", cita=CITA_P0), _a(2, veredicto="no_respaldada", cita="inventada"),
                  textos=[_texto(**DOS_FRASES)]).afirmaciones
    assert a1.veredicto == "no_respaldada" and a1.cita is not None
    assert a2.veredicto == "no_respaldada" and a2.cita is None


# ---------------------------- clasificación impuesta por el código ----------------------------

def test_opinion_o_cta_siempre_es_no_aplica_y_sin_cita():
    textos = [_texto(titulo="Guárdalo para después.")]
    (a,) = _una(_a(tipo="opinion_cta", veredicto="respaldada"), textos=textos).afirmaciones
    assert (a.clasificacion, a.veredicto, a.cita) == ("opinion_cta", "no_aplica", None)


def test_una_cifra_vuelve_factual_a_una_opinion():
    textos = [_texto(titulo="Empieza en 5 minutos.")]
    (a,) = _una(_a(tipo="opinion_cta", veredicto=None, cita=None), textos=textos).afirmaciones
    assert a.clasificacion == "factual" and a.veredicto == "no_verificada"


def test_contradice_vuelve_factual_a_una_opinion():
    (a,) = _una(_a(tipo="opinion_cta", veredicto="contradice", cita=CITA_P0)).afirmaciones
    assert (a.clasificacion, a.veredicto) == ("factual", "contradice")


@pytest.mark.parametrize("tipo", ["otro", None, 7])
def test_tipo_desconocido_es_factual(tipo):
    assert _una(_a(tipo=tipo)).afirmaciones[0].clasificacion == "factual"


# ---------------------------- hallazgos por veredicto ----------------------------

def test_contradice_es_bloqueante_para_el_redactor():
    r = _una(_a(veredicto="contradice", motivo="La fuente dice un mes."), textos=[_texto(titulo="Dura dos meses.")])
    (h,) = r.hallazgos
    assert (h.dimension, h.gravedad, h.slide, h.responsable) == ("fidelidad", "bloqueante", 1, "redactor")
    assert h.evidencia == "Dura dos meses." and h.explicacion == "La fuente dice un mes."


def test_no_respaldada_es_bloqueante():
    (h,) = _una(_a(veredicto="no_respaldada", cita=None)).hallazgos
    assert h.gravedad == "bloqueante"


def test_parcialmente_respaldada_es_mayor():
    (h,) = _una(_a(veredicto="parcialmente_respaldada")).hallazgos
    assert h.gravedad == "mayor"


@pytest.mark.parametrize("veredicto, esperado", [
    ("contradice", "bloqueante"), ("no_respaldada", "bloqueante"), ("parcialmente_respaldada", "mayor"),
    ("respaldada", None), ("no_verificada", None), ("no_aplica", None),
])
def test_gravedad_por_veredicto(veredicto, esperado):
    clasif = "opinion_cta" if veredicto == "no_aplica" else "factual"
    cita = {"fragmento": "x", "inicio": 0, "fin": 1} if veredicto in ("respaldada", "parcialmente_respaldada") else None
    h = hallazgo_de_afirmacion(Afirmacion("a1", 1, "x", clasif, veredicto, cita, "m"))
    assert (h.gravedad if h else None) == esperado


def test_hallazgos_ordenados_bloqueante_antes_que_mayor():
    r = _una(_a(veredicto="parcialmente_respaldada"), _a(2, veredicto="contradice"), textos=[_texto(**DOS_FRASES)])
    assert [h.gravedad for h in r.hallazgos] == ["bloqueante", "mayor"]


# ---------------------------- cifras (control por código) ----------------------------

def test_cifra_ausente_de_los_fragmentos_es_hallazgo_mayor_aunque_el_modelo_no_la_marque():
    textos = [_texto(cuerpo="Duran 7 meses.")]
    r = _una(_a(), textos=textos)
    assert r.afirmaciones[0].veredicto == "respaldada"  # el modelo la dio por buena
    (h,) = r.hallazgos
    assert (h.dimension, h.gravedad, h.responsable) == ("fidelidad", "mayor", "redactor") and "la cifra 7" in h.evidencia


def test_cifra_presente_en_los_fragmentos_no_abre_hallazgo():
    textos = [_texto(cuerpo="Equipos de 10 personas o menos.")]
    assert _una(_a(cita="El equipo tiene 10 personas o menos."), textos=textos).hallazgos == []


def test_cifra_ya_marcada_por_el_modelo_no_se_duplica():
    textos = [_texto(cuerpo="Duran 7 meses.")]
    r = _una(_a(veredicto="contradice"), textos=textos)
    assert len(r.hallazgos) == 1 and r.hallazgos[0].gravedad == "bloqueante"


def test_cifra_repetida_en_el_slide_se_marca_una_sola_vez():
    hs = hallazgos_por_cifras(1, {"titulo": "7 y 7", "cuerpo": "Son 7."}, ["sin números"], [])
    assert len(hs) == 1


@pytest.mark.parametrize("slide_texto, fuente", [
    ("Son 1000 personas", "Hay 1.000 personas"),
    ("Son 1.000 personas", "Hay 1000 personas"),
    ("Mide 1,5 metros", "Mide 1.5 metros"),
    ("Mide 1.5 metros", "Mide 1,5 metros"),
    ("El 50% del tiempo", "Es el 50 % del tiempo"),
])
def test_cifras_equivalentes_se_reconocen(slide_texto, fuente):
    assert hallazgos_por_cifras(1, {"cuerpo": slide_texto}, [fuente], []) == []


def test_cifras_solo_miran_campos_de_texto():
    assert hallazgos_por_cifras(1, {"cuerpo": None, "titulo": 5}, ["nada"], []) == []


# ---------------------------- cifras: contexto, marcadores y comparación exacta ----------------------------

def _evidencias(campos, fragmentos=("sin números",), llm=()):
    """Evidencias de los hallazgos por cifras del slide 1 (`llm` simula los hallazgos que ya marcó el modelo)."""
    return [h.evidencia for h in hallazgos_por_cifras(1, campos, list(fragmentos), list(llm))]


def _del_modelo(evidencia, slide=1):
    """Hallazgo mínimo del modelo: solo importan el slide y la evidencia."""
    return SimpleNamespace(slide=slide, evidencia=evidencia)


def test_hallazgo_de_cifra_incluye_la_frase_donde_aparece():
    (ev,) = _evidencias({"cuerpo": "Son 7 pasos clave para empezar."})
    assert "la cifra 7" in ev and "Son 7 pasos clave para empezar." in ev


def test_la_frase_de_contexto_es_corta_y_marca_los_recortes():
    largo = "palabra " * 30 + "con 7 elementos " + "palabra " * 30
    (ev,) = _evidencias({"cuerpo": largo})
    frase = ev.split("(frase: «", 1)[1].rsplit("»)", 1)[0]
    assert "7" in frase and frase.startswith("…") and frase.endswith("…")
    assert len(frase) <= rf.FRASE_CIFRA_MAX_CHARS + 2  # el límite más las dos elipsis


@pytest.mark.parametrize("texto", [
    "1. Primero\n2. Segundo",
    "- 1) Primero\n- 2) Segundo",
    "  3. Tercero",
])
def test_marcadores_de_lista_no_abren_hallazgo(texto):
    assert _evidencias({"cuerpo": texto}) == []


@pytest.mark.parametrize("texto", [
    "Son 1. Luego sigue",    # a mitad de línea
    "1.5 millones",          # decimal, no marcador
    "Hay 1 acción clave",    # sin punto ni paréntesis
])
def test_una_cifra_que_no_es_marcador_sigue_marcandose(texto):
    assert len(_evidencias({"cuerpo": texto})) == 1


def test_un_marcador_no_tapa_la_misma_cifra_cuando_aparece_como_dato():
    (ev,) = _evidencias({"cuerpo": "1. Primero\nHay 1 acción."})
    assert "la cifra 1" in ev and "Hay 1 acción." in ev


def test_cifra_senalada_por_el_modelo_se_compara_exacta_no_por_subcadena():
    llm = [_del_modelo("Tiene 11 módulos desde 2024.")]
    assert len(_evidencias({"cuerpo": "Hay 1 acción."}, llm=llm)) == 1   # el «1» no está en «11» ni en «2024»
    assert _evidencias({"cuerpo": "Hay 11 acciones."}, llm=llm) == []     # el «11» sí estaba señalado


def test_hallazgo_del_modelo_de_otro_slide_no_cuenta_como_senalado():
    assert len(_evidencias({"cuerpo": "Duran 7 meses."}, llm=[_del_modelo("Duran 7 meses.", slide=2)])) == 1


# ---------------------------- flujo por slide ----------------------------

def test_todas_las_frases_se_juzgan_aunque_sean_muchas():
    textos = [_texto(cuerpo=" ".join(f"Dato número {chr(97 + i)} listo." for i in range(20)))]
    r = _una(*[_a(n) for n in range(1, 21)], textos=textos)
    assert [a.afirmacion_id for a in r.afirmaciones] == [f"a{i}" for i in range(1, 21)]


def test_ids_continuos_entre_slides_y_cada_una_con_su_slide():
    pedir = PedirFalso(
        {"afirmaciones": [_a(), _a(2)]},
        {"afirmaciones": [_a(cita=CITA_P1), _a(2, cita=CITA_P1)]},
    )
    textos = [_texto(1, **DOS_FRASES), _texto(2, **DOS_FRASES)]
    r = _revisar(pedir, textos=textos, brief=_brief({1: (0,), 2: (1,)}))
    assert [(a.afirmacion_id, a.slide) for a in r.afirmaciones] == [("a1", 1), ("a2", 1), ("a3", 2), ("a4", 2)]
    assert r.sello["slides_verificados"] == 2 and len(pedir.llamadas) == 2


def test_items_invalidos_de_la_lista_se_ignoran():
    r = _una("texto suelto", {"frase": 9}, {"tipo": "factual"}, 5, _a())
    assert [a.afirmacion_id for a in r.afirmaciones] == ["a1"]  # la numeración no deja huecos


def test_slide_sin_fragmentos_asignados_no_llama_al_modelo():
    pedir = PedirFalso()
    r = _revisar(pedir, textos=[_texto(1), _texto(2)], brief=_brief({}))
    assert pedir.llamadas == [] and r.afirmaciones == []
    assert r.sello["slides_sin_fragmentos"] == 2 and r.sello["slides_verificados"] == 0


def test_indice_de_fragmento_fuera_de_rango_se_ignora():
    pedir = PedirFalso()
    _revisar(pedir, brief=_brief({1: (99,)}))
    assert pedir.llamadas == []


def test_slide_sin_texto_en_los_campos_se_omite():
    pedir = PedirFalso()
    r = _revisar(pedir, textos=[_texto(1, titulo="   ")])
    assert pedir.llamadas == [] and r.sello["slides_verificados"] == 0 and r.sello["slides_sin_fragmentos"] == 0


def test_acepta_textos_con_atributo_slide():
    t = SimpleNamespace(slide=1, campos={"titulo": "Sprints"})
    assert _una(_a(), textos=[t]).afirmaciones[0].slide == 1


def test_respuesta_sin_la_lista_de_afirmaciones_es_error():
    with pytest.raises(AgenteError) as e:
        _revisar(PedirFalso({"otra": []}))
    assert e.value.codigo == "revisor_respuesta_invalida"


def test_el_pedido_lleva_prompt_fijo_y_solo_los_fragmentos_asignados():
    pedir = PedirFalso({"afirmaciones": [_a()]})
    _revisar(pedir)
    sistema, usuario = pedir.llamadas[0]
    assert sistema == "SISTEMA FIJO"  # sin el comentario HTML, que no debe llegar al modelo
    assert "SLIDE: 1" in usuario and "1. [titulo] Duran un mes como máximo." in usuario
    assert "[F1] " + P0 in usuario and "Product Owner" not in usuario and "[F2]" not in usuario


# ---------------------------- Afirmacion (reglas del contrato) ----------------------------

CITA_OK = {"fragmento": "x", "inicio": 0, "fin": 1}
BASE = dict(afirmacion_id="a1", slide=1, afirmacion="x", clasificacion="factual", veredicto="no_respaldada",
            cita=None, motivo="m")


@pytest.mark.parametrize("cambio", [
    {"veredicto": "respaldada"},                                          # regla 1: respalda sin cita
    {"veredicto": "parcialmente_respaldada"},                             # regla 1
    {"clasificacion": "opinion_cta"},                                     # regla 2: opinión con veredicto de hecho
    {"clasificacion": "opinion_cta", "veredicto": "respaldada", "cita": CITA_OK},  # regla 2
    {"clasificacion": "opinion_cta", "veredicto": "contradice"},          # reglas 2 y 4
    {"veredicto": "no_aplica"},                                           # regla 3: no_aplica en algo factual
    {"afirmacion_id": "a1000"}, {"afirmacion_id": "x1"}, {"afirmacion_id": "a"},
    {"clasificacion": "otra"}, {"veredicto": "quizas"},
    {"afirmacion": "  "}, {"motivo": ""},
    {"veredicto": "respaldada", "cita": {"fragmento": "x", "inicio": 5, "fin": 5}},
    {"veredicto": "respaldada", "cita": {"fragmento": "x", "inicio": 5, "fin": 2}},
    {"veredicto": "respaldada", "cita": {"fragmento": "x", "inicio": -1, "fin": 2}},
    {"veredicto": "respaldada", "cita": {"fragmento": "", "inicio": 0, "fin": 1}},
    {"veredicto": "respaldada", "cita": {"fragmento": "x" * (CITA_MAX_CHARS + 1), "inicio": 0, "fin": 1}},
    {"veredicto": "respaldada", "cita": {"inicio": 0, "fin": 1}},
])
def test_afirmacion_rechaza_combinaciones_que_el_contrato_no_admite(cambio):
    with pytest.raises(AgenteError) as e:
        Afirmacion(**{**BASE, **cambio})
    assert e.value.codigo == "afirmacion_invalida"


def test_afirmacion_acepta_las_combinaciones_validas():
    Afirmacion(**{**BASE, "clasificacion": "opinion_cta", "veredicto": "no_aplica"})
    Afirmacion(**{**BASE, "veredicto": "no_verificada"})
    Afirmacion(**{**BASE, "veredicto": "contradice", "cita": CITA_OK})
    Afirmacion(**{**BASE, "veredicto": "respaldada", "cita": CITA_OK})


def test_a_evento_deja_el_slide_en_el_sobre_y_el_payload_del_contrato():
    ev = Afirmacion(**{**BASE, "slide": 3, "veredicto": "respaldada", "cita": CITA_OK}).a_evento()
    assert ev["slide"] == 3
    assert set(ev["payload"]) == {"afirmacion_id", "afirmacion", "clasificacion", "veredicto", "cita", "motivo"}
    assert ev["payload"]["cita"] == CITA_OK


# ---------------------------- con el cliente real (pedir_json) ----------------------------

def _json(*afirmaciones):
    return json.dumps({"afirmaciones": list(afirmaciones)})


def _con_cliente(cliente):
    return asyncio.run(revisar_fidelidad(cliente, _brief(), FUENTE, [_texto()]))


def test_usa_el_rol_revisor_sin_fallback_y_con_el_tope_de_tokens():
    c = ClienteFalso([_json(_a())])
    r = _con_cliente(c)
    llamada = c.llamadas[0]
    assert llamada["rol"] == "revisor_a" and llamada["max_tokens"] == MAX_TOKENS_REVISOR
    assert llamada["permitir_fallback"] is None   # Sin forzar: el cliente aplica la cadena propia del revisor (gpt-oss-120b → 20b), nunca el modelo del redactor.
    assert [m["role"] for m in llamada["mensajes"]] == ["system", "user"]
    assert llamada["mensajes"][0]["content"] == "SISTEMA FIJO"
    assert r.afirmaciones[0].veredicto == "respaldada"


def test_reintenta_tras_json_roto():
    c = ClienteFalso(['{"afirmaciones"', _json(_a())])
    assert len(_con_cliente(c).afirmaciones) == 1 and len(c.llamadas) == 2


def test_forma_invalida_tras_agotar_reintentos_es_salida_invalida():
    c = ClienteFalso([json.dumps({"x": 1}), json.dumps({"x": 1})])
    with pytest.raises(AgenteError) as e:
        _con_cliente(c)
    assert e.value.codigo == "salida_invalida" and len(c.llamadas) == 2


def test_salida_truncada_falla_sin_reintentar():
    c = ClienteFalso([(_json(_a())[:30], "length")])
    with pytest.raises(AgenteError) as e:
        _con_cliente(c)
    assert e.value.codigo == "salida_truncada" and len(c.llamadas) == 1


# ---------------------------- prompt real ----------------------------

def test_prompt_real_se_carga_desde_la_carpeta_de_prompts_y_sin_comentarios():
    # Falla si revisor.md no está junto a redactor.md.
    texto = cargar_prompt_real("revisor")
    assert "afirmaciones" in texto
    assert "<!--" not in rf._COMENTARIO_HTML.sub("", texto)

# ---------------------------- revisión agrupada (varios slides por llamada) ----------------------------

def _agrupado(pedir, slides_por_llamada):
    """Slides 1 y 2 con fragmentos distintos (P0 y P1), revisados en grupos del tamaño pedido."""
    brief = _brief({1: (0,), 2: (1,)})
    textos = [_texto(1), _texto(2, cuerpo="El Scrum Master ayuda al equipo.")]
    return asyncio.run(revisar_fidelidad(None, brief, FUENTE, textos, pedir, slides_por_llamada=slides_por_llamada))


def test_agrupado_revisa_dos_slides_en_una_llamada_con_sus_propios_fragmentos():
    a2 = _a(cita=CITA_P1)
    pedir = PedirFalso({"slides": [{"slide": 2, "afirmaciones": [a2]}, {"slide": 1, "afirmaciones": [_a()]}]})
    r = _agrupado(pedir, 2)
    assert len(pedir.llamadas) == 1
    usuario = pedir.llamadas[0][1]
    assert "SLIDE: 1" in usuario and "SLIDE: 2" in usuario and rf.SEPARADOR_SLIDES in usuario
    # Orden e ids según el grupo, no según el orden de la respuesta del modelo.
    assert [(a.afirmacion_id, a.slide) for a in r.afirmaciones] == [("a1", 1), ("a2", 2)]
    assert r.afirmaciones[1].cita["inicio"] == TEXTO.index(CITA_P1)
    assert r.sello["slides_verificados"] == 2


def test_agrupado_una_cita_de_otro_slide_no_respalda():
    # El slide 1 cita un trozo que solo está en los fragmentos del slide 2: no es literal para él.
    a2 = _a(cita=CITA_P1)
    pedir = PedirFalso({"slides": [{"slide": 1, "afirmaciones": [_a(cita=CITA_P1)]}, {"slide": 2, "afirmaciones": [a2]}]})
    r = _agrupado(pedir, 2)
    assert r.afirmaciones[0].veredicto == "no_verificada" and r.afirmaciones[0].cita is None


def test_agrupado_un_slide_omitido_se_revisa_solo_en_otra_llamada():
    pedir = PedirFalso(
        {"slides": [{"slide": 1, "afirmaciones": [_a()]}]},  # falta el slide 2
        {"afirmaciones": [_a(cita=CITA_P1)]},
    )
    r = _agrupado(pedir, 2)
    assert len(pedir.llamadas) == 2
    assert "SLIDE: 2" in pedir.llamadas[1][1] and "SLIDE: 1" not in pedir.llamadas[1][1]
    assert [(a.afirmacion_id, a.slide, a.veredicto) for a in r.afirmaciones] == [("a1", 1, "respaldada"), ("a2", 2, "respaldada")]


def test_con_pedir_inyectado_y_sin_valor_se_mantiene_una_llamada_por_slide():
    a2 = _a(cita=CITA_P1)
    pedir = PedirFalso({"afirmaciones": [_a()]}, {"afirmaciones": [a2]})
    _agrupado(pedir, None)
    assert len(pedir.llamadas) == 2


def test_cliente_real_agrupa_por_defecto_y_duplica_el_tope_de_salida():
    respuesta = json.dumps({"slides": [
        {"slide": 1, "afirmaciones": [_a()]},
        {"slide": 2, "afirmaciones": [_a(cita=CITA_P1)]},
    ]})
    c = ClienteFalso([respuesta])
    textos = [_texto(1), _texto(2, cuerpo="El Scrum Master ayuda al equipo.")]
    r = asyncio.run(revisar_fidelidad(c, _brief({1: (0,), 2: (1,)}), FUENTE, textos))
    assert len(c.llamadas) == 1 and c.llamadas[0]["max_tokens"] == MAX_TOKENS_REVISOR * 2
    assert len(r.afirmaciones) == 2


def test_validador_acepta_las_dos_formas_y_rechaza_otra():
    assert rf._validar_respuesta({"afirmaciones": []}) == []
    assert rf._validar_respuesta({"slides": [{"slide": 1, "afirmaciones": []}]}) == []
    # Tolerante: un elemento raro no invalida la respuesta (ese slide se revisa solo después).
    assert rf._validar_respuesta({"slides": [{"slide": "1"}, "basura"]}) == []
    assert rf._validar_respuesta({"x": 1})


def test_agrupado_acepta_el_numero_de_slide_como_texto():
    a2 = _a(cita=CITA_P1)
    pedir = PedirFalso({"slides": [{"slide": "1", "afirmaciones": [_a()]}, {"slide": "SLIDE 2", "afirmaciones": [a2]}]})
    r = _agrupado(pedir, 2)
    assert len(pedir.llamadas) == 1
    assert [a.slide for a in r.afirmaciones] == [1, 2]


def test_agrupado_un_elemento_ilegible_no_tumba_el_run():
    pedir = PedirFalso(
        {"slides": [{"slide": 1, "afirmaciones": [_a()]}, "basura"]},
        {"afirmaciones": [_a(cita=CITA_P1)]},  # el slide 2 se revisa solo
    )
    r = _agrupado(pedir, 2)
    assert len(pedir.llamadas) == 2 and r.sello["slides_verificados"] == 2


def test_cita_rechazada_queda_en_el_log_con_su_causa(caplog):
    """La cita que el modelo dio y no se pudo ubicar se registra, para saber por qué quedó no_verificada."""
    crudo = {"frase": 1, "tipo": "factual", "veredicto": "respaldada",
             "cita": "El Sprint dura dos meses.", "motivo": "ok"}
    with caplog.at_level("WARNING", logger="app.agentes.revisor_fidelidad"):
        af = rf._normalizar_afirmacion(crudo, 3, 1, FRAGMENTOS, "El Sprint dura un mes.")
    assert af.veredicto == "no_verificada" and af.cita is None
    assert "no aparece en los fragmentos" in caplog.text
    assert "El Sprint dura dos meses." in caplog.text


@pytest.mark.parametrize("cita, causa", [
    (None, "sin cita"),
    ("a" * 500, "demasiado larga"),
    ("El Sprint ... un mes", "puntos suspensivos"),
])
def test_causa_de_cita_rechazada(cita, causa):
    assert causa in rf._por_que_no_es_literal(cita)


# ---------------------------- las frases las pone el código y ninguna pasa sin veredicto ----------------------------

A2 = _a(cita=CITA_P1)
VACIOS = {"slides": [{"slide": 1, "afirmaciones": []}, {"slide": 2, "afirmaciones": []}]}
SLIDE_5 = {"titulo": "Controla tu tiempo y espacio con 1CTRL en Dubai"}


def test_el_modelo_no_puede_cambiar_la_frase_que_se_evalua():
    """Visto en un run real: el modelo redactaba una versión más suave del título y aprobaba esa versión."""
    suave = _a() | {"afirmacion": "1CTRL permite controlar cómo vives en Dubai."}
    r = _una(suave, textos=[_texto(**SLIDE_5)])
    assert [a.afirmacion for a in r.afirmaciones] == [SLIDE_5["titulo"]]


def test_un_grupo_que_vuelve_vacio_se_verifica_slide_por_slide():
    """Lo visto en un run real: los 3 slides de la primera llamada volvieron sin afirmaciones y pasaron."""
    pedir = PedirFalso(VACIOS, {"afirmaciones": [_a()]}, {"afirmaciones": [A2]})
    r = _agrupado(pedir, 2)
    assert len(pedir.llamadas) == 3 and r.hallazgos == []
    assert [(a.afirmacion_id, a.slide) for a in r.afirmaciones] == [("a1", 1), ("a2", 2)]


def test_si_falta_una_frase_se_pide_de_nuevo_y_solo_rellena_el_hueco():
    """El segundo intento no puede ablandar lo ya juzgado."""
    pedir = PedirFalso({"afirmaciones": [_a(veredicto="contradice")]}, {"afirmaciones": [_a(), _a(2)]})
    r = _revisar(pedir, textos=[_texto(**DOS_FRASES)])
    assert len(pedir.llamadas) == 2
    assert [a.veredicto for a in r.afirmaciones] == ["contradice", "respaldada"]


def test_la_frase_que_sigue_sin_veredicto_abre_un_hallazgo_que_la_muestra():
    pedir = PedirFalso({"afirmaciones": [_a()]}, {"afirmaciones": [_a()]})
    r = _revisar(pedir, textos=[_texto(**DOS_FRASES)])
    (h,) = r.hallazgos
    assert (h.slide, h.dimension, h.gravedad, h.responsable) == (1, "fidelidad", "mayor", "estratega")
    assert h.evidencia == "Sin verificar («cuerpo»): El equipo es pequeño."
    assert r.sello["slides_verificados"] == 0 and len(r.afirmaciones) == 1


def test_dos_juicios_de_la_misma_frase_gana_el_mas_severo():
    r = _una(_a(), _a(veredicto="no_respaldada", cita=None), _a())
    assert [a.veredicto for a in r.afirmaciones] == ["no_respaldada"]


@pytest.mark.parametrize("numero", [0, 2, None, "ninguna", True])
def test_un_numero_que_no_es_de_una_frase_se_ignora(numero):
    r = _una(_a(), _a(numero, veredicto="contradice"))
    assert [a.veredicto for a in r.afirmaciones] == ["respaldada"]


def test_el_numero_de_frase_puede_venir_como_texto():
    assert _una(_a("1")).afirmaciones[0].veredicto == "respaldada"
