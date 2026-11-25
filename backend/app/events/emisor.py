"""Emisor SSE: valida, espacia y formatea los eventos para el canal.

Reglas del contrato que implementa:
  - Cada evento sale con `id: <seq>` (así EventSource envía Last-Event-ID al reconectar).
  - Cada evento se valida antes de emitirse; uno inválido produce un evento SSE
    `evento_invalido` (visible) y el flujo se detiene. Nunca se omite en silencio.
  - Los eventos válidos salen tal cual, sin tocar `origen`.

Dos flujos: `flujo_sse` para listas cerradas (grabaciones) y `flujo_vivo` para ejecuciones en curso.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

from app.events.validador import comprobar_evento
from app.runs.registro import Ejecucion, EstadoRun

# Comentario SSE: lo ignora EventSource, pero mantiene viva la conexión a través de Nginx.
LATIDO_SSE = ": ping\n\n"


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


async def flujo_vivo(
    ejecucion: Ejecucion,
    desde_seq: int,
    latido_seg: float,
    ritmo: float | None = None,
    brecha_max: float = 0.0,
    dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    """Genera los mensajes SSE de una ejecución en curso, esperando los eventos que aún no llegan.

    Los eventos del buffer ya están validados al emitirse y su ritmo lo marca el orquestador, así que
    aquí no se revalida. Termina cuando la ejecución se cierra y no queda nada pendiente.

    Repetición animada: con `ritmo` (1, 2, 3...) los eventos que YA estaban guardados al conectar se
    reenvían con su brecha original (tope `brecha_max`) dividida por `ritmo`, para ver un run terminado
    en movimiento. Los eventos que lleguen después salen sin espaciar, igual que sin `ritmo`.
    """
    indice = desde_seq  # el seq es consecutivo desde 1: el evento siguiente a desde_seq está en ese índice
    guardados = len(ejecucion.eventos)  # solo estos se espacian; lo posterior ya llega con su ritmo real
    timestamp_anterior = None
    while True:  # sigue hasta que la ejecución se cierre y se agote el buffer
        # Hay eventos pendientes: se entregan en orden.
        if indice < len(ejecucion.eventos):
            evento = ejecucion.eventos[indice]
            if ritmo and indice < guardados:
                espera = _espera_entre(timestamp_anterior, evento["timestamp"], brecha_max) / ritmo
                if espera > 0:
                    await dormir(espera)
                timestamp_anterior = evento["timestamp"]
            indice += 1
            yield formatear_sse(evento, id_evento=evento["seq"])
            continue
        # Sin pendientes y la ejecución cerrada: se entrega el error si lo hubo y termina el flujo.
        if ejecucion.estado != EstadoRun.EN_CURSO:
            if ejecucion.fallo is not None:  # el error no lleva id: no mueve el Last-Event-ID
                yield formatear_sse(ejecucion.fallo["datos"], nombre=ejecucion.fallo["nombre"])
            return
        # La ejecución sigue en curso: se espera un evento nuevo o se manda un latido.
        if not await ejecucion.esperar_cambio(indice, latido_seg):
            yield LATIDO_SSE
