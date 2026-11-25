"""Pruebas de la tanda 2A del cliente LLM: respaldo solo por falla, reserva por rol y extras por modelo.

Sin red: se usa un SDK falso y un reloj controlado. Cada prueba arma su propio cliente con parámetros
explícitos (no depende del .env ni de los valores por defecto de config).
"""

import asyncio
import types

import groq
import httpx

from app.agentes.cliente_llm import ClienteGroq, LimitadorTokens, estimar_tokens

QWEN = "qwen/qwen3.8-27b"
G120 = "openai/gpt-oss-120b"
G20 = "openai/gpt-oss-20b"

MODELOS = {"estratega": QWEN, "redactor": QWEN, "revisor_a": G120, "revisor_b": G20}
CADENAS = {"redactor": [QWEN, G20], "estratega": [QWEN, G20], "revisor_a": [G120, G20], "revisor_b": [G120, G20]}
RESERVAS = {"estratega": 700, "redactor": 600, "revisor_a": 1000, "revisor_b": 1000}
EXTRAS = {G120: {"reasoning_effort": "low"}, G20: {"reasoning_effort": "low"}}

# Mensaje de ~700 tokens estimados (2100 caracteres entre 3).
MENSAJES = [{"role": "user", "content": "x" * 2100}]


class Reloj:
    """Reloj controlado a mano: `dormir` lo adelanta, así las esperas no son reales."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def dormir(self, segundos: float) -> None:
        """Adelanta el reloj en vez de esperar."""
        self.t += segundos


class SdkFalso:
    """SDK falso de Groq: cada llamada gasta `gasto` tokens; los modelos de `fallan` responden 500."""

    def __init__(self, gasto: int = 1050, fallan: tuple[str, ...] = ()):
        self.gasto = gasto
        self.fallan = set(fallan)
        self.peticiones: list[dict] = []  # parámetros de cada petición, en orden
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._crear))

    async def _crear(self, **kwargs):
        """Registra la petición y responde bien o con un 500 según el modelo."""
        self.peticiones.append(kwargs)
        # Un modelo marcado como caído lanza un error técnico del SDK.
        if kwargs["model"] in self.fallan:
            respuesta = httpx.Response(500, request=httpx.Request("POST", "http://groq.falso"))
            raise groq.InternalServerError("caído", response=respuesta, body=None)
        uso = types.SimpleNamespace(total_tokens=self.gasto, model_dump=lambda: {"total_tokens": self.gasto})
        eleccion = types.SimpleNamespace(message=types.SimpleNamespace(content="{}"), finish_reason="stop")
        return types.SimpleNamespace(choices=[eleccion], usage=uso)


def _cliente(sdk, reloj, **kwargs) -> ClienteGroq:
    """Cliente con los parámetros de la tanda 2A (se pueden pisar por prueba)."""
    parametros = dict(
        api_key="falsa", sdk=sdk, modelos=MODELOS, fallback_por_rol=CADENAS,
        roles_respaldo_por_falla=("estratega", "redactor"), espera_antes_de_saltar_seg=20,
        reserva_salida_por_rol=RESERVAS, extra_por_modelo=EXTRAS,
        limitador=LimitadorTokens(tpm_defecto=8000, rpm_defecto=30, margen=0.8, reloj=reloj),
        reloj=reloj, dormir=reloj.dormir,
    )
    parametros.update(kwargs)
    return ClienteGroq(**parametros)


def _correr(corrutina):
    """Ejecuta una corrutina desde una prueba síncrona (no depende de pytest-asyncio)."""
    return asyncio.run(corrutina)


async def _varias(cliente, rol, veces, **kwargs):
    """Hace `veces` llamadas seguidas al rol y devuelve las respuestas."""
    respuestas = []
    # Cada llamada es secuencial, como en el orquestador.
    for _ in range(veces):
        respuestas.append(await cliente.completar(rol, MENSAJES, max_tokens=2000, **kwargs))
    return respuestas


# ---------------------------------------------------------------- respaldo solo por falla

def test_el_redactor_se_queda_en_qwen_mientras_hay_cupo():
    reloj = Reloj()
    respuestas = _correr(_varias(_cliente(SdkFalso(), reloj), "redactor", 5))
    # Con 1.050 tokens reales por llamada caben 5 en la ventana: ninguna salta ni espera.
    assert [r.modelo for r in respuestas] == [QWEN] * 5
    assert all(r.motivo_salto is None and not r.fallback for r in respuestas)


def test_con_mas_margen_caben_las_seis_en_qwen():
    reloj = Reloj()
    limitador = LimitadorTokens(tpm_defecto=8000, rpm_defecto=30, margen=0.9, reloj=reloj)
    respuestas = _correr(_varias(_cliente(SdkFalso(), reloj, limitador=limitador), "redactor", 6))
    assert [r.modelo for r in respuestas] == [QWEN] * 6


def test_si_qwen_se_llena_y_la_espera_supera_el_tope_salta_por_cupo():
    reloj = Reloj()
    respuestas = _correr(_varias(_cliente(SdkFalso(), reloj), "redactor", 6))
    # La 6.ª llamada tendría que esperar ~60 s (más que el tope de 20 s): pasa al respaldo y lo dice.
    assert respuestas[-1].modelo == G20
    assert respuestas[-1].motivo_salto == "cupo" and respuestas[-1].fallback is True


def test_si_la_espera_es_tolerable_espera_en_vez_de_saltar():
    reloj = Reloj()
    # Tope de 100 s: esperar ~60 s a qwen es preferible a gastar la ventana de gpt-oss.
    cliente = _cliente(SdkFalso(), reloj, espera_antes_de_saltar_seg=100)
    respuestas = _correr(_varias(cliente, "redactor", 6))
    assert respuestas[-1].modelo == QWEN and respuestas[-1].motivo_salto is None
    assert respuestas[-1].espera_cupo_seg > 0  # esperó de verdad


def test_una_falla_tecnica_de_qwen_pasa_al_respaldo_y_lo_explica():
    reloj = Reloj()
    sdk = SdkFalso(fallan=(QWEN,))
    respuesta = _correr(_varias(_cliente(sdk, reloj), "redactor", 1))[0]
    assert respuesta.modelo == G20
    assert respuesta.motivo_salto == "falla_tecnica" and respuesta.fallback is True
    assert [p["model"] for p in sdk.peticiones] == [QWEN, G20]  # intentó qwen primero


def test_el_revisor_reparte_entre_sus_dos_gpt_oss_y_nunca_usa_qwen():
    reloj = Reloj()
    sdk = SdkFalso(gasto=1700)
    respuestas = _correr(_varias(_cliente(sdk, reloj), "revisor_a", 6))
    modelos = {r.modelo for r in respuestas}
    # El revisor salta por cupo entre sus dos modelos (no es un rol de «respaldo solo por falla»).
    assert modelos == {G120, G20}
    assert QWEN not in {p["model"] for p in sdk.peticiones}
    assert any(r.motivo_salto == "cupo" for r in respuestas)


def test_motivo_no_cabe_si_el_modelo_pedido_no_entra_en_su_ventana():
    reloj = Reloj()
    # Qwen con un límite diminuto: el pedido no cabe nunca en su ventana y responde el respaldo.
    limitador = LimitadorTokens(tpm_defecto=8000, rpm_defecto=30, tpm_por_modelo={QWEN: 500}, reloj=reloj)
    respuesta = _correr(_varias(_cliente(SdkFalso(), reloj, limitador=limitador), "redactor", 1))[0]
    assert respuesta.modelo == G20 and respuesta.motivo_salto == "no_cabe"


# ---------------------------------------------------------------- reserva por rol

class LimitadorEspia(LimitadorTokens):
    """Limitador que anota cuántos tokens se reservan en cada llamada."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.reservas: list[int] = []

    def reservar(self, modelo, tokens):
        """Anota la reserva y delega en el limitador real."""
        self.reservas.append(tokens)
        return super().reservar(modelo, tokens)


