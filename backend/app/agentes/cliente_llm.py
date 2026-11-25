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
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import groq

from app import config

log = logging.getLogger(__name__)

# Roles que por defecto NO admiten fallback (el revisor debe correr con su propio modelo).
ROLES_SIN_FALLBACK = ("revisor_a", "revisor_b")


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
    seg: float

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


def estimar_tokens(mensajes: list[dict[str, str]]) -> int:
    """Estimación prudente de tokens de entrada: 1 token por cada 3 caracteres (sobreestima a propósito)."""
    return sum(len(str(m.get("content") or "")) for m in mensajes) // 3 + 1


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
        self._ventana(modelo).bloqueado_hasta = self.reloj() + segundos

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


class ClienteGroq:
    """Cliente asíncrono de Groq con fallback técnico, reserva de tokens y registro de llamadas."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        modelos: dict[str, str] | None = None,
        orden_fallback: list[str] | None = None,
        limitador: LimitadorTokens | None = None,
        timeout_seg: float | None = None,
        espera_max_seg: float | None = None,
        max_intentos: int = 2,
        backoff_seg: float = 2.0,
        bloqueo_429_seg: float | None = None,
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

        self.reloj = reloj
        self.dormir = dormir
        self.limitador = limitador or LimitadorTokens(
            tpm_defecto=config.GROQ_TPM, rpm_defecto=config.GROQ_RPM, reloj=reloj
        )
        self.timeout_seg = timeout_seg if timeout_seg is not None else config.LLM_TIMEOUT_SEG
        self.espera_max_seg = espera_max_seg if espera_max_seg is not None else config.LLM_ESPERA_MAX_SEG
        self.bloqueo_429_seg = bloqueo_429_seg if bloqueo_429_seg is not None else config.LLM_BLOQUEO_429_SEG
        self.max_tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS
        self.max_intentos = max_intentos
        self.backoff_seg = backoff_seg

        # Reintentos internos del SDK desactivados: los reintentos son solo los de este cliente.
        self.sdk = sdk if sdk is not None else groq.AsyncGroq(api_key=clave, max_retries=0, timeout=self.timeout_seg)
        self.llamadas: deque[dict] = deque(maxlen=200)  # registro de diagnóstico (como el CALL_LOG del spike)
        # Modelos que rechazaron el modo JSON y aceptaron la misma petición sin él (ver docstring del módulo).
        self._sin_json: set[str] = set()

    @property
    def modelos_sin_json(self) -> frozenset[str]:
        """Modelos a los que ya no se les envía `response_format` (lectura para pruebas y diagnóstico)."""
        return frozenset(self._sin_json)

    def _registrar(self, **datos: Any) -> None:
        """Guarda una entrada en el registro de llamadas."""
        self.llamadas.append(datos)

    async def _crear(
        self, modelo: str, mensajes: list[dict[str, str]], temperatura: float,
        json_mode: bool, max_tokens: int, extra: dict[str, Any] | None,
    ) -> Any:
        """Una sola llamada al SDK, con los parámetros ya resueltos."""
        kwargs: dict[str, Any] = dict(
            model=modelo, messages=mensajes, temperature=temperatura, max_completion_tokens=max_tokens
        )
        # Parámetros propios de un modelo (por ejemplo reasoning_effort) que pasa el llamador.
        if extra:
            kwargs.update(extra)
        # Modo JSON: pide a Groq que devuelva un objeto JSON válido.
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return await self.sdk.chat.completions.create(**kwargs)

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

        `permitir_fallback=None` aplica el valor por defecto del rol (los revisores, sin fallback).
        Lanza LLMError si no se puede responder (pedido demasiado grande, sin cupo a tiempo,
        todos los modelos fallaron o error no técnico de la API).
        """
        # Un rol desconocido es un error de programación, pero se informa con claridad.
        if rol not in self.modelos:
            raise LLMError("rol_invalido", f"Rol de LLM desconocido: {rol}")
        # Por defecto, los revisores no admiten fallback.
        if permitir_fallback is None:
            permitir_fallback = rol not in ROLES_SIN_FALLBACK

        pedido = self.modelos[rol]
        cadena = [pedido] + ([m for m in self.orden_fallback if m != pedido] if permitir_fallback else [])
        salida_max = max_tokens if max_tokens is not None else self.max_tokens
        estimado = estimar_tokens(mensajes) + salida_max  # lo que se reserva antes de llamar

        # Solo se consideran los modelos en cuyo presupuesto cabe el pedido.
        viables = [m for m in cadena if self.limitador.cabe_en_absoluto(m, estimado)]
        if not viables:
            raise LLMError(
                "pedido_demasiado_grande",
                f"El pedido (~{estimado} tokens) supera el límite de tokens por minuto de los modelos disponibles.",
            )

        limite_total = self.reloj() + self.espera_max_seg  # tope de espera acumulada por cupo
        intentos = dict.fromkeys(viables, 0)  # fallas técnicas por modelo en esta llamada
        # Modelos que en ESTA llamada rechazaron el modo JSON (el apagado es por modelo, no global a la llamada).
        sin_json_llamada: set[str] = set()
        # Subconjunto del anterior cuyo rechazo fue transitorio (JSON mal generado): no se recuerda al terminar.
        rechazo_transitorio: set[str] = set()
        ultimo_error: Exception | None = None

        # Bucle principal: elegir un modelo con cupo, llamar, y reaccionar al resultado.
        while True:
            candidatos = [m for m in viables if intentos[m] < self.max_intentos]
            # Sin candidatos: todos los modelos agotaron sus intentos.
            if not candidatos:
                detalle = f" Último error: {type(ultimo_error).__name__}." if ultimo_error else ""
                raise LLMError("agotado", "Ningún modelo pudo responder por fallas técnicas." + detalle) from ultimo_error

            con_cupo = [m for m in candidatos if self.limitador.espera_necesaria(m, estimado) <= 0]
            # Ninguno tiene cupo ahora: se espera al que antes lo tenga, dentro del tope.
            if not con_cupo:
                espera = min(self.limitador.espera_necesaria(m, estimado) for m in candidatos)
                if self.reloj() + espera > limite_total:
                    raise LLMError("sin_cupo", "No hubo cupo de tokens a tiempo; reintenta en un minuto.")
                await self.dormir(espera + 0.05)
                continue

            modelo = con_cupo[0]
            # El JSON se envía solo si se pidió y este modelo no lo rechazó (antes o en esta misma llamada).
            json_activo = json_mode and modelo not in self._sin_json and modelo not in sin_json_llamada
            reserva = self.limitador.reservar(modelo, estimado)
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
                self._registrar(rol=rol, pedido=pedido, modelo=modelo, error=f"{type(e).__name__}: {str(e)[:200]}", seg=round(self.reloj() - t0, 2))

                # 429: el modelo se bloquea un rato para que ni esta ni otras llamadas lo usen.
                if isinstance(e, groq.RateLimitError) or estado == 429:
                    self.limitador.bloquear(modelo, self.bloqueo_429_seg)
                # 413 sin fallback: no hay otro modelo al que pasar.
                if estado == 413 and not permitir_fallback:
                    raise LLMError("pedido_demasiado_grande", f"El pedido excede el límite de {modelo}.") from e

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
            # Si Groq reporta tokens, se usan; si no, queda la estimación.
            if isinstance(total, int):
                self.limitador.ajustar(reserva, total)
            seg = round(self.reloj() - t0, 2)
            respuesta = RespuestaLLM(
                texto=texto, modelo=modelo, pedido=pedido, fallback=(modelo != pedido),
                finish_reason=getattr(eleccion, "finish_reason", None), uso=uso, seg=seg,
            )
            self._registrar(
                rol=rol, pedido=pedido, modelo=modelo, fallback=respuesta.fallback,
                json_mode=json_activo, finish_reason=respuesta.finish_reason, seg=seg, error=None,
            )
            # El modelo rechazó el JSON y la misma petición salió bien sin él: se recuerda para no repetir el fallo.
            if modelo in sin_json_llamada and modelo not in rechazo_transitorio and modelo not in self._sin_json:
                self._sin_json.add(modelo)
                log.info("Se recuerda que %s no admite el modo JSON; no se volverá a enviar response_format", modelo)
            # Una salida cortada o vacía no es un error técnico, pero conviene dejar constancia.
            if respuesta.truncada:
                log.warning("Respuesta truncada o vacía de %s (finish_reason=%s)", modelo, respuesta.finish_reason)
            return respuesta