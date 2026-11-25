"""Pruebas del orquestador real (sin red ni LLM).

Usan la `Ejecucion` real, que valida CADA evento contra los contratos reales, y el ciclo de
corrección, los adaptadores y el director de arte reales. Solo los agentes con LLM (estratega,
redactor, revisor de fidelidad) y el revisor de código se reemplazan por falsos.
"""

import asyncio
import hashlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.agentes.cliente_llm import LLMError
from app.agentes.comun import AgenteError
from app.agentes.redactor import TextoSlide, campos_del_redactor
from app.fuentes.cargador_fuente import FuenteCargada, fragmentar
from app.runs.orquestador_real import Agentes, ejecutar_run_real
from app.runs.registro import Ejecucion, EstadoRun

RUN_ID = "run_test0001"
KIT = {"paleta": {"fondo": "#112233"}}

ENTRADA = {
    "destino": {"red": "instagram"},
    "fuente": {"tipo": "documento", "atribucion": "Autora de prueba", "licencia": "CC BY 4.0", "idioma_salida": "es"},
}


# ---------------------------------------------------------------------------
# Datos de prueba
# ---------------------------------------------------------------------------

def _campo(nombre, origen="llm", maximo=80):
    """Campo de texto de la ficha, con llaves dobles como en las fichas reales."""
    return {"nombre": "{{" + nombre + "}}", "tipo": "texto", "origen_valor": origen, "longitud_max": maximo}


def resolucion(modo="auto"):
    """Resolución mínima de 5 slides: 4 con campos del redactor y el de fuentes con campos calculados."""
    roles = ["gancho", "segundo_gancho", "desarrollo", "cierre"]
    slides = [
        {"numero": i + 1, "rol": rol, "campos": [_campo("titulo"), _campo("cuerpo")]}
        for i, rol in enumerate(roles)  # un slide por rol, con título y cuerpo para el LLM
    ]
    slides.append({"numero": 5, "rol": "fuentes", "campos": [_campo("fuente_atribucion", "usuario"), _campo("sello", "calculado")]})
    return SimpleNamespace(
        ficha={"tipo_mensaje": "lista_de_pasos", "slides": slides},
        num_slides=5, plantilla_id="plantilla_demo", modo_plantilla=modo,
    )


def fuente():
    """Fuente cargada mínima, con huella real."""
    texto = "Primer párrafo de la fuente.\n\nSegundo párrafo de la fuente."
    return FuenteCargada(
        referencia="demo.md", texto=texto, sha256=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        caracteres=len(texto), fragmentos=fragmentar(texto, 30),
    )


@dataclass(frozen=True, eq=False)
class BriefFalso:
    """Brief mínimo con la interfaz que usan el orquestador y los adaptadores."""

    angulo: str = "ángulo de prueba"
    tono: str = "tono de prueba"
    fragmentos_por_slide: dict = None

    def payload_evento(self, resolucion):
        """Payload válido de brief_emitido a partir de la ficha."""
        ficha = resolucion.ficha
        return {
            "angulo": self.angulo, "tono": self.tono, "num_slides": resolucion.num_slides,
            "tipo_mensaje": ficha["tipo_mensaje"], "roles": [s["rol"] for s in ficha["slides"]],
        }


class Afirmacion:
    """Afirmación falsa que sabe convertirse en el evento de verificación."""

    def __init__(self, slide, sufijo, clasificacion="factual", veredicto="respaldada"):
        self.slide, self.sufijo = slide, sufijo
        self.clasificacion, self.veredicto = clasificacion, veredicto

    def a_evento(self):
        """Entrada {"slide", "payload"} como la entrega el revisor real."""
        cita = {"fragmento": "Primer", "inicio": 0, "fin": 6} if self.veredicto == "respaldada" else None
        return {
            "slide": self.slide,
            "payload": {
                "afirmacion_id": f"a{self.slide}{self.sufijo}", "afirmacion": f"Afirmación del slide {self.slide}",
                "clasificacion": self.clasificacion, "veredicto": self.veredicto, "cita": cita, "motivo": "motivo de prueba",
            },
        }


def hallazgo(slide, gravedad="bloqueante", responsable="redactor"):
    """Hallazgo en la forma {"slide", "payload"} (sin hallazgo_id: lo asigna el ciclo)."""
    return {
        "slide": slide,
        "payload": {
            "dimension": "fidelidad", "gravedad": gravedad, "evidencia": "cifra inventada",
            "explicacion": "La cifra no está en la fuente.", "accion": "Quitar la cifra.", "responsable": responsable,
        },
    }


