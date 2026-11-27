"""El asesor sin red: protección de datos, respaldo, lo que puede marcar y cómo afecta al semáforo."""
import asyncio
import json

import httpx
import pytest

from app import config
from app.agentes.asesor import asesorar, frases_a_revisar, mensaje_usuario
from app.agentes.cliente_asesor import AsesorNoDisponible, ClienteAsesor
from app.api import rutas
from app.events.validador import comprobar_evento
from app.main import app
from app.runs.aprobacion import Decision
from app.runs.semaforo import informe
from tests.test_rutas import ajustes, cliente_http, correr, falsos, kit_de_prueba, registro  # noqa: F401
from tests.test_rutas_aprobacion import _post, _run_esperando

MODELOS = ("@cf/prueba/principal", "@cf/prueba/respaldo")
CUENTA = "0" * 31 + "a"
FRASES = frases_a_revisar(
    {(1, "titulo"): "El taller dura tres horas.", (1, "cuerpo"): "Es gratis. Da un certificado.",
     (6, "fuente_atribucion"): "Folleto"},
    {(1, "titulo"), (1, "cuerpo")},
)


def _ok(juicios, fin="stop", texto=None):
    contenido = texto if texto is not None else json.dumps({"juicios": juicios})
    return 200, {"choices": [{"finish_reason": fin, "message": {"content": contenido}}]}


def _juicio(frase, problema=False, slide=1, **extra):
    return {"slide": slide, "frase": frase, "problema": problema, **extra}


class CloudflareFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.pedidos: list[dict] = []
        self.direcciones: list[str] = []

    async def __call__(self, url, cabeceras, cuerpo, timeout):
        self.pedidos.append(cuerpo)
        self.direcciones.append(url)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _cliente(*respuestas):
    red = CloudflareFalso(*respuestas)
    return ClienteAsesor("clave-secreta", MODELOS, red, CUENTA), red


def _asesorar(*respuestas):
    cliente, red = _cliente(*respuestas)
    return asyncio.run(asesorar(cliente, FRASES, {1: ("El taller dura dos horas.",)})), red


# ---------------------------- qué se envía ----------------------------

def test_los_textos_solo_van_a_cloudflare_tambien_con_el_respaldo():
    _, red = _asesorar((429, {}), _ok([_juicio(1)]))
    assert [p["model"] for p in red.pedidos] == list(MODELOS)
    assert set(red.direcciones) == {f"https://api.cloudflare.com/client/v4/accounts/{CUENTA}/ai/v1/chat/completions"}


def test_un_modelo_que_no_aloja_cloudflare_no_recibe_nada():
    red = CloudflareFalso(_ok([_juicio(1)]))
    cliente = ClienteAsesor("k", ("openai/gpt-de-terceros", "@cf/prueba/respaldo"), red, CUENTA)
    assert asyncio.run(asesorar(cliente, FRASES, {}))["modelo"] == "@cf/prueba/respaldo"
    assert [p["model"] for p in red.pedidos] == ["@cf/prueba/respaldo"]


@pytest.mark.parametrize("cuenta", ["", "tu_id", "../otra", "a" * 31, "a" * 32 + "/x"])
def test_una_cuenta_mal_escrita_no_llega_a_la_direccion(cuenta):
    red = CloudflareFalso()
    with pytest.raises(AsesorNoDisponible, match="CLOUDFLARE_ACCOUNT_ID"):
        asyncio.run(asesorar(ClienteAsesor("k", MODELOS, red, cuenta), FRASES, {}))
    assert red.pedidos == []


def test_se_envian_las_frases_del_redactor_numeradas_y_sus_fragmentos():
    texto = mensaje_usuario(FRASES, {1: ("El taller dura dos horas.",)})
    assert "1. [titulo] El taller dura tres horas." in texto and "3. [cuerpo] Da un certificado." in texto
    assert "[F1] El taller dura dos horas." in texto
    assert "Folleto" not in texto  # lo que escribió la persona no se manda


