"""Cliente LLM del backend: Groq con varios modelos, fallback solo técnico y límite de tokens.

Se construye UNA vez al arrancar el servidor y se inyecta en los agentes (estratega, redactor,
y más adelante el revisor). Las pruebas de los agentes usan un cliente falso con la misma
interfaz (`completar`), sin red.

Reglas heredadas del spike de fidelidad v3b:
- El fallback entre modelos salta SOLO por fallas técnicas (cuota 429, 413, 5xx, timeout,
  conexión), nunca por una respuesta que no guste.
- Cada respuesta dice qué modelo contestó y si hubo fallback.
- El revisor corre sin fallback (cada revisor con su modelo).
- Una salida cortada (`finish_reason == "length"`) o vacía se informa con `truncada`;
  qué hacer con ella lo decide el agente.

Memoria del modo JSON (tanda 9A):
- Si un modelo rechaza `response_format` (400) y la MISMA petición sale bien sin él, el cliente
  recuerda ese modelo (`modelos_sin_json`) y ya no se lo envía en las llamadas siguientes, así se
  evita un viaje de ida y vuelta fallido en cada petición.
- Solo se recuerda cuando el reintento sin JSON tuvo éxito: un 400 por otra causa (por ejemplo un
  parámetro inválido en `extra`) falla otra vez sin JSON y NO se atribuye al modo JSON.
- Un 400 por JSON mal generado por el modelo (`json_validate_failed`) es transitorio: se reintenta
  esa llamada sin JSON, pero no se recuerda al modelo.

Medición de tiempos (tanda 10A, solo observa; no cambia el comportamiento):
- Cada respuesta trae `espera_cupo_seg` (tiempo dormido esperando cupo del limitador), `intentos_red`
  (peticiones reales hechas a Groq en esa llamada) y `seg_total` (reloj de pared de toda la llamada,
  esperas incluidas; `seg` sigue siendo solo la última petición).
- Cada llamada deja UNA línea de log INFO con esos datos, para ver dónde se va el tiempo de un run.
- `metricas()` devuelve contadores acumulados del cliente (peticiones, espera por cupo, tokens): el
  orquestador los lee antes y después de cada etapa para atribuir el tiempo.

Menos espera por cupo (tanda 10B):
- Cada falla técnica (429, 413, 5xx, timeout, conexión) deja un WARNING con el modelo, el código HTTP y el
  mensaje de Groq: así se ve POR QUÉ una llamada cae al fallback (antes solo quedaba `fallback=True`).
- `fallback_por_rol` define cadenas de modelos propias de un rol. Un rol con cadena propia admite fallback
  DENTRO de ella aunque esté en ROLES_SIN_FALLBACK (el revisor salta de gpt-oss-120b a gpt-oss-20b, nunca
  al modelo del redactor). Con modelos inyectados (pruebas) no hay cadenas propias: nada cambia.
- El limitador usa el TPM de cada modelo (`config.GROQ_TPM_POR_MODELO`) en vez de uno solo para todos.

Respaldo solo por falla y reserva realista (tanda 2A, medido en el run run_348cc81c):
- El redactor saltaba a gpt-oss-120b/20b SIN falla técnica (qwen sin cupo porque la reserva era de más del
  doble del gasto real), gastaba 2 o 3 veces más tokens y le quitaba la ventana al revisor. Ahora el estratega
  y el redactor tienen cadena propia (qwen → gpt-oss-20b) y, en `roles_respaldo_por_falla`, el respaldo entra
  SOLO tras una falla técnica del modelo principal. Si el principal está lleno, se espera hasta
  `espera_antes_de_saltar_seg`; pasado ese tope se permite el salto por cupo para no dormir un minuto.
- `reserva_salida_por_rol` separa lo que se RESERVA en el limitador de lo que se PIDE a la API (`max_tokens`):
  se reserva la entrada estimada más la salida típica del rol, no el tope completo.
- `extra_por_modelo` añade parámetros fijos por modelo (reasoning_effort bajo en gpt-oss, para que el
  razonamiento no se coma la salida y termine en finish=length).
- Cada respuesta trae `motivo_salto`: None (respondió el modelo pedido), «cupo», «falla_tecnica» o «no_cabe».

Espera exacta tras un 429 (tanda 1 de velocidad, medido en el run run_db6c83fe):
- Qwen tiene un límite de tokens de SALIDA por minuto (OTPM = 1000) que el limitador no conoce. Cuando Groq
  responde 429 dice cuánto esperar («Please try again in 2.34s»). Antes el modelo se bloqueaba 20 s fijos
  (de ahí los 17,6 s de espera del corrector_3) y el rol saltaba al respaldo en el acto, gastando la ventana
  de gpt-oss-20b que comparte con el revisor (de ahí los 54 s del revisor_1).
- Ahora el bloqueo dura lo que indica Groq (más un colchón, con tope `bloqueo_429_max_seg`); si el mensaje no
  trae la pista, se usa el bloqueo fijo de siempre.
- Un rol de `roles_respaldo_por_falla` (estratega, redactor) que recibe un 429 con espera corta (hasta
  `espera_antes_de_saltar_seg`) ESPERA y reintenta en el mismo modelo, una sola vez por llamada. Si el segundo
  intento también falla, o la espera es larga, salta al respaldo como antes.

Reserva calibrada con el gasto real (tanda 2 de velocidad, medido en el run run_4e47da95):
- La reserva era la entrada estimada con «1 token por cada 3 caracteres» más una salida fija por rol. Eso
  quedaba muy por encima de lo que gastaba de verdad cada llamada del revisor (~1.300 tokens) y, con la ventana
  del 20b ya ocupada por respaldos del redactor, la llamada dormía hasta 53,7 s esperando un cupo que en
  realidad sobraba.
- Ahora el cliente aprende POR ROL de cada respuesta real: cuántos caracteres caben en un token de entrada
  (`prompt_tokens`) y cuántos tokens de salida se gastaron (`completion_tokens`). Con `calibracion_min_muestras`
  respuestas o más, la reserva usa la razón caracteres/token más baja reciente y la salida más alta reciente,
  ambas con un colchón (`calibracion_colchon`). Con menos muestras se usa la fórmula de siempre.
- Una salida cortada o vacía no se aprende (llegó al tope, no dice lo que el rol gasta normalmente) y la razón
  caracteres/token se acota para que una medición rara no vuelva optimista la reserva.
- Con modelos inyectados (pruebas) la calibración arranca APAGADA salvo que se pida; con config arranca según
  `LLM_CALIBRAR_RESERVA`. Cada respuesta trae `reserva_tokens` y el log muestra `in=`, `out=` y `reserva=`
  para comparar lo reservado con lo gastado.
"""

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import groq

