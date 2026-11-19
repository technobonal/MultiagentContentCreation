"""Punto de entrada de FastAPI. Arranque: uvicorn app.main:app --reload --port 8000

IMPORTANTE: las ejecuciones viven en la memoria del proceso, así que en producción se usa UN solo worker
(sin --workers N). Al reiniciar el servidor se pierden y el lienzo recibe un 404 visible.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.rutas import router
from app.runs.registro import obtener_registro_runs


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Al apagar la app cancela las ejecuciones que sigan en curso."""
    yield
    # Si una prueba reemplazó el registro con dependency_overrides, se cancela ese y no el real.
    registro = app.dependency_overrides.get(obtener_registro_runs, obtener_registro_runs)()
    await registro.cancelar_todo()


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