def test_los_modelos_configurados_son_los_dos_que_se_eligieron():
    assert config.ASESOR_MODELOS == ("@cf/google/gemma-4-26b-a4b-it", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")


# ---------------------------- respaldo y fallas ----------------------------

@pytest.mark.parametrize("falla", [
    (429, {}), (404, {}), (503, {}), httpx.ReadTimeout("t"), _ok([], texto="no es json"), _ok([_juicio(1)], fin="length"),
    _ok([_juicio(99)]), (200, {}),
], ids=["429", "404", "503", "timeout", "no_json", "cortada", "sin_juicios_validos", "vacia"])
def test_si_el_principal_falla_responde_el_respaldo(falla):
    payload, red = _asesorar(falla, _ok([_juicio(1)]))
    assert payload["modelo"] == MODELOS[1] and len(red.pedidos) == 2


def test_si_fallan_los_dos_no_esta_disponible_y_no_prueba_otros():
    cliente, red = _cliente((429, {}), (404, {}))
    with pytest.raises(AsesorNoDisponible, match="no está disponible") as e:
        asyncio.run(asesorar(cliente, FRASES, {}))
    assert len(red.pedidos) == 2 and "clave-secreta" not in e.value.mensaje and CUENTA not in e.value.mensaje


def test_un_error_de_credenciales_corta_sin_probar_el_respaldo():
    cliente, red = _cliente((401, {}))
    with pytest.raises(AsesorNoDisponible, match="401"):
        asyncio.run(asesorar(cliente, FRASES, {}))
    assert len(red.pedidos) == 1


def test_sin_clave_no_sale_ningun_pedido():
    red = CloudflareFalso()
    with pytest.raises(AsesorNoDisponible, match="CLOUDFLARE_API_KEY_TOKEN"):
        asyncio.run(asesorar(ClienteAsesor("", MODELOS, red, CUENTA), FRASES, {}))
    assert red.pedidos == []


# ---------------------------- qué puede decir ----------------------------

def test_la_frase_de_la_alerta_la_pone_el_codigo_y_cuenta_lo_revisado():
    juicios = [_juicio(1, True, explicacion="Dura dos.", sugerencia="reescribir", texto="otra cosa"), _juicio(2),
               _juicio(3, True, sugerencia="borrar_todo"), _juicio(4, True), _juicio(1, True, slide=9), "basura"]
    payload, _ = _asesorar(_ok(juicios))
    assert (payload["frases_revisadas"], payload["frases_totales"]) == (3, 3)
    primera, segunda = payload["alertas"]
    assert (primera["frase"], primera["explicacion"]) == ("El taller dura tres horas.", "Dura dos.")
    assert segunda["sugerencia"] == "reescribir" and "sin explicar" in segunda["explicacion"]


def test_si_juzga_dos_veces_una_frase_gana_la_alerta():
    payload, _ = _asesorar(_ok([_juicio(1, True, explicacion="mal"), _juicio(1, False)]))
    assert len(payload["alertas"]) == 1


# ---------------------------- semáforo ----------------------------

def _evento(seq, tipo, slide=None, **payload):
    return {"seq": seq, "tipo": tipo, "payload": payload, **({} if slide is None else {"slide": slide})}


def _asesoria(seq, *slides):
    return _evento(seq, "asesoria", modelo="m", frases_revisadas=2, frases_totales=2,
                   alertas=[{"slide": n, "frase": "Frase.", "explicacion": "e", "sugerencia": "quitar"} for n in slides])


VERDE = [
    _evento(1, "texto_propuesto", 1, campo="titulo"), _evento(2, "escribir_texto", 1, campo="titulo"),
    _evento(3, "verificacion_fidelidad", 1, veredicto="respaldada", afirmacion="Frase."),
]


def test_una_alerta_pone_en_rojo_un_slide_verde():
    assert informe(VERDE)["visto_bueno"] and informe(VERDE)["asesor"] is None
    r = informe([*VERDE, _asesoria(4, 1)])
    assert not r["visto_bueno"] and "Alerta del asesor" in r["slides"][0]["motivos"][0]


def test_insistir_hasta_que_no_diga_nada_no_quita_la_alerta():
    r = informe([*VERDE, _asesoria(4, 1), _asesoria(5)])
    assert not r["visto_bueno"] and r["asesor"]["consultas"] == 2


def test_sin_alertas_no_pone_en_verde_lo_que_estaba_en_rojo():
    sin_veredicto = [e for e in VERDE if e["tipo"] != "verificacion_fidelidad"]
    assert not informe([*sin_veredicto, _asesoria(4)])["visto_bueno"]


def test_al_reescribir_el_texto_la_alerta_vieja_deja_de_valer():
    nuevo = [*VERDE, _asesoria(4, 1), _evento(5, "escribir_texto", 1, campo="titulo"),
             _evento(6, "verificacion_fidelidad", 1, veredicto="respaldada", afirmacion="Otra.")]
    assert informe(nuevo)["visto_bueno"]


# ---------------------------- endpoint ----------------------------

def _consultar(registro, cliente, antes=None):
    """Pide consejo sobre un run en verde que espera decisión; devuelve (ejecución, respuestas)."""
    app.dependency_overrides[rutas.obtener_cliente_asesor] = lambda: cliente

    async def escenario():
        ej = await _run_esperando(registro)
        if antes:
            antes(ej)
        async with cliente_http() as c:
            return ej, await c.post(f"/api/runs/{ej.run_id}/asesor")

    try:
        return correr(escenario())
    finally:
        app.dependency_overrides.pop(rutas.obtener_cliente_asesor, None)


def test_el_consejo_queda_como_evento_valido_y_bloquea_la_aprobacion_normal(falsos, registro):
    cliente, red = _cliente(_ok([_juicio(1, True, explicacion="La fuente no lo dice.")]))
    ej, r = _consultar(registro, cliente)
    assert r.status_code == 200 and not r.json()["visto_bueno"] and r.json() == informe(ej.eventos)
    evento = ej.eventos[-1]
    assert (evento["tipo"], evento["agente"]) == ("asesoria", "asesor") and comprobar_evento(evento) == []
    assert ej.esperando_decision and not ej.asesorando
    assert correr(_post(ej.run_id, json={})).status_code == 422


def test_si_no_esta_disponible_responde_503_y_no_cambia_nada(falsos, registro):
    cliente, _ = _cliente((429, {}), (429, {}))
    ej, r = _consultar(registro, cliente)
    assert r.status_code == 503 and informe(ej.eventos)["visto_bueno"] and not ej.asesorando


def test_si_la_persona_decide_mientras_tanto_el_consejo_no_se_registra(falsos, registro):
    ejecuciones = []

    async def enviar(*args):
        ejecuciones[0].registrar_decision(Decision())
        return _ok([_juicio(1, True)])

    ej, r = _consultar(registro, ClienteAsesor("k", MODELOS, enviar, CUENTA), antes=ejecuciones.append)
    assert r.status_code == 409 and not any(e["tipo"] == "asesoria" for e in ej.eventos)


@pytest.mark.parametrize("preparar, parte", [
    (lambda ej: ej.registrar_decision(Decision()), "mientras el run espera"),
    (lambda ej: setattr(ej, "asesorando", True), "ya está revisando"),
])
def test_no_se_consulta_fuera_de_turno(falsos, registro, preparar, parte):
    cliente, red = _cliente()
    _, r = _consultar(registro, cliente, antes=preparar)
    assert r.status_code == 409 and parte in r.json()["motivos"][0] and red.pedidos == []


def test_hay_un_tope_de_consultas_por_run(falsos, registro, monkeypatch):
    monkeypatch.setattr(config, "ASESOR_MAX_CONSULTAS", 0)
    cliente, red = _cliente()
    _, r = _consultar(registro, cliente)
    assert r.status_code == 409 and red.pedidos == []