from app import config

log = logging.getLogger(__name__)

# Roles que por defecto NO admiten fallback (el revisor debe correr con su propio modelo).
ROLES_SIN_FALLBACK = ("revisor_a", "revisor_b")

# Tope de la razón caracteres/token que se aprende: el español ronda 3,5 a 4,2. Sin este tope, una medición
# rara (por ejemplo una entrada casi vacía con mucho texto de plantilla) daría una razón enorme y una reserva
# demasiado optimista.
RAZON_MAX_CHARS_POR_TOKEN = 4.5


class LLMError(Exception):
    """Fallo del cliente LLM. `codigo` es estable; `mensaje` es apto para mostrar al usuario."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class RespuestaLLM:
    """Resultado de una llamada: texto, modelo que contestó y datos para el registro."""

    texto: str
    modelo: str  # modelo que realmente respondió
    pedido: str  # modelo que se pidió primero para ese rol
    fallback: bool  # True si respondió un modelo distinto del pedido
    finish_reason: str | None
    uso: dict | None  # tokens reportados por Groq, si los hay
    seg: float  # duración de la última petición a Groq (la que respondió)
    # Datos de medición (tanda 10A). Con valor por defecto para no romper a quien construye
    # una RespuestaLLM a mano (por ejemplo los clientes falsos de las pruebas).
    espera_cupo_seg: float = 0.0  # tiempo dormido esperando cupo del limitador en esta llamada
    intentos_red: int = 1  # peticiones reales a Groq hechas en esta llamada (reintentos incluidos)
    seg_total: float = 0.0  # reloj de pared de toda la llamada, esperas y reintentos incluidos
    # Por qué respondió un modelo distinto del pedido (tanda 2A): «cupo», «falla_tecnica» o «no_cabe».
    motivo_salto: str | None = None
    # Tokens que el limitador reservó para esta llamada (tanda 2 de velocidad); 0 si no se conoce.
    reserva_tokens: int = 0

    @property
    def truncada(self) -> bool:
        """True si la salida se cortó por longitud o llegó vacía (no se debe puntuar ni usar)."""
        return self.finish_reason == "length" or not self.texto.strip()


class ClienteLLM(Protocol):
    """Interfaz que usan los agentes; la cumplen ClienteGroq y los clientes falsos de las pruebas."""

    async def completar(
        self,
        rol: str,
        mensajes: list[dict[str, str]],
        *,
        temperatura: float = 0.2,
        json_mode: bool = True,
        permitir_fallback: bool | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RespuestaLLM: ...


def _caracteres(mensajes: list[dict[str, str]]) -> int:
    """Total de caracteres del contenido de los mensajes (base de la estimación de tokens de entrada)."""
    return sum(len(str(m.get("content") or "")) for m in mensajes)


def estimar_tokens(mensajes: list[dict[str, str]]) -> int:
    """Estimación prudente de tokens de entrada: 1 token por cada 3 caracteres (sobreestima a propósito)."""
    return _caracteres(mensajes) // 3 + 1


# ---------------------------------------------------------------------------
# Límite de tokens y peticiones por minuto
# ---------------------------------------------------------------------------

@dataclass
class _Uso:
    """Una entrada de la ventana: cuándo se hizo y cuántos tokens se le atribuyen (ajustable)."""

    ts: float
    tokens: int


class _Ventana:
    """Historial de un modelo en la ventana deslizante."""

    def __init__(self, tpm: int, rpm: int, margen: float):
        self.presupuesto = int(tpm * margen)  # tokens por minuto utilizables
        self.rpm_efectivo = max(1, int(rpm * margen))  # peticiones por minuto utilizables
        self.usos: deque[_Uso] = deque()
        self.bloqueado_hasta = 0.0  # tras un 429 el modelo no se usa hasta este instante


class LimitadorTokens:
    """Lleva la cuenta de tokens y peticiones por modelo en una ventana deslizante.

    A diferencia de registrar el gasto al terminar, aquí se RESERVA al empezar la llamada,
    para que varias ejecuciones simultáneas no elijan el mismo modelo "creyendo" que tiene cupo.
    """

    def __init__(
        self,
        tpm_defecto: int = 8000,
        rpm_defecto: int = 30,
        tpm_por_modelo: dict[str, int] | None = None,
        rpm_por_modelo: dict[str, int] | None = None,
        margen: float = 0.8,
        ventana_seg: float = 60.0,
        reloj: Callable[[], float] = time.monotonic,
    ):
        self.tpm_defecto = tpm_defecto
        self.rpm_defecto = rpm_defecto
        self.tpm_por_modelo = tpm_por_modelo or {}
        self.rpm_por_modelo = rpm_por_modelo or {}
        self.margen = margen
        self.ventana_seg = ventana_seg
        self.reloj = reloj
        self._ventanas: dict[str, _Ventana] = {}

    def _ventana(self, modelo: str) -> _Ventana:
        """Devuelve (creándola si hace falta) la ventana del modelo."""
        if modelo not in self._ventanas:
            self._ventanas[modelo] = _Ventana(
                self.tpm_por_modelo.get(modelo, self.tpm_defecto),
                self.rpm_por_modelo.get(modelo, self.rpm_defecto),
                self.margen,
            )
        return self._ventanas[modelo]

    def _purgar(self, v: _Ventana, ahora: float) -> None:
        """Descarta las entradas más viejas que la ventana."""
        # Las entradas están ordenadas por tiempo: se quitan desde el principio.
        while v.usos and ahora - v.usos[0].ts > self.ventana_seg:
            v.usos.popleft()

    def cabe_en_absoluto(self, modelo: str, tokens: int) -> bool:
        """True si el pedido cabría alguna vez en el presupuesto del modelo (aunque la ventana esté vacía)."""
        return tokens <= self._ventana(modelo).presupuesto

    def espera_necesaria(self, modelo: str, tokens: int) -> float:
        """Segundos que habría que esperar para poder enviar `tokens` a este modelo (0 = ahora mismo)."""
        v = self._ventana(modelo)
        ahora = self.reloj()
        self._purgar(v, ahora)
        espera = max(0.0, v.bloqueado_hasta - ahora)

        # Tokens: cuánto se pasa del presupuesto y cuándo vencen las entradas que lo liberan.
        exceso = sum(u.tokens for u in v.usos) + tokens - v.presupuesto
        if exceso > 0:
            acumulado = 0
            # Se recorre del más antiguo al más nuevo hasta liberar lo suficiente.
            for u in v.usos:
                acumulado += u.tokens
                if acumulado >= exceso:
                    espera = max(espera, u.ts + self.ventana_seg - ahora)
                    break

        # Peticiones: si ya se alcanzó el tope, hay que esperar a que venza la que libera un hueco.
        if len(v.usos) >= v.rpm_efectivo:
            libera = v.usos[len(v.usos) - v.rpm_efectivo]
            espera = max(espera, libera.ts + self.ventana_seg - ahora)
        return max(0.0, espera)

    def reservar(self, modelo: str, tokens: int) -> _Uso:
        """Anota una petición con `tokens` estimados y devuelve la entrada para ajustarla después."""
        uso = _Uso(self.reloj(), tokens)
        self._ventana(modelo).usos.append(uso)
        return uso

    def ajustar(self, reserva: _Uso, tokens_reales: int) -> None:
        """Corrige los tokens de una reserva con el gasto real (0 si la llamada falló)."""
        reserva.tokens = max(0, tokens_reales)

    def bloquear(self, modelo: str, segundos: float) -> None:
        """Marca el modelo como no disponible durante `segundos` (por ejemplo, tras un 429)."""
        # Nunca se acorta un bloqueo vigente: un 429 con pista corta no debe liberar un bloqueo más largo.
        v = self._ventana(modelo)
        v.bloqueado_hasta = max(v.bloqueado_hasta, self.reloj() + segundos)

    def tokens_usados(self, modelo: str) -> int:
        """Tokens atribuidos al modelo dentro de la ventana actual (para pruebas y diagnóstico)."""
        v = self._ventana(modelo)
        self._purgar(v, self.reloj())
        return sum(u.tokens for u in v.usos)


# ---------------------------------------------------------------------------
# Cliente de Groq
# ---------------------------------------------------------------------------

def _estado_http(e: Exception) -> int | None:
    """Código HTTP de un error del SDK, si lo trae."""
    estado = getattr(e, "status_code", None)
    return estado if isinstance(estado, int) else None


def _es_tecnico(e: Exception) -> bool:
    """True si el fallo es técnico (cuota, tamaño, servidor, timeout, conexión) y justifica reintentar o cambiar de modelo."""
    if isinstance(
        e,
        (groq.RateLimitError, groq.APIConnectionError, groq.InternalServerError, asyncio.TimeoutError, TimeoutError),
    ):
        return True
    estado = _estado_http(e)
    return estado in (413, 429) or (estado is not None and estado >= 500)


def _rechazo_json_transitorio(e: Exception) -> bool:
    """True si el 400 viene de que el modelo generó un JSON inválido (no de que no admita el modo JSON).

    Ese caso depende de la respuesta concreta, no del modelo, así que no debe recordarse.
    """
    texto = str(e).lower()
    return "json_validate_failed" in texto or "failed to generate json" in texto


# Pista de espera que Groq pone en sus 429: «try again in 19.8s», «try again in 2m3.5s» o «try again in 340ms».
# Los minutos se aceptan solo si no van seguidos de «s» (así «340ms» no se lee como 340 minutos).
_REINTENTO = re.compile(r"try again in\s+(?:(\d+)m(?!s))?\s*(?:(\d+(?:\.\d+)?)(ms|s))?", re.IGNORECASE)


def _segundos_de_reintento(e: Exception) -> float | None:
    """Segundos que Groq pide esperar según el mensaje del error, o None si el mensaje no trae la pista."""
    coincidencia = _REINTENTO.search(str(e))
    if coincidencia is None:
        return None
    minutos, valor, unidad = coincidencia.groups()
    # El patrón puede casar sin capturar nada («try again in» seguido de otra cosa): no hay pista.
    if minutos is None and valor is None:
        return None
    total = int(minutos) * 60.0 if minutos else 0.0
    if valor is not None:
        total += float(valor) / 1000 if unidad.lower() == "ms" else float(valor)
    return total


class ClienteGroq:
    """Cliente asíncrono de Groq con fallback técnico, reserva de tokens y registro de llamadas."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        modelos: dict[str, str] | None = None,
        orden_fallback: list[str] | None = None,
        fallback_por_rol: dict[str, list[str]] | None = None,
        roles_respaldo_por_falla: Iterable[str] | None = None,
        espera_antes_de_saltar_seg: float | None = None,
        reserva_salida_por_rol: dict[str, int] | None = None,
        extra_por_modelo: dict[str, dict[str, Any]] | None = None,
        calibrar_reserva: bool | None = None,
        calibracion_muestras: int | None = None,
        calibracion_min_muestras: int | None = None,
        calibracion_colchon: float | None = None,
        margen: float | None = None,
        limitador: LimitadorTokens | None = None,
        timeout_seg: float | None = None,
        espera_max_seg: float | None = None,
        max_intentos: int = 2,
        backoff_seg: float = 2.0,
        bloqueo_429_seg: float | None = None,
        bloqueo_429_max_seg: float | None = None,
        colchon_429_seg: float | None = None,
        max_tokens: int | None = None,
        sdk: Any = None,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        """Arma el cliente. `sdk`, `reloj` y `dormir` se inyectan en las pruebas (sin red ni esperas reales)."""
        clave = api_key if api_key is not None else config.GROQ_API_KEY
        # Sin clave y sin SDK inyectado no hay forma de llamar: se falla al construir, no a mitad de un run.
        if sdk is None and not clave:
            raise LLMError("sin_clave", "Falta GROQ_API_KEY en el entorno del servidor.")

        # Con modelos de config se usan también las cadenas, reservas y extras de config; con modelos
        # inyectados (pruebas) todo eso arranca vacío y el comportamiento anterior no cambia.
        desde_config = modelos is None

        self.modelos = modelos or {
            "estratega": config.GROQ_MODELO_ESTRATEGA,
            "redactor": config.GROQ_MODELO_REDACTOR,
            "revisor_a": config.GROQ_MODELO_REVISOR_A,
            "revisor_b": config.GROQ_MODELO_REVISOR_B,
        }
        # Orden de respaldo: el del spike (redactor, revisor A, revisor B), sin repetidos.
        base = orden_fallback or [
            config.GROQ_MODELO_REDACTOR,
            config.GROQ_MODELO_REVISOR_A,
            config.GROQ_MODELO_REVISOR_B,
        ]
        self.orden_fallback = list(dict.fromkeys(base))

        # Cadenas de fallback propias de un rol (revisor, estratega y redactor con los modelos de config).
        if fallback_por_rol is None:
            fallback_por_rol = (
                {
                    "revisor_a": config.GROQ_FALLBACK_REVISOR,
                    "revisor_b": config.GROQ_FALLBACK_REVISOR,
                    "estratega": config.GROQ_FALLBACK_ESTRATEGA,
                    "redactor": config.GROQ_FALLBACK_REDACTOR,
                }
                if desde_config
                else {}
            )
        self.fallback_por_rol = {rol: list(dict.fromkeys(cadena)) for rol, cadena in fallback_por_rol.items()}

        # Roles cuyo respaldo entra solo tras una falla técnica (no por falta de cupo del principal).
        if roles_respaldo_por_falla is None:
            roles_respaldo_por_falla = config.ROLES_RESPALDO_SOLO_POR_FALLA if desde_config else ()
        self.roles_respaldo_por_falla = frozenset(roles_respaldo_por_falla)
        self.espera_antes_de_saltar_seg = (
            espera_antes_de_saltar_seg if espera_antes_de_saltar_seg is not None
            else config.LLM_ESPERA_ANTES_DE_SALTAR_SEG
        )

        # Salida típica que se reserva por rol, y parámetros fijos por modelo (reasoning_effort de gpt-oss).
        if reserva_salida_por_rol is None:
            reserva_salida_por_rol = dict(config.LLM_RESERVA_SALIDA_POR_ROL) if desde_config else {}
        self.reserva_salida_por_rol = dict(reserva_salida_por_rol)
        if extra_por_modelo is None:
            extra_por_modelo = dict(config.GROQ_EXTRA_POR_MODELO) if desde_config else {}
        self.extra_por_modelo = {m: dict(p) for m, p in extra_por_modelo.items()}

        # Calibración de la reserva (tanda 2 de velocidad). Con config sigue LLM_CALIBRAR_RESERVA; con modelos
        # inyectados (pruebas) arranca apagada, para que los tests anteriores vean la misma reserva de siempre.
        if calibrar_reserva is None:
            calibrar_reserva = config.LLM_CALIBRAR_RESERVA if desde_config else False
        self.calibrar_reserva = calibrar_reserva
        # Tamaño de la ventana de muestras por rol, mínimo de muestras para fiarse y colchón (nunca menor que 1).
        self.calibracion_muestras = max(
            1, calibracion_muestras if calibracion_muestras is not None else config.LLM_CALIBRACION_MUESTRAS
        )
        self.calibracion_min_muestras = max(
            1, calibracion_min_muestras if calibracion_min_muestras is not None else config.LLM_CALIBRACION_MIN_MUESTRAS
        )
        self.calibracion_colchon = max(
            1.0, calibracion_colchon if calibracion_colchon is not None else config.LLM_CALIBRACION_COLCHON
        )
        # Lo aprendido por rol: caracteres por token de entrada y tokens de salida de las últimas respuestas reales.
        self._razon_entrada: dict[str, deque[float]] = {}
        self._salida_real: dict[str, deque[int]] = {}

        self.reloj = reloj
        self.dormir = dormir
        self.limitador = limitador or LimitadorTokens(
            tpm_defecto=config.GROQ_TPM, rpm_defecto=config.GROQ_RPM,
            tpm_por_modelo=dict(config.GROQ_TPM_POR_MODELO),
            margen=margen if margen is not None else config.GROQ_MARGEN,
            reloj=reloj,
        )
        self.timeout_seg = timeout_seg if timeout_seg is not None else config.LLM_TIMEOUT_SEG
        self.espera_max_seg = espera_max_seg if espera_max_seg is not None else config.LLM_ESPERA_MAX_SEG
        self.bloqueo_429_seg = bloqueo_429_seg if bloqueo_429_seg is not None else config.LLM_BLOQUEO_429_SEG
        # Bloqueo tras un 429 con pista de Groq: la pista más un colchón, sin pasar del tope.
        self.bloqueo_429_max_seg = (
            bloqueo_429_max_seg if bloqueo_429_max_seg is not None else config.LLM_BLOQUEO_429_MAX_SEG
        )
        self.colchon_429_seg = colchon_429_seg if colchon_429_seg is not None else config.LLM_COLCHON_429_SEG
        self.max_tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS
        self.max_intentos = max_intentos
        self.backoff_seg = backoff_seg

        # Reintentos internos del SDK desactivados: los reintentos son solo los de este cliente.
        self.sdk = sdk if sdk is not None else groq.AsyncGroq(api_key=clave, max_retries=0, timeout=self.timeout_seg)
        self.llamadas: deque[dict] = deque(maxlen=200)  # registro de diagnóstico (como el CALL_LOG del spike)
        # Modelos que rechazaron el modo JSON y aceptaron la misma petición sin él (ver docstring del módulo).
        self._sin_json: set[str] = set()

        # Contadores acumulados desde que arrancó el cliente (tanda 10A). Nunca se reinician: quien
        # quiera medir un tramo toma `metricas()` antes y después y resta.
        self._m_llamadas_red = 0  # peticiones reales enviadas a Groq (reintentos incluidos)
        self._m_espera_cupo = 0.0  # segundos dormidos esperando cupo del limitador
        self._m_tokens = 0  # tokens consumidos (reales si Groq los reporta, estimados si no)

    @property
    def modelos_sin_json(self) -> frozenset[str]:
        """Modelos a los que ya no se les envía `response_format` (lectura para pruebas y diagnóstico)."""
        return frozenset(self._sin_json)

    def metricas(self) -> dict[str, float]:
        """Contadores acumulados del cliente: peticiones a Groq, espera por cupo (s) y tokens.

        Son globales al cliente: si hay varios runs a la vez, el tramo medido incluye también
        lo que hicieron los otros. Para el diagnóstico de un run basta.
        """
        return {
            "llamadas_red": self._m_llamadas_red,
            "espera_cupo_seg": round(self._m_espera_cupo, 2),
            "tokens": self._m_tokens,
        }

    def _registrar(self, **datos: Any) -> None:
        """Guarda una entrada en el registro de llamadas."""
        self.llamadas.append(datos)

    def _bloqueo_429(self, reintento: float | None) -> float:
        """Segundos que se bloquea un modelo tras un 429: lo que pide Groq más el colchón, con tope.

        Sin pista en el mensaje se usa el bloqueo fijo de siempre.
        """
        # Sin pista de Groq no hay nada más preciso que el valor fijo.
        if reintento is None:
            return self.bloqueo_429_seg
        return min(reintento + self.colchon_429_seg, self.bloqueo_429_max_seg)

    async def _crear(
        self, modelo: str, mensajes: list[dict[str, str]], temperatura: float,
        json_mode: bool, max_tokens: int, extra: dict[str, Any] | None,
    ) -> Any:
        """Una sola llamada al SDK, con los parámetros ya resueltos."""
        kwargs: dict[str, Any] = dict(
            model=modelo, messages=mensajes, temperature=temperatura, max_completion_tokens=max_tokens
        )
        # Parámetros fijos del modelo (por ejemplo reasoning_effort en gpt-oss); qwen no recibe ninguno.
        kwargs.update(self.extra_por_modelo.get(modelo, {}))
        # Parámetros propios de la llamada que pasa el llamador: pisan a los fijos del modelo.
        if extra:
            kwargs.update(extra)
        # Modo JSON: pide a Groq que devuelva un objeto JSON válido.
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return await self.sdk.chat.completions.create(**kwargs)

    def _reserva_salida(self, rol: str, salida_max: int) -> int:
        """Tokens de salida que el limitador reserva: la salida típica del rol, nunca más que el tope pedido."""
        tipica = self.reserva_salida_por_rol.get(rol)
        # Sin valor para el rol (o con 0 o menos) se reserva el tope completo, como antes de la tanda 2A.
        if not tipica or tipica <= 0:
            return salida_max
        return min(tipica, salida_max)

    def _entrada_estimada(self, rol: str, caracteres: int) -> int:
        """Tokens de entrada que se reservan: calibrados con lo medido del rol, o la fórmula de siempre.

        Calibrada = caracteres / (razón caracteres-por-token más baja reciente) × colchón. Se usa la razón más
        baja porque es la que da MÁS tokens por carácter, o sea la más prudente de las recientes.
        """
        base = caracteres // 3 + 1  # fórmula de siempre (equivale a estimar_tokens)
        razones = self._razon_entrada.get(rol)
        # Sin calibración activa, o sin muestras suficientes, no hay nada mejor que la fórmula de siempre.
        if not self.calibrar_reserva or not razones or len(razones) < self.calibracion_min_muestras:
            return base
        return int(caracteres / min(razones) * self.calibracion_colchon) + 1

    def _salida_estimada(self, rol: str, salida_max: int) -> int:
        """Tokens de salida que se reservan: la mayor salida real reciente del rol (con colchón), o la reserva fija.

        Nunca pasa del tope `salida_max` que se envía a Groq.
        """
        fija = self._reserva_salida(rol, salida_max)  # reserva por rol de config (valor de arranque)
        muestras = self._salida_real.get(rol)
        # Sin calibración activa, o sin muestras suficientes, se mantiene la reserva fija.
        if not self.calibrar_reserva or not muestras or len(muestras) < self.calibracion_min_muestras:
            return fija
        return min(int(max(muestras) * self.calibracion_colchon) + 1, salida_max)

    def _aprender(self, rol: str, caracteres: int, entrada_real: Any, salida_real: Any, descartar_salida: bool) -> None:
        """Anota lo que gastó una respuesta real: caracteres por token de entrada y tokens de salida.

        Se anota siempre (aunque la calibración esté apagada) para que encenderla después ya tenga datos.
        `descartar_salida=True` (salida cortada o vacía) deja fuera la salida: no representa el gasto normal.
        """
        # Entrada: solo con un recuento de tokens válido; la razón se acota por arriba para no ser optimista.
        if caracteres > 0 and isinstance(entrada_real, int) and entrada_real > 0:
            razon = min(caracteres / entrada_real, RAZON_MAX_CHARS_POR_TOKEN)
            self._razon_entrada.setdefault(rol, deque(maxlen=self.calibracion_muestras)).append(razon)
        # Salida: solo con un recuento válido y si la respuesta no llegó cortada ni vacía.
        if not descartar_salida and isinstance(salida_real, int) and salida_real >= 0:
            self._salida_real.setdefault(rol, deque(maxlen=self.calibracion_muestras)).append(salida_real)

    async def completar(
        self,
        rol: str,
        mensajes: list[dict[str, str]],
        *,
        temperatura: float = 0.2,
        json_mode: bool = True,
        permitir_fallback: bool | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RespuestaLLM:
        """Pide una respuesta al modelo del `rol`, con espera de cupo y fallback técnico.

        `permitir_fallback=None` aplica el valor por defecto del rol: los revisores no admiten fallback, salvo
        que el rol tenga cadena propia en `fallback_por_rol` (entonces salta solo dentro de esa cadena).
        Los roles de `roles_respaldo_por_falla` solo pasan al respaldo tras una falla técnica del principal
        (o si este tendría que esperar más de `espera_antes_de_saltar_seg`). Ante un 429 de espera corta, esos
        roles esperan lo que indica Groq y reintentan en el mismo modelo (una vez por llamada).
        Lanza LLMError si no se puede responder (pedido demasiado grande, sin cupo a tiempo,
        todos los modelos fallaron o error no técnico de la API).
        """
        # Un rol desconocido es un error de programación, pero se informa con claridad.
        if rol not in self.modelos:
            raise LLMError("rol_invalido", f"Rol de LLM desconocido: {rol}")
        # Por defecto, los revisores no admiten fallback, salvo que el rol tenga una cadena propia.
        if permitir_fallback is None:
            permitir_fallback = rol in self.fallback_por_rol or rol not in ROLES_SIN_FALLBACK

        pedido = self.modelos[rol]
        # La cadena de respaldo es la propia del rol si existe y, si no, la general.
        respaldo = self.fallback_por_rol.get(rol, self.orden_fallback)
        cadena = [pedido] + ([m for m in respaldo if m != pedido] if permitir_fallback else [])
        salida_max = max_tokens if max_tokens is not None else self.max_tokens
        # Lo que se reserva antes de llamar: entrada estimada + salida típica del rol. Con la calibración activa
        # y muestras suficientes, ambas salen de lo que el rol gastó de verdad (tanda 2 de velocidad).
        caracteres = _caracteres(mensajes)
        estimado = self._entrada_estimada(rol, caracteres) + self._salida_estimada(rol, salida_max)
        respaldo_por_falla = permitir_fallback and rol in self.roles_respaldo_por_falla

        # Solo se consideran los modelos en cuyo presupuesto cabe el pedido.
        viables = [m for m in cadena if self.limitador.cabe_en_absoluto(m, estimado)]
        if not viables:
            raise LLMError(
                "pedido_demasiado_grande",
                f"El pedido (~{estimado} tokens) supera el límite de tokens por minuto de los modelos disponibles.",
            )

        t_inicio = self.reloj()  # inicio de la llamada completa (para `seg_total`)
        limite_total = t_inicio + self.espera_max_seg  # tope de espera acumulada por cupo
        espera_cupo = 0.0  # segundos que ESTA llamada lleva dormidos esperando cupo
        intentos_red = 0  # peticiones reales a Groq hechas por ESTA llamada
        intentos = dict.fromkeys(viables, 0)  # fallas técnicas por modelo en esta llamada
        # Modelos que en ESTA llamada rechazaron el modo JSON (el apagado es por modelo, no global a la llamada).
        sin_json_llamada: set[str] = set()
        # Subconjunto del anterior cuyo rechazo fue transitorio (JSON mal generado): no se recuerda al terminar.
        rechazo_transitorio: set[str] = set()
        ultimo_error: Exception | None = None
        motivo_salto: str | None = None  # por qué respondió un modelo distinto del pedido (None = el pedido)

        # Bucle principal: elegir un modelo con cupo, llamar, y reaccionar al resultado.
        while True:
            candidatos = [m for m in viables if intentos[m] < self.max_intentos]
            # Sin candidatos: todos los modelos agotaron sus intentos.
            if not candidatos:
                detalle = f" Último error: {type(ultimo_error).__name__}." if ultimo_error else ""
                raise LLMError("agotado", "Ningún modelo pudo responder por fallas técnicas." + detalle) from ultimo_error

            # Respaldo solo por falla: compite únicamente el primer modelo que sigue vivo (el principal, o el
            # siguiente tras una falla). Si tendría que esperar demasiado, entran también los demás (salto por cupo).
            if respaldo_por_falla:
                principal = candidatos[0]
                if self.limitador.espera_necesaria(principal, estimado) <= self.espera_antes_de_saltar_seg:
                    candidatos = [principal]

            con_cupo = [m for m in candidatos if self.limitador.espera_necesaria(m, estimado) <= 0]
            # Ninguno tiene cupo ahora: se espera al que antes lo tenga, dentro del tope.
            if not con_cupo:
                espera = min(self.limitador.espera_necesaria(m, estimado) for m in candidatos)
                if self.reloj() + espera > limite_total:
                    raise LLMError("sin_cupo", "No hubo cupo de tokens a tiempo; reintenta en un minuto.")
                log.info(
                    "LLM rol=%s esperando cupo %.1f s (acumulado en esta llamada: %.1f s)",
                    rol, espera + 0.05, espera_cupo + espera + 0.05,
                )
                await self.dormir(espera + 0.05)
                # Se anota lo dormido en la llamada y en el contador global del cliente.
                espera_cupo += espera + 0.05
                self._m_espera_cupo += espera + 0.05
                continue

            modelo = con_cupo[0]
            # Si no es el modelo pedido, se anota por qué (el log lo explica; antes solo quedaba fallback=True).
            if modelo == pedido:
                motivo_salto = None
            elif pedido not in intentos:
                motivo_salto = "no_cabe"  # el pedido no cabía en el presupuesto de su ventana
            elif intentos[pedido] >= self.max_intentos:
                motivo_salto = "falla_tecnica"  # el pedido falló antes (el WARNING de la falla ya quedó en el log)
            else:
                motivo_salto = "cupo"  # el pedido seguía vivo pero sin cupo, y otro modelo sí tenía
                log.info("LLM rol=%s salta de %s a %s por falta de cupo", rol, pedido, modelo)
            # El JSON se envía solo si se pidió y este modelo no lo rechazó (antes o en esta misma llamada).
            json_activo = json_mode and modelo not in self._sin_json and modelo not in sin_json_llamada
            reserva = self.limitador.reservar(modelo, estimado)
            intentos_red += 1  # una petición real a Groq (la cuenta incluye las que fallen)
            self._m_llamadas_red += 1
            t0 = self.reloj()
            try:
                resp = await asyncio.wait_for(
                    self._crear(modelo, mensajes, temperatura, json_activo, salida_max, extra),
                    self.timeout_seg,
                )
            except groq.BadRequestError as e:
                self.limitador.ajustar(reserva, 0)
                # Modo JSON rechazado: se reintenta en el mismo modelo sin response_format (queda registrado).
                # Si ese reintento sale bien, el modelo se recuerda más abajo; si vuelve a dar 400, no era el JSON.
                if json_activo:
                    log.warning("Groq rechazó el modo JSON en %s; se reintenta sin response_format", modelo)
                    self._registrar(rol=rol, pedido=pedido, modelo=modelo, error="BadRequest en JSON mode", seg=round(self.reloj() - t0, 2))
                    sin_json_llamada.add(modelo)
                    # Un JSON mal generado depende de la respuesta, no del modelo: no se recordará.
                    if _rechazo_json_transitorio(e):
                        rechazo_transitorio.add(modelo)
                    continue
                raise LLMError("error_api", f"La API rechazó el pedido: {str(e)[:200]}") from e
            except Exception as e:  # noqa: BLE001 - se clasifica abajo
                self.limitador.ajustar(reserva, 0)
                # Un error que no es técnico (configuración o uso) no se esconde con un fallback.
                if not _es_tecnico(e):
                    raise LLMError("error_api", f"Error de la API ({type(e).__name__}): {str(e)[:200]}") from e
                ultimo_error = e
                estado = _estado_http(e)
                # Deja constancia de la causa (código HTTP y mensaje de Groq): es lo que explica un fallback.
                log.warning(
                    "LLM rol=%s modelo=%s falló (%s, HTTP %s): %s",
                    rol, modelo, type(e).__name__, estado if estado is not None else "?", str(e)[:300],
                )
                self._registrar(rol=rol, pedido=pedido, modelo=modelo, error=f"{type(e).__name__}: {str(e)[:200]}", seg=round(self.reloj() - t0, 2))

                es_429 = isinstance(e, groq.RateLimitError) or estado == 429
                # Pista de Groq («try again in 2.34s»): None si el mensaje no la trae.
                reintento = _segundos_de_reintento(e) if es_429 else None
                # 429: el modelo se bloquea lo que Groq indica (o el valor fijo si no dice nada) para que
                # ni esta ni otras llamadas lo usen mientras tanto.
                if es_429:
                    self.limitador.bloquear(modelo, self._bloqueo_429(reintento))
                # 413 sin fallback: no hay otro modelo al que pasar.
                if estado == 413 and not permitir_fallback:
                    raise LLMError("pedido_demasiado_grande", f"El pedido excede el límite de {modelo}.") from e

                # Rol con respaldo solo por falla y un 429 de espera corta: se espera en el mismo modelo en vez
                # de gastar la ventana del respaldo (una sola vez por llamada; el segundo 429 sí salta).
                if (
                    es_429 and respaldo_por_falla and reintento is not None
                    and reintento + self.colchon_429_seg <= self.espera_antes_de_saltar_seg
                    and intentos[modelo] + 1 < self.max_intentos
                ):
                    intentos[modelo] += 1
                    log.info(
                        "LLM rol=%s modelo=%s: 429 con espera de %.1f s; se espera y se reintenta en el mismo modelo",
                        rol, modelo, reintento,
                    )
                    continue

                # Con fallback (o 413), el modelo se descarta y se pasa al siguiente de inmediato.
                if permitir_fallback or estado == 413:
                    intentos[modelo] = self.max_intentos
                else:
                    intentos[modelo] += 1
                    # Sin fallback se reintenta el mismo modelo con espera creciente (salvo 429, que ya espera por el bloqueo).
                    if estado != 429:
                        await self.dormir(self.backoff_seg * intentos[modelo])
                continue

            # Éxito: se extrae el texto y se corrige la reserva con el gasto real.
            eleccion = resp.choices[0]
            texto = eleccion.message.content or ""
            usage = getattr(resp, "usage", None)
            uso = usage.model_dump() if hasattr(usage, "model_dump") else None
            total = getattr(usage, "total_tokens", None)
            # Desglose real de Groq: entrada y salida por separado (alimenta la calibración y el log).
            entrada_real = getattr(usage, "prompt_tokens", None)
            salida_real = getattr(usage, "completion_tokens", None)
            # Si Groq reporta tokens, se usan; si no, queda la estimación.
            if isinstance(total, int):
                self.limitador.ajustar(reserva, total)
            # Contador global de tokens: el real si existe, y si no la estimación reservada.
            self._m_tokens += total if isinstance(total, int) else estimado
            seg = round(self.reloj() - t0, 2)
            respuesta = RespuestaLLM(
                texto=texto, modelo=modelo, pedido=pedido, fallback=(modelo != pedido),
                finish_reason=getattr(eleccion, "finish_reason", None), uso=uso, seg=seg,
                espera_cupo_seg=round(espera_cupo, 2), intentos_red=intentos_red,
                seg_total=round(self.reloj() - t_inicio, 2), motivo_salto=motivo_salto,
                reserva_tokens=estimado,
            )
            # La calibración aprende de esta respuesta (una salida cortada o vacía no cuenta como gasto normal).
            # Solo si contestó el modelo pedido: el respaldo (otro tokenizador, salidas más largas) falsearía las muestras.
            if not respuesta.fallback:
                self._aprender(rol, caracteres, entrada_real, salida_real, respuesta.truncada)
            self._registrar(
                rol=rol, pedido=pedido, modelo=modelo, fallback=respuesta.fallback,
                json_mode=json_activo, finish_reason=respuesta.finish_reason, seg=seg, error=None,
                seg_total=respuesta.seg_total, espera_cupo_seg=respuesta.espera_cupo_seg,
                intentos_red=intentos_red, tokens=total if isinstance(total, int) else None,
                motivo_salto=motivo_salto, reserva=estimado,
                tokens_entrada=entrada_real if isinstance(entrada_real, int) else None,
                tokens_salida=salida_real if isinstance(salida_real, int) else None,
            )
            # Una línea por llamada: de aquí sale la foto de dónde se va el tiempo de un run. Los campos nuevos
            # (in, out, reserva) van al final para no mover los que ya se leían.
            log.info(
                "LLM rol=%s modelo=%s fallback=%s seg=%.1f total=%.1f cupo=%.1f intentos=%d tokens=%s json=%s finish=%s salto=%s"
                " in=%s out=%s reserva=%d",
                rol, modelo, respuesta.fallback, seg, respuesta.seg_total, respuesta.espera_cupo_seg,
                intentos_red, total if isinstance(total, int) else "?", json_activo, respuesta.finish_reason,
                motivo_salto or "-",
                entrada_real if isinstance(entrada_real, int) else "?",
                salida_real if isinstance(salida_real, int) else "?",
                estimado,
            )
            # El modelo rechazó el JSON y la misma petición salió bien sin él: se recuerda para no repetir el fallo.
            if modelo in sin_json_llamada and modelo not in rechazo_transitorio and modelo not in self._sin_json:
                self._sin_json.add(modelo)
                log.info("Se recuerda que %s no admite el modo JSON; no se volverá a enviar response_format", modelo)
            # Una salida cortada o vacía no es un error técnico, pero conviene dejar constancia.
            if respuesta.truncada:
                log.warning("Respuesta truncada o vacía de %s (finish_reason=%s)", modelo, respuesta.finish_reason)
            return respuesta