def fabricar_agentes(malos=(), hallazgo_fijo=None, error_redactor=None, error_brief=None, texto_largo=False, brief_lento=False):
    """Agentes falsos. `malos`: slides que el redactor escribe mal la primera vez (título "MALO").

    `hallazgo_fijo`: función slide -> hallazgo que el revisor devuelve siempre (para casos sin corrección).
    `brief_lento`: el estratega no responde nunca (sirve para probar el tope global de tiempo).
    """
    registro = {"redactor": [], "fidelidad": []}

    async def generar_brief(cliente, entrada, resolucion_, fuente_):
        """Brief falso; si `error_brief` está, lo lanza; si `brief_lento`, se queda esperando."""
        if error_brief:
            raise error_brief
        if brief_lento:
            await asyncio.sleep(3600)  # el tope global lo corta mucho antes
        return BriefFalso(fragmentos_por_slide={})

    async def redactar(cliente, entrada, resolucion_, fuente_, brief, numero, correcciones=()):
        """Redactor falso: llena los campos del slide; "MALO" si toca, "reescrito" si hay correcciones."""
        registro["redactor"].append((numero, tuple(correcciones)))
        if error_redactor:
            raise error_redactor
        slide = next(s for s in resolucion_.ficha["slides"] if s["numero"] == numero)
        campos = {nombre: f"{nombre} {numero}" for nombre, _ in campos_del_redactor(slide)}
        # Primera redacción mala; después de una corrección, texto nuevo.
        if campos and numero in malos and not correcciones:
            campos["titulo"] = "MALO"
        elif campos and correcciones:
            campos["titulo"] = "reescrito"
        if campos and texto_largo:
            campos["titulo"] = "x" * 401  # supera el máximo del contrato
        return TextoSlide(numero, campos, (), "modelo", False)

    async def revisar_fidelidad(cliente, brief, fuente_, textos, pedir=None):
        """Revisor falso: una afirmación factual respaldada por slide con texto y una opinión en el slide 1."""
        registro["fidelidad"].append({t.numero for t in textos})
        hallazgos, afirmaciones = [], []
        for t in textos:  # un recorrido por los slides revisados
            # El slide de fuentes no tiene campos del redactor: no hay nada que afirmar.
            if not t.campos:
                continue
            afirmaciones.append(Afirmacion(t.numero, 0))
            if t.numero == 1:
                afirmaciones.append(Afirmacion(1, 1, "opinion_cta", "no_aplica"))
            if t.campos.get("titulo") == "MALO":
                hallazgos.append(hallazgo(t.numero))
            elif hallazgo_fijo and (h := hallazgo_fijo(t.numero)):
                hallazgos.append(h)
        return SimpleNamespace(afirmaciones=afirmaciones, hallazgos=hallazgos, sello=None)

    agentes = Agentes(
        generar_brief=generar_brief, redactar=redactar,
        revisar_codigo=lambda resolucion_, kit, textos, entrada: [],
        revisar_fidelidad=revisar_fidelidad,
        con_ids=lambda hs, primer_numero=1: list(hs),
    )
    return agentes, registro


def correr(agentes, modo="auto", esperar_cancelacion=False, timeout_seg=None):
    """Ejecuta el orquestador con una Ejecucion real y devuelve la Ejecucion resultante.

    `timeout_seg` es el tope global del run; sin valor se usa el de config (600 s), que estas pruebas no alcanzan.
    """

    async def principal():
        ejecucion = Ejecucion(RUN_ID, ENTRADA, resolucion(modo), "real")
        # La cancelación se propaga: la prueba la captura para poder inspeccionar la ejecución.
        if esperar_cancelacion:
            with pytest.raises(asyncio.CancelledError):
                await ejecutar_run_real(ejecucion, fuente(), "cliente", KIT, agentes, timeout_seg)
        else:
            await ejecutar_run_real(ejecucion, fuente(), "cliente", KIT, agentes, timeout_seg)
        return ejecucion

    return asyncio.run(principal())


def tipos(ejecucion):
    """Lista de tipos de evento en orden de emisión."""
    return [e["tipo"] for e in ejecucion.eventos]


def de_tipo(ejecucion, tipo):
    """Eventos de un tipo."""
    return [e for e in ejecucion.eventos if e["tipo"] == tipo]


# ---------------------------------------------------------------------------
# Flujo feliz
# ---------------------------------------------------------------------------

