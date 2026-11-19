"""Orquestador: una corutina por ejecución que emite eventos al buffer de su Ejecucion.

En el paso 1 reproduce el guion de relleno (sin LLM). Desde el paso 2 el mismo orquestador
llama a los agentes reales. Un evento inválido corta la ejecución con error visible; cualquier
otro fallo la marca fallida con un mensaje `run_error` (el detalle queda en el registro del servidor).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.runs import relleno
from app.runs.registro import Ejecucion, EventoInvalido

log = logging.getLogger(__name__)


async def ejecutar_run(
    ejecucion: Ejecucion,
    ritmo_seg: float,
    dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Emite todos los eventos de la ejecución, con `ritmo_seg` de pausa entre uno y otro.

    `dormir` se inyecta para que las pruebas no esperen de verdad.
    """
    try:
        color = relleno.color_de_fondo(ejecucion.entrada)
        guion = relleno.construir_guion(ejecucion.run_id, ejecucion.entrada, ejecucion.resolucion, color)
        for i, paso in enumerate(guion):  # un evento por paso del guion, en orden
            # La primera emisión sale sin pausa; las demás respetan el ritmo.
            if i > 0 and ritmo_seg > 0:
                await dormir(ritmo_seg)
            await ejecucion.emitir(**paso)
        await ejecucion.cerrar()
    except EventoInvalido:
        # La Ejecucion ya quedó FALLIDA con los motivos; no hay nada más que hacer.
        log.error("Evento inválido en %s: la ejecución se cortó", ejecucion.run_id)
    except asyncio.CancelledError:
        # Apagado del servidor: se avisa a los lectores y se deja propagar la cancelación.
        await ejecucion.fallar("La ejecución se canceló porque el servidor se apagó.")
        raise
    except Exception as exc:  # cualquier fallo inesperado: visible, pero sin filtrar detalles al cliente
        log.exception("Fallo inesperado en %s", ejecucion.run_id)
        await ejecucion.fallar(
            f"Error inesperado del orquestador ({type(exc).__name__}); el detalle está en el registro del servidor."
        )
