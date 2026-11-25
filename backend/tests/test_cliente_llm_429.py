"""Pruebas de la tanda 1 de velocidad: espera exacta tras un 429 y reintento en el mismo modelo.

Sin red ni esperas reales: el SDK, el reloj y el sueño son falsos. Se prueba:
- que la pista «try again in ...» de Groq se lee bien (segundos, minutos y milisegundos);
- que un 429 corto en un rol con «respaldo solo por falla» espera y reintenta en el MISMO modelo;
- que un 429 largo, un segundo 429 o un mensaje sin pista saltan al respaldo como antes;
- que el bloqueo del modelo dura lo que dice Groq (con tope) o el valor fijo si no hay pista.
"""

import asyncio
from types import SimpleNamespace

import groq
import httpx
import pytest

from app.agentes.cliente_llm import ClienteGroq, _segundos_de_reintento

QWEN = "qwen/modelo-de-prueba"
RESPALDO = "openai/respaldo-de-prueba"
MENSAJES = [{"role": "user", "content": "hola"}]


def _error_429(mensaje: str) -> groq.RateLimitError:
    """RateLimitError del SDK con el mensaje dado (sin tocar la red)."""
    peticion = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return groq.RateLimitError(mensaje, response=httpx.Response(429, request=peticion), body=None)


def _respuesta(total: int = 100) -> SimpleNamespace:
    """Respuesta falsa del SDK con el mínimo que lee el cliente (texto, finish_reason y tokens)."""
    uso = SimpleNamespace(total_tokens=total, model_dump=lambda: {"total_tokens": total})
    eleccion = SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")
    return SimpleNamespace(choices=[eleccion], usage=uso)