def test_se_reserva_la_entrada_estimada_mas_la_salida_tipica_del_rol():
    reloj = Reloj()
    espia = LimitadorEspia(tpm_defecto=8000, rpm_defecto=30, reloj=reloj)
    _correr(_varias(_cliente(SdkFalso(), reloj, limitador=espia), "redactor", 1))
    # Redactor: 600 de salida típica, aunque se pidan 2000 a la API (antes se reservaban los 2000).
    assert espia.reservas == [estimar_tokens(MENSAJES) + 600]


def test_la_reserva_nunca_supera_el_tope_pedido():
    reloj = Reloj()
    espia = LimitadorEspia(tpm_defecto=8000, rpm_defecto=30, reloj=reloj)
    cliente = _cliente(SdkFalso(), reloj, limitador=espia)
    _correr(cliente.completar("redactor", MENSAJES, max_tokens=300))
    assert espia.reservas == [estimar_tokens(MENSAJES) + 300]  # min(600, 300)


def test_sin_reserva_para_el_rol_se_reserva_el_tope_completo():
    reloj = Reloj()
    espia = LimitadorEspia(tpm_defecto=8000, rpm_defecto=30, reloj=reloj)
    cliente = _cliente(SdkFalso(), reloj, limitador=espia, reserva_salida_por_rol={})
    _correr(_varias(cliente, "redactor", 1))
    assert espia.reservas == [estimar_tokens(MENSAJES) + 2000]  # comportamiento anterior a la 2A


