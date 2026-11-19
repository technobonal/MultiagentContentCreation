"""Rutas HTTP del backend: iniciar una ejecución (POST) y su canal SSE de eventos (GET)."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app import config
from app.events.cargador import RunNoEncontrado, cargar_eventos
from app.events.emisor import filtrar_desde, flujo_sse, flujo_vivo
from app.events.validador import comprobar_entrada
from app.resolution import cargar_fichas, resolver
from app.runs.orquestador import ejecutar_run
from app.runs.registro import EstadoRun, LimiteDeRuns, RegistroRuns, obtener_registro_runs
from app.runs.relleno import ORIGEN_RELLENO

router = APIRouter(prefix="/api")

# Cabeceras de toda respuesta SSE.
CABECERAS_SSE = {
    "Cache-Control": "no-cache",  # un flujo vivo no se cachea
    "X-Accel-Buffering": "no",  # Nginx (OCI) no debe acumular el flujo en un buffer
}


def obtener_brecha_max() -> float:
    """Dependencia que entrega la brecha máxima; las pruebas la reemplazan por 0."""
    return config.BRECHA_MAX_SEG


def obtener_ritmo_relleno() -> float:
    """Dependencia que entrega la pausa entre eventos del relleno; las pruebas la reemplazan por 0."""
    return config.RITMO_RELLENO_SEG


def obtener_latido() -> float:
    """Dependencia que entrega los segundos entre latidos del SSE; las pruebas pueden acortarla."""
    return config.LATIDO_SEG


def _rechazo(codigo: int, motivos: list[str], cabeceras: dict | None = None) -> JSONResponse:
    """Respuesta de error con la lista de motivos (mismo formato que evento_invalido)."""
    return JSONResponse(status_code=codigo, content={"motivos": motivos}, headers=cabeceras)


@router.post("/runs", status_code=201)
async def iniciar_run(
    request: Request,
    registro: RegistroRuns = Depends(obtener_registro_runs),
    ritmo_relleno: float = Depends(obtener_ritmo_relleno),
):
    """Valida la entrada (forma y reglas cruzadas), crea la ejecución y lanza el orquestador.

    Responde 201 con el run_id y la URL del canal de eventos. El cuerpo se valida contra
    input.schema.json (la única fuente de verdad), no contra un modelo Pydantic.
    """
    try:
        entrada = await request.json()
    except ValueError:  # cuerpo vacío, no JSON o con codificación inválida
        return _rechazo(422, ["el cuerpo no es un JSON válido"])

    motivos = comprobar_entrada(entrada)  # forma
    if motivos:
        return _rechazo(422, motivos)

    resolucion, motivos = resolver(entrada, cargar_fichas())  # reglas que cruzan archivos
    if motivos:
        return _rechazo(422, motivos)

    try:
        ejecucion = registro.crear(entrada, resolucion, ORIGEN_RELLENO)
    except LimiteDeRuns as exc:  # demasiadas ejecuciones en curso: que reintente en unos segundos
        return _rechazo(429, [str(exc)], {"Retry-After": "10"})

    registro.lanzar(ejecutar_run(ejecucion, ritmo_relleno))
    return {"run_id": ejecucion.run_id, "url_eventos": f"/api/runs/{ejecucion.run_id}/eventos"}


@router.get("/runs/{run_id}/eventos")
async def eventos_de_run(
    run_id: str,
    last_event_id: str | None = Header(default=None),  # llega como cabecera Last-Event-ID
    # EventSource no permite fijar cabeceras a mano: el cliente usa ?desde=N para pedir de nuevo lo que falta.
    desde: int | None = Query(default=None, ge=0),
    brecha_max: float = Depends(obtener_brecha_max),
    latido: float = Depends(obtener_latido),
    registro: RegistroRuns = Depends(obtener_registro_runs),
):
    """Emite por SSE los eventos de una ejecución (en vivo o grabada).

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

    # Primero se busca entre las ejecuciones vivas; si no está, entre las grabaciones.
    ejecucion = registro.obtener(run_id)
    if ejecucion is not None:
        # Reconexión sin nada pendiente: 204 solo si la ejecución TERMINÓ; en curso hay que esperar
        # y una fallida debe volver a entregar su error (no lleva id y pudo perderse).
        if desde_seq > 0 and desde_seq >= len(ejecucion.eventos) and ejecucion.estado == EstadoRun.TERMINADA:
            return Response(status_code=204)
        return StreamingResponse(
            flujo_vivo(ejecucion, desde_seq, latido),
            media_type="text/event-stream",
            headers=CABECERAS_SSE,
        )

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
        headers=CABECERAS_SSE,
    )