def test_flujo_feliz_emite_en_orden_y_termina_aprobada():
    agentes, _ = fabricar_agentes()
    ej = correr(agentes)
    t = tipos(ej)
    assert t[:4] == ["run_iniciada", "fuente_indexada", "brief_emitido", "plantilla_elegida"]
    assert t[-2:] == ["aprobacion_solicitada", "run_finalizada"]  # 8F: la aprobación se pide justo antes del cierre
    assert ej.estado == EstadoRun.TERMINADA and ej.fallo is None
    assert [e["seq"] for e in ej.eventos] == list(range(1, len(ej.eventos) + 1))  # seq consecutivo
    assert {e["origen"] for e in ej.eventos} == {"real"}
    # 4 slides con 2 campos: 8 textos propuestos y escritos; un fondo por slide.
    assert (t.count("texto_propuesto"), t.count("escribir_texto"), t.count("colocar_fondo")) == (8, 8, 5)
    # Todo texto propuesto va antes del arte, y el arte antes de las verificaciones.
    assert max(i for i, x in enumerate(t) if x == "texto_propuesto") < min(i for i, x in enumerate(t) if x == "colocar_fondo")
    assert max(i for i, x in enumerate(t) if x == "escribir_texto") < min(i for i, x in enumerate(t) if x == "verificacion_fidelidad")


def test_run_finalizada_trae_estado_sello_y_referencia_al_ledger():
    agentes, _ = fabricar_agentes()
    final = de_tipo(correr(agentes), "run_finalizada")[0]["payload"]
    # 4 factuales respaldadas; la opinión del slide 1 queda fuera del total.
    assert final == {
        "estado_final": "aprobada",
        "fact_ledger_ref": f"{RUN_ID}/fact_ledger",
        "sello": {"afirmaciones_respaldadas": 4, "afirmaciones_totales": 4},
    }


def test_run_iniciada_declara_la_fuente_verificada_y_fuente_indexada_usa_su_huella():
    agentes, _ = fabricar_agentes()
    ej = correr(agentes)
    iniciada = de_tipo(ej, "run_iniciada")[0]["payload"]
    assert iniciada["verificacion"] == "verificada" and iniciada["num_slides"] == 5
    assert iniciada["fuente"] == {"tipo": "documento", "atribucion": "Autora de prueba", "licencia": "CC BY 4.0"}
    f = fuente()
    assert de_tipo(ej, "fuente_indexada")[0]["payload"] == {
        "num_fragmentos": len(f.fragmentos), "num_caracteres": f.caracteres, "sha256": f.sha256,
    }


def test_plantilla_fijada_por_el_usuario_registra_el_motivo():
    agentes, _ = fabricar_agentes()
    payload = de_tipo(correr(agentes, modo="fijo"), "plantilla_elegida")[0]["payload"]
    assert payload["modo"] == "fijo" and payload["motivo"] == "Se respetó la plantilla fijada por el usuario"


def test_el_redactor_trabaja_los_slides_en_secuencia():
    agentes, registro = fabricar_agentes()
    correr(agentes)
    assert [numero for numero, _ in registro["redactor"]] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Aprobación solicitada (8F)
# ---------------------------------------------------------------------------

def test_aprobacion_solicitada_aprobada_va_antes_de_run_finalizada_y_el_run_no_espera():
    agentes, _ = fabricar_agentes()
    ej = correr(agentes)
    aprobacion = de_tipo(ej, "aprobacion_solicitada")
    assert len(aprobacion) == 1  # se emite una sola vez, también en un run aprobado
    assert aprobacion[0]["agente"] == "sistema"
    assert aprobacion[0]["payload"] == {
        "estado_revision": "aprobada",
        "hallazgos_abiertos": 0,
        "sello": {"afirmaciones_respaldadas": 4, "afirmaciones_totales": 4},
    }
    # Inmediatamente antes del cierre, y el run termina solo (no queda en espera de la persona).
    assert ej.eventos[-2]["seq"] == aprobacion[0]["seq"] and ej.eventos[-1]["tipo"] == "run_finalizada"
    assert ej.estado == EstadoRun.TERMINADA


def test_aprobacion_solicitada_con_menor_abierto_cuenta_el_hallazgo():
    agentes, _ = fabricar_agentes(hallazgo_fijo=lambda n: hallazgo(2, "menor") if n == 2 else None)
    ej = correr(agentes)
    payload = de_tipo(ej, "aprobacion_solicitada")[0]["payload"]
    assert payload["estado_revision"] == "aprobada_con_advertencias" and payload["hallazgos_abiertos"] == 1


