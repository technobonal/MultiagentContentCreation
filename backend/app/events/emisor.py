"""Emisor SSE: valida, espacia y formatea los eventos para el canal.

Reglas del contrato que implementa:
  - Cada evento sale con `id: <seq>` (así EventSource envía Last-Event-ID al reconectar).
  - Cada evento se valida antes de emitirse; uno inválido produce un evento SSE
    `evento_invalido` (visible) y el flujo se detiene. Nunca se omite en silencio.
  - Los eventos válidos salen tal cual, sin tocar `origen`.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

from app.events.validador import comprobar_evento


def formatear_sse(datos: dict, id_evento: int | None = None, nombre: str | None = None) -> str:
    """Arma un mensaje SSE (id, event y data terminados por línea en blanco).

    Sin `nombre` el navegador lo entrega a `onmessage`; con `nombre` hay que
    escucharlo con addEventListener.
    """
    lineas = []
    # El id solo se incluye en eventos del contrato: los de error no mueven el Last-Event-ID.
    if id_evento is not None:
        lineas.append(f"id: {id_evento}")
    # El nombre solo se incluye en mensajes especiales (por ejemplo, evento_invalido).
    if nombre is not None:
        lineas.append(f"event: {nombre}")
    # JSON en una sola línea: los saltos de línea dentro de textos van escapados.
    lineas.append("data: " + json.dumps(datos, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lineas) + "\n\n"


def filtrar_desde(eventos: list, desde_seq: int) -> list:
    """Devuelve los eventos con seq mayor que `desde_seq` (reanudación por Last-Event-ID)."""
    pendientes = []
    for evento in eventos:  # revisa cada evento de la secuencia
        seq = evento.get("seq") if isinstance(evento, dict) else None
        # Un seq ausente o no entero no se descarta: debe llegar al validador y verse como error.
        if not isinstance(seq, int) or seq > desde_seq:
            pendientes.append(evento)
    return pendientes


def _espera_entre(anterior: str | None, actual: str, brecha_max: float) -> float:
    """Segundos a esperar antes de emitir: la brecha original entre timestamps, con tope."""
    # Sin evento previo (primero del flujo) o con tope 0 no se espera.
    if anterior is None or brecha_max <= 0:
        return 0.0
    try:
        delta = (datetime.fromisoformat(actual) - datetime.fromisoformat(anterior)).total_seconds()
    except (ValueError, TypeError):
        return 0.0  # timestamp ilegible o con/sin zona horaria mezclada: no se espera
    # Nunca negativa y nunca mayor que el tope.
    return min(max(delta, 0.0), brecha_max)


async def flujo_sse(
    eventos: list,
    brecha_max: float,
    dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    """Genera los mensajes SSE de una lista de eventos ya ordenada y filtrada.

    `dormir` se inyecta para que las pruebas no esperen de verdad.
    """
    timestamp_anterior = None
    for evento in eventos:  # un mensaje SSE por evento, en orden por seq
        motivos = comprobar_evento(evento)
        # Evento inválido: se avisa con un mensaje visible y se corta el flujo.
        if motivos:
            info = evento if isinstance(evento, dict) else {}
            yield formatear_sse(
                {"seq": info.get("seq"), "tipo": info.get("tipo"), "motivos": motivos},
                nombre="evento_invalido",
            )
            return
        espera = _espera_entre(timestamp_anterior, evento["timestamp"], brecha_max)
        # Solo se duerme si hay una brecha real que respetar.
        if espera > 0:
            await dormir(espera)
        yield formatear_sse(evento, id_evento=evento["seq"])
        timestamp_anterior = evento["timestamp"]