"""Pruebas de la medición de tiempos (tanda 10A): cliente LLM y medidor de etapas del orquestador.

Sin red ni esperas reales: el SDK de Groq es falso y el reloj y el `dormir` se inyectan. Las pruebas
son síncronas y usan `asyncio.run`, así que no dependen de ningún plugin de pytest para async.

NOTA DE RUTA: `_Medidor` vive en el módulo del orquestador real. Si en tu repo ese módulo no está en
`app.runs.orquestador_real`, cambia solo el import de la línea marcada.
"""

import asyncio
import logging
from types import SimpleNamespace

import groq
import httpx
import pytest

from app.agentes.cliente_llm import ClienteGroq, LimitadorTokens
from app.runs.orquestador_real import _Medidor  # <-- ajusta esta ruta si tu módulo está en otro paquete


# ---------------------------------------------------------------------------
# Piezas falsas
# ---------------------------------------------------------------------------

class RelojFalso:
    """Reloj controlable a mano: `dormir` lo adelanta, así las esperas no cuestan tiempo real."""

    def __init__(self) -> None:
        self.t = 0.0  # instante actual del reloj falso

    def __call__(self) -> float:
        """Devuelve el instante actual."""
        return self.t

    async def dormir(self, segundos: float) -> None:
        """Sustituto de asyncio.sleep: solo adelanta el reloj."""
        self.t += segundos


def _respuesta(total_tokens: int = 600, texto: str = "{}", finish: str = "stop") -> SimpleNamespace:
    """Arma una respuesta con la forma mínima que lee el cliente (choices, usage)."""
    usage = SimpleNamespace(total_tokens=total_tokens, model_dump=lambda: {"total_tokens": total_tokens})
    eleccion = SimpleNamespace(message=SimpleNamespace(content=texto), finish_reason=finish)
    return SimpleNamespace(choices=[eleccion], usage=usage)


def _sdk_falso(guion: list) -> SimpleNamespace:
    """SDK falso: cada llamada consume un elemento del guion (una respuesta o una excepción a lanzar)."""
    cola = list(guion)

    async def create(**_kwargs):
        """Devuelve la siguiente respuesta del guion o lanza la excepción que toque."""
        item = cola.pop(0)
        # Una excepción del guion se lanza; cualquier otra cosa es la respuesta.
        if isinstance(item, Exception):
            raise item
        return item

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _cliente(sdk: SimpleNamespace, reloj: RelojFalso, tpm: int = 1000) -> ClienteGroq:
    """Cliente con todo inyectado (no toca config ni red): un solo modelo `m` para el rol `redactor`."""
    limitador = LimitadorTokens(
        tpm_por_modelo={"m": tpm}, rpm_defecto=100, margen=1.0, reloj=reloj,
    )
    return ClienteGroq(
        modelos={"redactor": "m"}, orden_fallback=["m"], limitador=limitador,
        timeout_seg=5, espera_max_seg=120, bloqueo_429_seg=1.0, max_tokens=500,
        sdk=sdk, reloj=reloj, dormir=reloj.dormir,
    )


MENSAJES = [{"role": "user", "content": "x" * 300}]  # ~101 tokens estimados + 500 de salida = 601


# ---------------------------------------------------------------------------
# Cliente LLM
# ---------------------------------------------------------------------------

def test_espera_por_cupo_se_registra_en_respuesta_y_metricas(caplog):
    """La segunda llamada no cabe en la ventana: debe dormir ~60 s y dejarlo anotado."""
    reloj = RelojFalso()
    cliente = _cliente(_sdk_falso([_respuesta(600), _respuesta(600)]), reloj)

    async def correr():
        """Dos llamadas seguidas al mismo modelo con presupuesto de 1000 tokens/min."""
        r1 = await cliente.completar("redactor", MENSAJES, json_mode=False)
        r2 = await cliente.completar("redactor", MENSAJES, json_mode=False)
        return r1, r2

    with caplog.at_level(logging.INFO):
        r1, r2 = asyncio.run(correr())

    # La primera pasa de inmediato; la segunda espera a que venza la ventana de la primera.
    assert r1.espera_cupo_seg == 0.0
    assert r2.espera_cupo_seg == pytest.approx(60.05, abs=0.1)
    assert r2.seg_total >= r2.espera_cupo_seg  # el reloj de pared incluye la espera
    assert r1.intentos_red == 1 and r2.intentos_red == 1
    # Los contadores globales acumulan lo mismo.
    m = cliente.metricas()
    assert m["llamadas_red"] == 2
    assert m["espera_cupo_seg"] == pytest.approx(60.05, abs=0.1)
    assert m["tokens"] == 1200
    # Y queda una línea de log por llamada, con la etiqueta de espera.
    lineas = [r.getMessage() for r in caplog.records if r.getMessage().startswith("LLM rol=redactor modelo=m")]
    assert len(lineas) == 2