def test_aprobacion_solicitada_escalada_a_humano_y_coincide_con_el_estado_final():
    agentes, _ = fabricar_agentes(
        hallazgo_fijo=lambda n: hallazgo(2, "bloqueante", "director_arte") if n == 2 else None
    )
    ej = correr(agentes)
    payload = de_tipo(ej, "aprobacion_solicitada")[0]["payload"]
    assert payload["estado_revision"] == "requiere_humano" and payload["hallazgos_abiertos"] == 1
    # La revisión pedida y el estado final del run dicen lo mismo.
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == payload["estado_revision"]
    assert ej.estado == EstadoRun.TERMINADA


# ---------------------------------------------------------------------------
# Ciclo de corrección
# ---------------------------------------------------------------------------

def test_reescritura_emite_texto_propuesto_con_causa_y_vuelve_a_escribir_solo_ese_slide():
    agentes, registro = fabricar_agentes(malos={1})
    ej = correr(agentes)
    abierto = de_tipo(ej, "hallazgo_abierto")[0]
    propuestos = [e for e in de_tipo(ej, "texto_propuesto") if "causa" in e]
    # Los dos campos del slide 1, apuntando al hallazgo_abierto original.
    assert [(e["slide"], e["causa"], e["payload"]["campo"]) for e in propuestos] == [
        (1, abierto["seq"], "titulo"), (1, abierto["seq"], "cuerpo"),
    ]
    assert propuestos[0]["payload"]["texto"] == "reescrito"
    t = tipos(ej)
    # Dos escribir_texto más (solo el slide 1) y ningún colocar_fondo nuevo.
    assert (t.count("escribir_texto"), t.count("colocar_fondo")) == (10, 5)
    ultimos = [e for e in ej.eventos if e["tipo"] == "escribir_texto" and e["seq"] > propuestos[-1]["seq"]]
    assert [e["slide"] for e in ultimos] == [1, 1]
    # El hallazgo se cierra y el run aprueba; la segunda revisión solo mira el slide corregido.
    corregido = de_tipo(ej, "hallazgo_corregido")[0]
    assert corregido["causa"] == abierto["seq"] and corregido["payload"]["resultado"] == "corregido"
    assert registro["fidelidad"] == [{1, 2, 3, 4, 5}, {1}]
    final = de_tipo(ej, "run_finalizada")[0]["payload"]
    assert final["estado_final"] == "aprobada"
    # El sello usa las verificaciones vigentes: 4 factuales, sin duplicar las del slide 1.
    assert final["sello"] == {"afirmaciones_respaldadas": 4, "afirmaciones_totales": 4}
    # El hallazgo ya corregido no cuenta como abierto al pedir la aprobación.
    assert de_tipo(ej, "aprobacion_solicitada")[0]["payload"]["hallazgos_abiertos"] == 0


def test_hallazgo_menor_abierto_sale_con_advertencias():
    agentes, _ = fabricar_agentes(hallazgo_fijo=lambda n: hallazgo(2, "menor") if n == 2 else None)
    ej = correr(agentes)
    assert ej.estado == EstadoRun.TERMINADA
    assert de_tipo(ej, "hallazgo_abierto")[0]["payload"]["gravedad"] == "menor"
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "aprobada_con_advertencias"


def test_hallazgo_sin_correccion_automatica_escala_a_humano_sin_gastar_otra_revision():
    agentes, registro = fabricar_agentes(
        hallazgo_fijo=lambda n: hallazgo(2, "bloqueante", "director_arte") if n == 2 else None
    )
    ej = correr(agentes)
    assert ej.estado == EstadoRun.TERMINADA  # escalar a humano no es un fallo del run
    assert de_tipo(ej, "run_finalizada")[0]["payload"]["estado_final"] == "requiere_humano"
    assert not [e for e in de_tipo(ej, "texto_propuesto") if "causa" in e]  # nadie reescribió nada
    assert registro["fidelidad"] == [{1, 2, 3, 4, 5}]  # sin_cambios: no hubo re-revisión


# ---------------------------------------------------------------------------
# Errores y cancelación
# ---------------------------------------------------------------------------