class _Reloj:
    """Reloj falso: `dormir` no espera, solo avanza la hora y anota cuánto se durmió."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.dormidos: list[float] = []

    def __call__(self) -> float:
        """Hora actual del reloj falso."""
        return self.t

    async def dormir(self, segundos: float) -> None:
        """Avanza el reloj `segundos` sin esperar de verdad."""
        self.dormidos.append(segundos)
        self.t += segundos


class _SdkFalso:
    """SDK falso: cada modelo tiene un guion con respuestas o excepciones que se van consumiendo."""

    def __init__(self, guion: dict[str, list]) -> None:
        self.guion = {modelo: list(pasos) for modelo, pasos in guion.items()}
        self.llamadas: list[str] = []  # modelos pedidos, en orden
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        """Devuelve (o lanza) el siguiente paso del guion del modelo pedido."""
        modelo = kwargs["model"]
        self.llamadas.append(modelo)
        paso = self.guion[modelo].pop(0)
        # Una excepción del guion se lanza; cualquier otra cosa es la respuesta.
        if isinstance(paso, Exception):
            raise paso
        return paso


def _cliente(guion: dict[str, list]):
    """Cliente con rol «redactor» (qwen → respaldo, respaldo solo por falla) y todo inyectado."""
    reloj = _Reloj()
    sdk = _SdkFalso(guion)
    cliente = ClienteGroq(
        sdk=sdk,
        modelos={"redactor": QWEN},
        fallback_por_rol={"redactor": [QWEN, RESPALDO]},
        roles_respaldo_por_falla=("redactor",),
        espera_antes_de_saltar_seg=40.0,
        bloqueo_429_seg=20.0,
        bloqueo_429_max_seg=60.0,
        colchon_429_seg=0.5,
        reloj=reloj,
        dormir=reloj.dormir,
    )
    return cliente, sdk, reloj


def _completar(cliente: ClienteGroq):
    """Una llamada del rol «redactor» sin modo JSON (el SDK falso no lo necesita)."""
    return asyncio.run(cliente.completar("redactor", MENSAJES, json_mode=False))


@pytest.mark.parametrize(
    ("mensaje", "esperado"),
    [
        ("Rate limit reached. Please try again in 19.8s. Need more tokens?", 19.8),
        ("Please try again in 2.34s.", 2.34),
        ("Please try again in 2m3.5s.", 123.5),
        ("Please try again in 340ms.", 0.34),
        ("Rate limit reached sin ninguna pista de espera", None),
        ("try again in unos minutos", None),
    ],
)
def test_lee_la_pista_de_espera_de_groq(mensaje, esperado):
    """La pista se convierte a segundos en los formatos que usa Groq; sin pista devuelve None."""
    resultado = _segundos_de_reintento(Exception(mensaje))
    # Sin pista no hay nada que comparar; con pista se tolera el error de coma flotante.
    if esperado is None:
        assert resultado is None
    else:
        assert resultado == pytest.approx(esperado)


def test_429_corto_espera_y_reintenta_en_el_mismo_modelo():
    """Un 429 con 2,3 s de espera no gasta el respaldo: se duerme lo justo y qwen responde."""
    cliente, sdk, reloj = _cliente({QWEN: [_error_429("Please try again in 2.3s."), _respuesta()], RESPALDO: []})
    resp = _completar(cliente)

    assert sdk.llamadas == [QWEN, QWEN]  # el respaldo no se tocó
    assert resp.modelo == QWEN
    assert resp.fallback is False
    assert resp.motivo_salto is None
    # Se durmió la pista (2,3) más el colchón (0,5) y los 0,05 s de margen del bucle.
    assert sum(reloj.dormidos) == pytest.approx(2.85, abs=0.01)
    assert resp.espera_cupo_seg == pytest.approx(2.85, abs=0.01)


def test_429_largo_salta_al_respaldo_sin_dormir():
    """Si Groq pide más espera que el tope (55 s > 40 s), se pasa al respaldo de inmediato."""
    cliente, sdk, reloj = _cliente({QWEN: [_error_429("Please try again in 55.0s.")], RESPALDO: [_respuesta()]})
    resp = _completar(cliente)

    assert sdk.llamadas == [QWEN, RESPALDO]
    assert resp.fallback is True
    assert resp.motivo_salto == "falla_tecnica"
    assert reloj.dormidos == []


def test_segundo_429_en_la_misma_llamada_salta_al_respaldo():
    """La espera en el mismo modelo es de una sola vez: si vuelve a fallar, entra el respaldo."""
    cliente, sdk, reloj = _cliente(
        {QWEN: [_error_429("Please try again in 2.0s."), _error_429("Please try again in 2.0s.")], RESPALDO: [_respuesta()]}
    )
    resp = _completar(cliente)

    assert sdk.llamadas == [QWEN, QWEN, RESPALDO]
    assert resp.fallback is True
    assert resp.motivo_salto == "falla_tecnica"
    assert len(reloj.dormidos) == 1  # solo se durmió la primera vez


def test_429_sin_pista_bloquea_el_tiempo_fijo_y_salta():
    """Sin «try again in» no se puede esperar con precisión: salto al respaldo y bloqueo fijo de 20 s."""
    cliente, sdk, reloj = _cliente({QWEN: [_error_429("Rate limit reached")], RESPALDO: [_respuesta()]})
    resp = _completar(cliente)

    assert sdk.llamadas == [QWEN, RESPALDO]
    assert resp.fallback is True
    assert cliente.limitador.espera_necesaria(QWEN, 10) == pytest.approx(20.0, abs=0.01)


def test_el_bloqueo_con_pista_respeta_el_tope():
    """Una pista absurda (500 s) no deja a qwen bloqueado más del tope de 60 s."""
    cliente, sdk, reloj = _cliente({QWEN: [_error_429("Please try again in 500s.")], RESPALDO: [_respuesta()]})
    _completar(cliente)

    assert cliente.limitador.espera_necesaria(QWEN, 10) == pytest.approx(60.0, abs=0.01)


def test_el_bloqueo_con_pista_dura_la_pista_mas_el_colchon():
    """El bloqueo de qwen es 19,8 s + 0,5 s de colchón, no los 20 s fijos de antes."""
    cliente, sdk, reloj = _cliente({QWEN: [_error_429("Please try again in 19.8s."), _respuesta()], RESPALDO: []})
    # Se prueba el bloqueo antes de que el reintento lo consuma: se fuerza el 429 a mano sobre el limitador.
    cliente.limitador.bloquear(QWEN, cliente._bloqueo_429(_segundos_de_reintento(_error_429("try again in 19.8s."))))

    assert cliente.limitador.espera_necesaria(QWEN, 10) == pytest.approx(20.3, abs=0.01)