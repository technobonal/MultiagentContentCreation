"""Rutas HTTP del backend. Por ahora: el canal SSE de eventos de una ejecución."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app import config
from app.events.cargador import RunNoEncontrado, cargar_eventos
from app.events.emisor import filtrar_desde, flujo_sse

router = APIRouter(prefix="/api")


def obtener_brecha_max() -> float:
    """Dependencia que entrega la brecha máxima; las pruebas la reemplazan por 0."""
    return config.BRECHA_MAX_SEG


@router.get("/runs/{run_id}/eventos")
async def eventos_de_run(
    run_id: str,
    last_event_id: str | None = Header(default=None),  # llega como cabecera Last-Event-ID
    # EventSource no permite fijar cabeceras a mano: el cliente usa ?desde=N para pedir de nuevo lo que falta.
    desde: int | None = Query(default=None, ge=0),
    brecha_max: float = Depends(obtener_brecha_max),
):
    """Emite por SSE los eventos de una ejecución.

    Reanudación: manda la cabecera Last-Event-ID si viene; si no, el parámetro ?desde=N.
    Solo se reenvían los eventos con seq mayor que ese valor.
    """
    desde_seq = 0  # 0 = primera conexión, se envía todo

    # La cabecera tiene prioridad: es lo que envía el navegador al reconectar solo.
    if last_event_id is not None:
        try:
            desde_seq = int(last_event_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID debe ser un entero")
        # Un seq negativo no existe en el contrato (empieza en 1).
        if desde_seq < 0:
            raise HTTPException(status_code=400, detail="Last-Event-ID no puede ser negativo")
    # Sin cabecera, se usa ?desde=N (FastAPI ya validó que sea entero >= 0).
    elif desde is not None:
        desde_seq = desde

    try:
        eventos = cargar_eventos(run_id)
    except RunNoEncontrado:
        raise HTTPException(status_code=404, detail=f"No existe la ejecución {run_id}")

    pendientes = filtrar_desde(eventos, desde_seq)
    # Reconexión sin nada pendiente: 204 le indica a EventSource que deje de reconectar.
    if desde_seq > 0 and not pendientes:
        return Response(status_code=204)

    return StreamingResponse(
        flujo_sse(pendientes, brecha_max),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",  # un flujo vivo no se cachea
            "X-Accel-Buffering": "no",  # Nginx (OCI) no debe acumular el flujo en un buffer
        },
    )