def test_error_de_agente_corta_el_run_con_su_mensaje():
    agentes, _ = fabricar_agentes(error_redactor=AgenteError("salida_invalida", "El redactor devolvió una salida inválida."))
    ej = correr(agentes)
    assert ej.estado == EstadoRun.FALLIDA
    assert ej.fallo == {"nombre": "run_error", "datos": {"motivos": ["El redactor devolvió una salida inválida."]}}
    assert "run_finalizada" not in tipos(ej)
    assert "aprobacion_solicitada" not in tipos(ej)  # un run fallido no pide aprobación


def test_error_del_cliente_llm_corta_el_run_con_su_mensaje():
    agentes, _ = fabricar_agentes(error_brief=LLMError("sin_cupo", "No hubo cupo de tokens a tiempo; reintenta en un minuto."))
    ej = correr(agentes)
    assert ej.estado == EstadoRun.FALLIDA
    assert ej.fallo["datos"]["motivos"] == ["No hubo cupo de tokens a tiempo; reintenta en un minuto."]
    assert tipos(ej) == ["run_iniciada", "fuente_indexada"]  # falló antes del brief


def test_error_inesperado_no_filtra_detalles_al_cliente():
    agentes, _ = fabricar_agentes(error_redactor=RuntimeError("clave-secreta"))
    ej = correr(agentes)
    mensaje = ej.fallo["datos"]["motivos"][0]
    assert ej.estado == EstadoRun.FALLIDA and "RuntimeError" in mensaje and "clave-secreta" not in mensaje


def test_cancelacion_avisa_a_los_lectores_y_se_propaga():
    agentes, _ = fabricar_agentes(error_redactor=asyncio.CancelledError())
    ej = correr(agentes, esperar_cancelacion=True)
    assert ej.estado == EstadoRun.FALLIDA
    assert "se canceló" in ej.fallo["datos"]["motivos"][0]


def test_texto_fuera_del_contrato_corta_con_evento_invalido():
    agentes, _ = fabricar_agentes(texto_largo=True)
    ej = correr(agentes)
    assert ej.estado == EstadoRun.FALLIDA
    assert ej.fallo["nombre"] == "evento_invalido" and ej.fallo["datos"]["tipo"] == "texto_propuesto"
    assert "run_finalizada" not in tipos(ej)


# ---------------------------------------------------------------------------
# Tope global de tiempo (8F)
# ---------------------------------------------------------------------------

def test_tope_global_corta_un_run_colgado_con_run_error_visible():
    agentes, _ = fabricar_agentes(brief_lento=True)
    ej = correr(agentes, timeout_seg=0.05)
    assert ej.estado == EstadoRun.FALLIDA  # libera el cupo de MAX_RUNS_ACTIVOS
    assert ej.fallo["nombre"] == "run_error"
    assert "tiempo máximo" in ej.fallo["datos"]["motivos"][0]
    assert tipos(ej) == ["run_iniciada", "fuente_indexada"]  # se colgó en el estratega
    assert "run_finalizada" not in tipos(ej)


def test_un_run_dentro_del_tope_termina_normal():
    agentes, _ = fabricar_agentes()
    ej = correr(agentes, timeout_seg=30)
    assert ej.estado == EstadoRun.TERMINADA and ej.fallo is None


def test_tope_cero_o_negativo_desactiva_el_limite():
    agentes, _ = fabricar_agentes()
    ej = correr(agentes, timeout_seg=0)
    assert ej.estado == EstadoRun.TERMINADA and tipos(ej)[-1] == "run_finalizada"


def test_la_cancelacion_externa_no_se_confunde_con_el_tope():
    # Aunque haya tope, una cancelación del servidor se propaga y avisa "se canceló", no "tiempo máximo".
    agentes, _ = fabricar_agentes(error_redactor=asyncio.CancelledError())
    ej = correr(agentes, esperar_cancelacion=True, timeout_seg=30)
    assert ej.estado == EstadoRun.FALLIDA and "se canceló" in ej.fallo["datos"]["motivos"][0]


# ---------------------------------------------------------------------------
# Guardia de roles
# ---------------------------------------------------------------------------

def test_los_roles_que_usan_los_agentes_existen_en_el_cliente():
    """Evita el error `rol_invalido` en el primer llamado real (por ejemplo, un rol "revisor" inexistente)."""
    from app.agentes.cliente_llm import ClienteGroq
    from app.agentes.revisor_fidelidad import ROL_REVISOR

    modelos = ClienteGroq(sdk=object()).modelos  # sdk falso: no hace falta clave ni red
    for rol in ("estratega", "redactor", ROL_REVISOR):  # cada rol que piden los agentes
        assert rol in modelos