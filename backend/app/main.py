"""Punto de entrada de FastAPI. Arranque: uvicorn app.main:app --reload --port 8000"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.rutas import router

app = FastAPI(title="MultiagentContentCreation API")

# CORS solo si se configuró CORS_ORIGENES; en desarrollo basta el proxy de Vite.
if config.CORS_ORIGENES:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGENES,
        allow_methods=["GET"],
        allow_headers=["Last-Event-ID"],
    )

app.include_router(router)