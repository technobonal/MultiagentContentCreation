"""Punto de entrada de FastAPI. Arranque: uvicorn app.main:app --reload --port 8000

IMPORTANTE: las ejecuciones viven en la memoria del proceso, así que en producción se usa UN solo worker
(sin --workers N). Al reiniciar el servidor se pierden y el lienzo recibe un 404 visible.

Modo de ejecución (variable MODO_RUN): "relleno" (simulado, por defecto) o "real" (agentes con Groq).
La decisión se toma UNA sola vez, al arrancar: app.state.contexto es None en relleno y el contexto real
(cliente Groq + kit de marca) en modo real. Las rutas solo miran si hay contexto.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.rutas import router
from app.runs.contexto_real import construir_contexto
from app.runs.registro import obtener_registro_runs


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Al arrancar prepara el contexto real (si aplica); al apagar cancela las ejecuciones y cierra el cliente."""
    contexto = None
    # Solo en modo real hace falta el contexto; si falta la clave de Groq o el kit, el arranque falla aquí.
    if config.MODO_RUN == "real":
        contexto = construir_contexto()
    app.state.contexto = contexto  # None = modo relleno

    try:
        yield
    finally:
        # Si una prueba reemplazó el registro con dependency_overrides, se cancela ese y no el real.
        registro = app.dependency_overrides.get(obtener_registro_runs, obtener_registro_runs)()
        try:
            # Primero se cancelan las ejecuciones: así ninguna usa el cliente HTTP después de cerrarlo.
            await registro.cancelar_todo()
        finally:
            # El cliente se cierra siempre, aunque la cancelación haya fallado.
            if contexto is not None:
                await contexto.cerrar()
            # Ya cerrado, el contexto no debe quedar en app.state (si no, otra arrancada de la misma app lo reutilizaría).
            app.state.contexto = None


app = FastAPI(title="MultiagentContentCreation API", lifespan=ciclo_de_vida)

# CORS solo si se configuró CORS_ORIGENES; en desarrollo basta el proxy de Vite.
if config.CORS_ORIGENES:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGENES,
        allow_methods=["GET", "POST"],  # POST inicia ejecuciones
        allow_headers=["Last-Event-ID", "Content-Type"],  # Content-Type: el POST envía JSON
    )

app.include_router(router)