def test_tras_la_llamada_la_ventana_queda_con_el_gasto_real():
    reloj = Reloj()
    cliente = _cliente(SdkFalso(gasto=1050), reloj)
    _correr(_varias(cliente, "redactor", 1))
    assert cliente.limitador.tokens_usados(QWEN) == 1050


# ---------------------------------------------------------------- extras por modelo

def test_los_gpt_oss_reciben_reasoning_effort_y_qwen_no():
    reloj = Reloj()
    sdk = SdkFalso(fallan=(QWEN,))  # qwen falla: la petición llega a qwen y luego al gpt-oss-20b
    _correr(_varias(_cliente(sdk, reloj), "redactor", 1))
    por_modelo = {p["model"]: p for p in sdk.peticiones}
    assert "reasoning_effort" not in por_modelo[QWEN]
    assert por_modelo[G20]["reasoning_effort"] == "low"


def test_el_extra_de_la_llamada_pisa_al_fijo_del_modelo():
    reloj = Reloj()
    sdk = SdkFalso()
    _correr(_cliente(sdk, reloj).completar("revisor_a", MENSAJES, extra={"reasoning_effort": "high"}))
    assert sdk.peticiones[0]["reasoning_effort"] == "high"


# ---------------------------------------------------------------- compatibilidad

def test_sin_parametros_nuevos_el_comportamiento_es_el_de_antes():
    reloj = Reloj()
    sdk = SdkFalso()
    # Modelos inyectados y nada más: sin cadenas propias, sin reservas por rol, sin extras.
    cliente = ClienteGroq(
        api_key="falsa", sdk=sdk, modelos=MODELOS, reloj=reloj, dormir=reloj.dormir,
        limitador=LimitadorTokens(tpm_defecto=8000, rpm_defecto=30, reloj=reloj),
    )
    respuesta = _correr(cliente.completar("redactor", MENSAJES, max_tokens=2000))
    assert respuesta.modelo == MODELOS["redactor"] and respuesta.motivo_salto is None
    assert "reasoning_effort" not in sdk.peticiones[0]
    assert cliente.roles_respaldo_por_falla == frozenset() and cliente.reserva_salida_por_rol == {}