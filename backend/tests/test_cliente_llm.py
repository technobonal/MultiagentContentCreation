"""Pruebas del cliente LLM: SDK falso, reloj falso y sin esperas reales (sin red, sin cuota)."""

import asyncio
from types import SimpleNamespace

import groq
import httpx
import pytest

from app.agentes.cliente_llm import ClienteGroq, LimitadorTokens, LLMError, estimar_tokens

REDACTOR, REV_A, REV_B = "m-redactor", "m-rev-a", "m-rev-b"
MODELOS = {"estratega": REDACTOR, "redactor": REDACTOR, "revisor_a": REV_A, "revisor_b": REV_B}
ORDEN = [REDACTOR, REV_A, REV_B]
MSGS = [{"role": "user", "content": "hola"}]


def correr(coro):
    """Ejecuta una corrutina desde una prueba síncrona (no depende de plugins async)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------- dobles de prueba

class RelojFalso:
    """Reloj controlable a mano; `dormir` lo adelanta sin esperar de verdad."""

    def __init__(self):
        self.t = 1000.0
        self.dormidos = []

    def __call__(self):
        return self.t

    async def dormir(self, seg):
        self.dormidos.append(seg)
        self.t += seg


def _resp(texto="{}", finish="stop", tokens=50):
    """Respuesta falsa con la forma mínima del SDK de Groq."""
    usage = SimpleNamespace(total_tokens=tokens, model_dump=lambda: {"total_tokens": tokens})
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=texto), finish_reason=finish)], usage=usage
    )


def _http(status):
    """Respuesta HTTP falsa para construir errores reales del SDK."""
    return httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com/x"))


def _err(status):
    """Error del SDK de Groq con el tipo que corresponde a ese código HTTP."""
    clases = {400: groq.BadRequestError, 429: groq.RateLimitError, 500: groq.InternalServerError}
    clase = clases.get(status, groq.APIStatusError)
    return clase(f"error {status}", response=_http(status), body=None)


def _err400(mensaje):
    """400 de Groq con un mensaje concreto (para distinguir las causas del rechazo)."""
    return groq.BadRequestError(mensaje, response=_http(400), body=None)


class SDKFalso:
    """SDK falso: cada llamada consume el siguiente guion (una respuesta o una excepción)."""

    def __init__(self, *guion):
        self.guion = list(guion)
        self.llamadas = []  # kwargs de cada llamada, para comprobar qué se envió
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        paso = self.guion.pop(0)
        if callable(paso):
            return await paso()
        if isinstance(paso, Exception):
            raise paso
        return paso


def _cliente(sdk, reloj=None, **kw):
    """Cliente con modelos de prueba, reloj falso y los parámetros indicados."""
    reloj = reloj or RelojFalso()
    kw.setdefault("limitador", LimitadorTokens(tpm_defecto=100000, rpm_defecto=1000, reloj=reloj))
    return ClienteGroq(
        api_key="x", modelos=MODELOS, orden_fallback=ORDEN, sdk=sdk,
        reloj=reloj, dormir=reloj.dormir, max_tokens=100, **kw,
    )


# ---------------------------------------------------------------- camino feliz

def test_respuesta_normal():
    """Devuelve el texto, el modelo que respondió y el modo JSON activado."""
    sdk = SDKFalso(_resp('{"a": 1}'))
    r = correr(_cliente(sdk).completar("redactor", MSGS))
    assert r.texto == '{"a": 1}'
    assert (r.modelo, r.pedido, r.fallback) == (REDACTOR, REDACTOR, False)
    assert r.finish_reason == "stop" and r.uso == {"total_tokens": 50}
    envio = sdk.llamadas[0]
    assert envio["model"] == REDACTOR
    assert envio["response_format"] == {"type": "json_object"}
    assert envio["max_completion_tokens"] == 100


def test_sin_json_mode_no_envia_response_format():
    """json_mode=False no manda response_format."""
    sdk = SDKFalso(_resp("texto"))
    correr(_cliente(sdk).completar("redactor", MSGS, json_mode=False))
    assert "response_format" not in sdk.llamadas[0]


def test_extra_se_pasa_al_sdk():
    """Los parámetros propios de un modelo (reasoning_effort) llegan al SDK."""
    sdk = SDKFalso(_resp())
    correr(_cliente(sdk).completar("revisor_a", MSGS, extra={"reasoning_effort": "low"}))
    assert sdk.llamadas[0]["reasoning_effort"] == "low"


def test_rol_desconocido():
    """Un rol que no existe es un LLMError claro."""
    with pytest.raises(LLMError) as e:
        correr(_cliente(SDKFalso()).completar("inventado", MSGS))
    assert e.value.codigo == "rol_invalido"


def test_truncada_por_length_o_vacia():
    """finish_reason=length o texto vacío se marcan como truncada."""
    c = _cliente(SDKFalso(_resp("{", finish="length"), _resp("  ")))
    assert correr(c.completar("redactor", MSGS)).truncada is True
    assert correr(c.completar("redactor", MSGS)).truncada is True


def test_sin_clave_falla_al_construir():
    """Sin GROQ_API_KEY (y sin SDK inyectado) el cliente no se construye."""
    with pytest.raises(LLMError) as e:
        ClienteGroq(api_key="")
    assert e.value.codigo == "sin_clave"


# ---------------------------------------------------------------- JSON mode

def test_json_mode_rechazado_reintenta_sin_response_format():
    """Un 400 en modo JSON se reintenta en el mismo modelo sin response_format."""
    sdk = SDKFalso(_err(400), _resp("ok"))
    c = _cliente(sdk)
    r = correr(c.completar("redactor", MSGS))
    assert r.texto == "ok" and r.modelo == REDACTOR
    assert "response_format" in sdk.llamadas[0] and "response_format" not in sdk.llamadas[1]
    assert any("JSON" in (x.get("error") or "") for x in c.llamadas)  # quedó registrado


# --- Memoria del modo JSON por modelo (tanda 9A)

def test_json_rechazado_se_recuerda_y_no_se_repite():
    """Si el modelo rechaza el JSON y sin él responde, la llamada siguiente ya no lo envía."""
    sdk = SDKFalso(_err(400), _resp("ok1"), _resp("ok2"))
    c = _cliente(sdk)
    correr(c.completar("redactor", MSGS))  # 400 con JSON + reintento sin JSON (2 llamadas al SDK)
    assert c.modelos_sin_json == {REDACTOR}
    r = correr(c.completar("redactor", MSGS))  # ahora directo, sin response_format (1 llamada)
    assert r.texto == "ok2" and len(sdk.llamadas) == 3
    assert "response_format" not in sdk.llamadas[2]
    assert c.llamadas[-1]["json_mode"] is False  # el registro refleja que no se usó JSON


def test_json_recordado_no_afecta_a_otros_modelos():
    """Recordar que un modelo no admite JSON no apaga el JSON de los demás."""
    sdk = SDKFalso(_err(400), _resp("ok1"), _resp("ok2"))
    c = _cliente(sdk)
    correr(c.completar("redactor", MSGS))  # el redactor queda recordado
    correr(c.completar("revisor_a", MSGS))  # otro modelo: sigue enviando response_format
    assert sdk.llamadas[2]["model"] == REV_A and "response_format" in sdk.llamadas[2]
    assert c.modelos_sin_json == {REDACTOR}


def test_json_apagado_en_un_modelo_no_se_arrastra_al_fallback():
    """Si el reintento sin JSON falla técnicamente y se pasa al siguiente modelo, este recibe JSON y nada se recuerda."""
    sdk = SDKFalso(_err(400), _err(500), _resp("ok"))
    c = _cliente(sdk)
    r = correr(c.completar("redactor", MSGS))
    assert r.modelo == REV_A and r.fallback is True
    assert "response_format" in sdk.llamadas[2]  # el fallback vuelve a probar JSON
    assert c.modelos_sin_json == frozenset()  # el redactor nunca respondió sin JSON: no se recuerda


def test_400_que_tambien_falla_sin_json_no_se_atribuye_al_json():
    """Un 400 ajeno al JSON (p. ej. un parámetro inválido) falla otra vez sin JSON: error_api y sin memoria."""
    sdk = SDKFalso(_err(400), _err(400), _resp("ok"))
    c = _cliente(sdk)
    with pytest.raises(LLMError) as e:
        correr(c.completar("redactor", MSGS, extra={"reasoning_effort": "invalido"}))
    assert e.value.codigo == "error_api"
    assert c.modelos_sin_json == frozenset()
    correr(c.completar("redactor", MSGS))  # la siguiente llamada sigue enviando JSON
    assert "response_format" in sdk.llamadas[2]


def test_json_mal_generado_es_transitorio_y_no_se_recuerda():
    """Un 400 por JSON inválido del modelo se reintenta sin JSON, pero no apaga el JSON para siempre."""
    sdk = SDKFalso(_err400("Failed to generate JSON. Please adjust your prompt."), _resp("ok1"), _resp("ok2"))
    c = _cliente(sdk)
    assert correr(c.completar("redactor", MSGS)).texto == "ok1"
    assert "response_format" not in sdk.llamadas[1]  # esa llamada se reintentó sin JSON
    assert c.modelos_sin_json == frozenset()
    correr(c.completar("redactor", MSGS))
    assert "response_format" in sdk.llamadas[2]  # y la siguiente vuelve a pedir JSON


def test_400_sin_json_mode_es_error_de_api():
    """Un 400 que no es del modo JSON no se esconde con un fallback."""
    with pytest.raises(LLMError) as e:
        correr(_cliente(SDKFalso(_err(400))).completar("redactor", MSGS, json_mode=False))
    assert e.value.codigo == "error_api"


def test_error_no_tecnico_no_hace_fallback():
    """Un error que no es técnico (p. ej. ValueError) se informa y no cambia de modelo."""
    sdk = SDKFalso(ValueError("mal uso"), _resp())
    with pytest.raises(LLMError) as e:
        correr(_cliente(sdk).completar("redactor", MSGS))
    assert e.value.codigo == "error_api" and len(sdk.llamadas) == 1


# ---------------------------------------------------------------- fallback técnico

@pytest.mark.parametrize("error", [_err(500), _err(429), groq.APIConnectionError(request=httpx.Request("POST", "https://x"))])
def test_falla_tecnica_pasa_al_siguiente_modelo(error):
    """500, 429 o fallo de conexión: con fallback responde el modelo siguiente y queda marcado."""
    sdk = SDKFalso(error, _resp("ok"))
    r = correr(_cliente(sdk).completar("redactor", MSGS))
    assert r.modelo == REV_A and r.pedido == REDACTOR and r.fallback is True
    assert [k["model"] for k in sdk.llamadas] == [REDACTOR, REV_A]


def test_timeout_se_trata_como_falla_tecnica():
    """Una llamada que excede el tiempo cuenta como falla técnica y pasa al siguiente modelo."""
    async def lenta():
        await asyncio.sleep(5)

    sdk = SDKFalso(lenta, _resp("ok"))
    r = correr(_cliente(sdk, timeout_seg=0.05).completar("redactor", MSGS))
    assert r.modelo == REV_A and r.fallback is True


def test_429_bloquea_el_modelo_un_rato():
    """Tras un 429 el modelo no se vuelve a usar hasta pasado el bloqueo."""
    reloj = RelojFalso()
    sdk = SDKFalso(_err(429), _resp("a"), _resp("b"), _resp("c"))
    c = _cliente(sdk, reloj, bloqueo_429_seg=20)
    assert correr(c.completar("redactor", MSGS)).modelo == REV_A  # el redactor queda bloqueado
    assert correr(c.completar("redactor", MSGS)).modelo == REV_A  # sigue bloqueado
    reloj.t += 21
    assert correr(c.completar("redactor", MSGS)).modelo == REDACTOR  # ya se puede usar


def test_todos_fallan_da_agotado():
    """Si todos los modelos fallan, LLMError agotado."""
    sdk = SDKFalso(_err(500), _err(500), _err(500))
    with pytest.raises(LLMError) as e:
        correr(_cliente(sdk).completar("redactor", MSGS))
    assert e.value.codigo == "agotado"
    assert len(sdk.llamadas) == 3  # uno por modelo, sin repetir


def test_revisor_no_hace_fallback_y_reintenta_su_modelo():
    """El revisor reintenta su propio modelo (con espera) y nunca usa otro."""
    reloj = RelojFalso()
    sdk = SDKFalso(_err(500), _err(500))
    with pytest.raises(LLMError) as e:
        correr(_cliente(sdk, reloj, backoff_seg=2).completar("revisor_a", MSGS))
    assert e.value.codigo == "agotado"
    assert [k["model"] for k in sdk.llamadas] == [REV_A, REV_A]  # solo su modelo
    assert reloj.dormidos == [2.0, 4.0]  # espera creciente


def test_revisor_se_recupera_si_el_reintento_funciona():
    """Un fallo técnico seguido de un acierto en el mismo modelo devuelve la respuesta."""
    sdk = SDKFalso(_err(500), _resp("ok"))
    r = correr(_cliente(sdk).completar("revisor_b", MSGS))
    assert r.modelo == REV_B and r.fallback is False


def test_permitir_fallback_explicito_en_un_revisor():
    """El valor por defecto del rol se puede cambiar llamada a llamada."""
    sdk = SDKFalso(_err(500), _resp("ok"))
    r = correr(_cliente(sdk).completar("revisor_a", MSGS, permitir_fallback=True))
    assert r.modelo != REV_A and r.fallback is True


def test_413_sin_fallback_es_pedido_demasiado_grande():
    """Un 413 sin posibilidad de fallback se informa como pedido demasiado grande."""
    with pytest.raises(LLMError) as e:
        correr(_cliente(SDKFalso(_err(413))).completar("revisor_a", MSGS))
    assert e.value.codigo == "pedido_demasiado_grande"


def test_413_con_fallback_prueba_otro_modelo():
    """Con fallback, un 413 descarta ese modelo y se prueba el siguiente."""
    sdk = SDKFalso(_err(413), _resp("ok"))
    assert correr(_cliente(sdk).completar("redactor", MSGS)).modelo == REV_A


# ---------------------------------------------------------------- límite de tokens

def test_pedido_que_no_cabe_en_ningun_modelo_no_llama():
    """Si el pedido supera el presupuesto de todos los modelos, falla sin llamar a la API."""
    reloj = RelojFalso()
    sdk = SDKFalso()
    c = _cliente(sdk, reloj, limitador=LimitadorTokens(tpm_defecto=100, reloj=reloj))
    with pytest.raises(LLMError) as e:
        correr(c.completar("redactor", [{"role": "user", "content": "x" * 3000}]))
    assert e.value.codigo == "pedido_demasiado_grande" and sdk.llamadas == []


def test_espera_cupo_antes_de_llamar():
    """Con un solo modelo y el presupuesto casi gastado, la segunda llamada espera a que venza la ventana."""
    reloj = RelojFalso()
    lim = LimitadorTokens(tpm_defecto=1000, rpm_defecto=1000, margen=1.0, reloj=reloj)
    sdk = SDKFalso(_resp(tokens=900), _resp("segunda"))
    c = ClienteGroq(
        api_key="x", modelos=MODELOS, orden_fallback=[REDACTOR], sdk=sdk, limitador=lim,
        reloj=reloj, dormir=reloj.dormir, max_tokens=500,
    )
    correr(c.completar("redactor", MSGS))  # gasta 900 de 1000
    r = correr(c.completar("redactor", MSGS))  # ahora no cabe: espera
    assert r.texto == "segunda"
    assert reloj.dormidos and reloj.dormidos[0] > 0


def test_sin_cupo_si_la_espera_supera_el_tope():
    """Si el cupo tarda más que el tope de espera, LLMError sin_cupo."""
    reloj = RelojFalso()
    lim = LimitadorTokens(tpm_defecto=1000, rpm_defecto=1000, margen=1.0, reloj=reloj)
    sdk = SDKFalso(_resp(tokens=900))
    c = ClienteGroq(
        api_key="x", modelos=MODELOS, orden_fallback=[REDACTOR], sdk=sdk, limitador=lim,
        reloj=reloj, dormir=reloj.dormir, max_tokens=500, espera_max_seg=5,
    )
    correr(c.completar("redactor", MSGS))
    with pytest.raises(LLMError) as e:
        correr(c.completar("redactor", MSGS))
    assert e.value.codigo == "sin_cupo"


def test_tokens_reales_ajustan_la_reserva():
    """Tras responder, el limitador queda con los tokens reales y no con la estimación."""
    reloj = RelojFalso()
    lim = LimitadorTokens(tpm_defecto=100000, rpm_defecto=1000, reloj=reloj)
    c = _cliente(SDKFalso(_resp(tokens=42)), reloj, limitador=lim)
    correr(c.completar("redactor", MSGS))
    assert lim.tokens_usados(REDACTOR) == 42


def test_registro_de_llamadas():
    """Cada llamada deja una entrada con el modelo pedido y el que respondió."""
    c = _cliente(SDKFalso(_err(500), _resp("ok")))
    correr(c.completar("redactor", MSGS))
    ok = [x for x in c.llamadas if x.get("error") is None][-1]
    assert ok["pedido"] == REDACTOR and ok["modelo"] == REV_A and ok["fallback"] is True
    assert any(x.get("error") for x in c.llamadas)  # el fallo también quedó registrado


# ---------------------------------------------------------------- LimitadorTokens (unidad)

def _lim(reloj, **kw):
    """Limitador de prueba con margen 1.0 para que las cuentas sean exactas."""
    kw.setdefault("margen", 1.0)
    return LimitadorTokens(reloj=reloj, **kw)


def test_limitador_cabe_en_absoluto():
    """Un pedido mayor que el presupuesto nunca cabe; uno igual, sí."""
    lim = _lim(RelojFalso(), tpm_defecto=1000)
    assert lim.cabe_en_absoluto("m", 1000) is True
    assert lim.cabe_en_absoluto("m", 1001) is False


def test_limitador_margen_de_seguridad():
    """El margen reduce el presupuesto efectivo (8000 * 0.8 = 6400)."""
    lim = LimitadorTokens(tpm_defecto=8000, margen=0.8, reloj=RelojFalso())
    assert lim.cabe_en_absoluto("m", 6400) and not lim.cabe_en_absoluto("m", 6401)


def test_limitador_espera_hasta_que_venza_la_entrada():
    """Cuánto falta para liberar tokens depende de cuándo se hizo la reserva más antigua necesaria."""
    reloj = RelojFalso()
    lim = _lim(reloj, tpm_defecto=1000, rpm_defecto=1000)
    lim.reservar("m", 600)
    reloj.t += 10
    lim.reservar("m", 300)
    assert lim.espera_necesaria("m", 100) == 0  # 900 + 100 = 1000: cabe justo
    assert lim.espera_necesaria("m", 200) == pytest.approx(50)  # hay que esperar a que venza la de 600 (a los 60 s)
    assert lim.espera_necesaria("m", 1000) == pytest.approx(60)  # hace falta que venzan las dos (la de 300 vence a los 70 s)


def test_limitador_la_ventana_expira():
    """Pasados 60 s las reservas dejan de contar."""
    reloj = RelojFalso()
    lim = _lim(reloj, tpm_defecto=1000, rpm_defecto=1000)
    lim.reservar("m", 1000)
    assert lim.espera_necesaria("m", 500) > 0
    reloj.t += 61
    assert lim.espera_necesaria("m", 500) == 0 and lim.tokens_usados("m") == 0


def test_limitador_peticiones_por_minuto():
    """El tope de peticiones también hace esperar, aunque sobren tokens."""
    reloj = RelojFalso()
    lim = _lim(reloj, tpm_defecto=100000, rpm_defecto=2)
    lim.reservar("m", 1)
    reloj.t += 5
    lim.reservar("m", 1)
    assert lim.espera_necesaria("m", 1) == pytest.approx(55)  # falta que venza la primera


def test_limitador_bloqueo():
    """Un bloqueo manual impide usar el modelo hasta que pasa el tiempo."""
    reloj = RelojFalso()
    lim = _lim(reloj, tpm_defecto=1000)
    lim.bloquear("m", 20)
    assert lim.espera_necesaria("m", 1) == pytest.approx(20)
    reloj.t += 21
    assert lim.espera_necesaria("m", 1) == 0


def test_limitador_modelos_independientes():
    """El gasto de un modelo no afecta a otro."""
    lim = _lim(RelojFalso(), tpm_defecto=1000)
    lim.reservar("a", 1000)
    assert lim.espera_necesaria("a", 1) > 0 and lim.espera_necesaria("b", 1) == 0


def test_estimar_tokens_es_prudente():
    """La estimación es mayor que chars/4 (sobreestima a propósito)."""
    assert estimar_tokens([{"role": "user", "content": "a" * 300}]) >= 100