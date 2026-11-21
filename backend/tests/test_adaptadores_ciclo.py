"""Pruebas de los adaptadores del ciclo y de las correcciones del redactor (sin LLM ni servidor)."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agentes.adaptadores_ciclo import (
    CORRECCION_MAX_CHARS,
    MAX_CORRECCIONES,
    CorrectorCarrusel,
    EstadoCarrusel,
    RevisorCarrusel,
    texto_de_correccion,
)
from app.agentes.ciclo_correccion import HallazgoAbierto, ejecutar_ciclo
from app.agentes.comun import AgenteError
from app.agentes.estratega import Brief
from app.agentes.redactor import TextoSlide, construir_mensajes


def texto(numero, titulo="ok"):
    """TextoSlide mínimo para las pruebas."""
    return TextoSlide(numero, {"titulo": titulo}, (), "modelo", False)


def brief():
    """Brief mínimo."""
    return Brief("ángulo", "tono", {1: (0,), 2: (1,)}, "modelo", False)


def estado_base():
    """Estado con dos slides."""
    return EstadoCarrusel({1: texto(1), 2: texto(2)}, brief())


def hallazgo_final(slide, dimension="fidelidad", gravedad="bloqueante", evidencia="e", responsable="redactor"):
    """Hallazgo ya en la forma {"slide", "payload"} que entrega con_ids."""
    return {
        "slide": slide,
        "payload": {
            "hallazgo_id": "h1", "dimension": dimension, "gravedad": gravedad, "evidencia": evidencia,
            "explicacion": "explica", "accion": "haz esto", "responsable": responsable,
        },
    }


def abierto(slide=1, **kw):
    """HallazgoAbierto como lo entrega el ciclo al corrector."""
    h = hallazgo_final(slide, **kw)
    return HallazgoAbierto("h1", slide, h["payload"], seq_abierto=3)


class Afirmacion:
    """Afirmación falsa con a_evento()."""

    def __init__(self, slide, veredicto="respaldada"):
        self.slide = slide
        self.veredicto = veredicto

    def a_evento(self):
        return {"slide": self.slide, "payload": {"afirmacion_id": f"a{self.slide}", "veredicto": self.veredicto}}


class Emisor:
    """Imita Ejecucion.emitir."""

    def __init__(self):
        self.eventos = []

    async def __call__(self, agente, tipo, payload, slide=None, causa=None):
        evento = {"seq": len(self.eventos) + 1, "agente": agente, "tipo": tipo, "payload": payload, "slide": slide}
        self.eventos.append(evento)
        return evento


def fabricar_revisor(codigo=None, fidelidad=None):
    """RevisorCarrusel con funciones falsas; `llamadas` guarda los argumentos recibidos."""
    llamadas = {"codigo": [], "fidelidad": []}

    def revisar_codigo(resolucion, kit, textos, entrada):
        assert isinstance(textos, list)  # el revisor real recibe una secuencia, no un diccionario
        llamadas["codigo"].append({t.numero for t in textos})
        return codigo(textos) if codigo else []

    async def revisar_fidelidad(cliente, brief_, fuente, textos, pedir=None):
        assert isinstance(textos, list)
        llamadas["fidelidad"].append(({t.numero for t in textos}, pedir))
        hallazgos, afirmaciones = fidelidad(textos) if fidelidad else ([], [])
        return SimpleNamespace(afirmaciones=afirmaciones, hallazgos=hallazgos, sello=None)

    revisor = RevisorCarrusel(
        "cliente", "resolucion", {}, {}, "fuente",
        revisar_codigo=revisar_codigo, revisar_fidelidad=revisar_fidelidad,
        con_ids=lambda hs, primer_numero=1: list(hs), pedir="pedir",
    )
    return revisor, llamadas


def correr(corutina):
    """Ejecuta una corrutina."""
    return asyncio.run(corutina)


# ---------- Corrector ----------


class RedactorFalso:
    """Imita redactar_slide: guarda los argumentos y devuelve un texto nuevo."""

    def __init__(self, error=None):
        self.llamadas = []
        self.error = error

    async def __call__(self, cliente, entrada, resolucion, fuente, brief_, numero, correcciones=()):
        self.llamadas.append((brief_, numero, correcciones))
        if self.error:
            raise self.error
        return texto(numero, "reescrito")


def corrector(redactor):
    """CorrectorCarrusel con el redactor falso."""
    return CorrectorCarrusel("cliente", {}, "resolucion", "fuente", redactar=redactor)


def test_redactor_reescribe_solo_su_slide_y_no_muta_el_estado():
    redactor = RedactorFalso()
    estado = estado_base()
    nuevo = correr(corrector(redactor)(
        "redactor", 1, [abierto(1)], estado))
    assert nuevo is not estado
    assert nuevo.textos[1].campos["titulo"] == "reescrito" and nuevo.textos[2] is estado.textos[2]
    assert estado.textos[1].campos["titulo"] == "ok"  # el estado anterior no se tocó
    brief_, numero, correcciones = redactor.llamadas[0]
    assert brief_ is estado.brief and numero == 1
    assert "explica" in correcciones[0] and "haz esto" in correcciones[0] and "bloqueante" in correcciones[0]


def test_correcciones_se_limitan_en_cantidad_y_largo():
    redactor = RedactorFalso()
    muchos = [abierto(1, evidencia="x" * 1000) for _ in range(MAX_CORRECCIONES + 3)]
    correr(corrector(redactor)("redactor", 1, muchos, estado_base()))
    correcciones = redactor.llamadas[0][2]
    assert len(correcciones) == MAX_CORRECCIONES
    assert all(len(c) <= CORRECCION_MAX_CHARS for c in correcciones)


def test_texto_de_correccion_incluye_gravedad_explicacion_accion():
    t = texto_de_correccion(abierto(1, gravedad="mayor"))
    assert t.startswith("[mayor]") and "explica" in t and "Acción: haz esto" in t


@pytest.mark.parametrize("responsable,slide", [("director_arte", 1), ("estratega", 1), ("redactor", None), (None, 1)])
def test_sin_correccion_automatica_devuelve_el_mismo_estado(responsable, slide):
    redactor = RedactorFalso()
    estado = estado_base()
    assert correr(corrector(redactor)(responsable, slide, [abierto(1)], estado)) is estado
    assert redactor.llamadas == []


def test_error_del_agente_deja_el_estado_igual():
    estado = estado_base()
    redactor = RedactorFalso(error=AgenteError("salida_invalida", "no valida"))
    assert correr(corrector(redactor)("redactor", 1, [abierto(1)], estado)) is estado


def test_otros_errores_se_propagan():
    with pytest.raises(RuntimeError):
        correr(corrector(RedactorFalso(error=RuntimeError("cliente caído")))("redactor", 1, [abierto(1)], estado_base()))


# ---------- Revisor ----------


def test_revisor_junta_codigo_y_fidelidad():
    revisor, _ = fabricar_revisor(
        codigo=lambda t: [hallazgo_final(2, dimension="contraste", responsable="director_arte")],
        fidelidad=lambda t: ([hallazgo_final(1)], [Afirmacion(1), Afirmacion(2, "contradice")]),
    )
    rev = correr(revisor(estado_base(), None))
    assert [h["slide"] for h in rev.hallazgos] == [2, 1]  # primero código, luego fidelidad
    assert [v["slide"] for v in rev.verificaciones] == [1, 2]
    assert revisor.todas_las_verificaciones() == rev.verificaciones


def test_alcance_limita_la_fidelidad_pero_no_el_codigo():
    revisor, llamadas = fabricar_revisor()
    correr(revisor(estado_base(), {2}))
    assert llamadas["codigo"] == [{1, 2}] and llamadas["fidelidad"] == [({2}, "pedir")]


def test_sin_alcance_revisa_todos_los_slides():
    revisor, llamadas = fabricar_revisor()
    correr(revisor(estado_base(), None))
    assert llamadas["fidelidad"][0][0] == {1, 2}


def test_alcance_sin_slides_no_llama_al_llm():
    revisor, llamadas = fabricar_revisor()
    rev = correr(revisor(estado_base(), {99}))
    assert llamadas["fidelidad"] == [] and rev.verificaciones == []


def test_reemplaza_verificaciones_del_slide_revisado_y_conserva_las_demas():
    ronda = {"n": 0}

    def fidelidad(textos):
        ronda["n"] += 1
        return ([], [Afirmacion(t.numero, f"v{ronda['n']}") for t in textos])

    revisor, _ = fabricar_revisor(fidelidad=fidelidad)
    correr(revisor(estado_base(), None))
    correr(revisor(estado_base(), {1}))
    vigentes = {v["slide"]: v["payload"]["veredicto"] for v in revisor.todas_las_verificaciones()}
    assert vigentes == {1: "v2", 2: "v1"}


# ---------- Redactor: correcciones en el prompt ----------


def argumentos_prompt():
    """Argumentos mínimos de construir_mensajes."""
    slide = {"numero": 1, "rol": "gancho"}
    fragmentos = [SimpleNamespace(indice=0, texto="texto de la fuente")]
    return {"fuente": {"idioma_salida": "es"}}, brief(), slide, [("titulo", 60)], fragmentos


@pytest.fixture(autouse=True)
def prompt_falso(monkeypatch):
    """Estas pruebas no dependen del archivo redactor.md: el prompt fijo se simula."""
    monkeypatch.setattr("app.agentes.redactor.cargar_prompt", lambda nombre: "PROMPT_FIJO")


def test_prompt_sin_correcciones_no_cambia():
    mensajes = construir_mensajes(*argumentos_prompt())
    assert "Correcciones" not in mensajes[1]["content"]
    assert mensajes[1]["content"].endswith("texto de la fuente")


def test_prompt_con_correcciones_las_agrega_al_final():
    mensajes = construir_mensajes(*argumentos_prompt(), correcciones=("quita la cifra", "acorta"))
    contenido = mensajes[1]["content"]
    assert contenido.index("Fragmentos de la fuente") < contenido.index("Correcciones requeridas")
    assert contenido.endswith("- quita la cifra\n- acorta")
    assert mensajes[0]["content"] == construir_mensajes(*argumentos_prompt())[0]["content"]  # el prefijo no cambia


# ---------- Ciclo completo con los adaptadores ----------


def test_ciclo_completo_corrige_el_slide_y_aprueba():
    def fidelidad(textos):
        malos = [t.numero for t in textos if t.campos["titulo"] == "MALO"]
        return [hallazgo_final(n, evidencia="cifra inventada") for n in malos], [Afirmacion(t.numero) for t in textos]

    revisor, llamadas = fabricar_revisor(fidelidad=fidelidad)
    estado = EstadoCarrusel({1: texto(1, "MALO"), 2: texto(2)}, brief())
    emisor = Emisor()
    res = correr(ejecutar_ciclo(estado, revisar=revisor, corregir=corrector(RedactorFalso()), emitir=emisor))
    tipos = [e["tipo"] for e in emisor.eventos]
    assert (res.estado_final, res.rondas, res.corregidos) == ("aprobado", 2, ["h1"])
    assert res.estado.textos[1].campos["titulo"] == "reescrito"
    # Primera revisión: todo; segunda: solo el slide corregido.
    assert [c[0] for c in llamadas["fidelidad"]] == [{1, 2}, {1}]
    assert tipos.count("hallazgo_abierto") == 1 and tipos.count("hallazgo_corregido") == 1
    assert tipos.count("verificacion_fidelidad") == 3