def test_rechazo_json_transitorio_cuenta_dos_intentos_de_red():
    """Un 400 por JSON mal generado se reintenta sin JSON: dos peticiones reales, una respuesta."""
    reloj = RelojFalso()
    peticion = httpx.Request("POST", "http://prueba.local/chat")
    error = groq.BadRequestError(
        "Failed to generate JSON", response=httpx.Response(400, request=peticion), body=None,
    )
    cliente = _cliente(_sdk_falso([error, _respuesta(100)]), reloj)

    respuesta = asyncio.run(cliente.completar("redactor", MENSAJES, json_mode=True))

    assert respuesta.intentos_red == 2  # la que falló y la que respondió
    assert cliente.metricas()["llamadas_red"] == 2
    # El registro de la llamada exitosa trae los datos nuevos.
    ultima = cliente.llamadas[-1]
    assert ultima["intentos_red"] == 2 and ultima["tokens"] == 100 and ultima["error"] is None


def test_respuesta_llm_sigue_construyendose_sin_los_campos_nuevos():
    """Los clientes falsos de otras pruebas arman RespuestaLLM sin los campos de medición."""
    from app.agentes.cliente_llm import RespuestaLLM

    r = RespuestaLLM(texto="hola", modelo="m", pedido="m", fallback=False, finish_reason="stop", uso=None, seg=0.1)
    assert (r.espera_cupo_seg, r.intentos_red, r.seg_total) == (0.0, 1, 0.0)


# ---------------------------------------------------------------------------
# Medidor de etapas
# ---------------------------------------------------------------------------

class ClienteConMetricas:
    """Cliente falso con contadores que las pruebas mueven a mano."""

    def __init__(self) -> None:
        self.valores = {"llamadas_red": 0, "espera_cupo_seg": 0.0, "tokens": 0}

    def metricas(self) -> dict:
        """Copia de los contadores actuales."""
        return dict(self.valores)


def test_medidor_atribuye_tiempo_y_consumo_a_cada_etapa():
    """El medidor resta los contadores de antes y después de cada etapa."""
    reloj = RelojFalso()
    cliente = ClienteConMetricas()
    medidor = _Medidor("run_x", cliente, reloj=reloj)

    with medidor.etapa("estratega"):
        reloj.t += 12.5
        cliente.valores.update(llamadas_red=2, espera_cupo_seg=3.0, tokens=900)
    with medidor.etapa("redactor_slide_1"):
        reloj.t += 30.0
        cliente.valores.update(llamadas_red=3, espera_cupo_seg=3.0, tokens=1500)

    estratega, redactor = medidor.etapas
    assert (estratega.seg, estratega.llamadas, estratega.espera_cupo_seg, estratega.tokens) == (12.5, 2, 3.0, 900)
    # La segunda etapa solo cuenta lo que pasó DENTRO de ella.
    assert (redactor.seg, redactor.llamadas, redactor.espera_cupo_seg, redactor.tokens) == (30.0, 1, 0.0, 600)
    texto = medidor.resumen()
    assert "total 42.5 s" in texto and "estratega" in texto and "redactor_slide_1" in texto
    assert "INTERRUMPIDA" not in texto


def test_etapa_interrumpida_queda_marcada_y_la_excepcion_se_propaga():
    """Si una etapa falla (o vence el tope), se registra como interrumpida y el error sigue su camino."""
    reloj = RelojFalso()
    medidor = _Medidor("run_x", ClienteConMetricas(), reloj=reloj)

    with pytest.raises(RuntimeError):
        with medidor.etapa("revisor_1"):
            reloj.t += 5.0
            raise RuntimeError("falla de prueba")

    assert medidor.etapas[0].ok is False and medidor.etapas[0].seg == 5.0
    assert "INTERRUMPIDA" in medidor.resumen()


def test_medidor_tolera_clientes_sin_metricas_o_que_fallan():
    """Un cliente falso sin `metricas()`, o con una que revienta, no debe romper la medición."""
    reloj = RelojFalso()

    class SinMetricas:
        """Cliente que no mide."""

    class MetricasRotas:
        """Cliente cuya medición lanza una excepción."""

        def metricas(self):
            """Falla siempre."""
            raise ValueError("roto")

    # Se prueba con los dos tipos de cliente.
    for cliente in (SinMetricas(), MetricasRotas()):
        medidor = _Medidor("run_x", cliente, reloj=reloj)
        with medidor.etapa("estratega"):
            reloj.t += 1.0
        etapa = medidor.etapas[0]
        assert etapa.seg == 1.0 and etapa.llamadas == 0 and etapa.tokens == 0