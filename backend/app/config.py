"""Configuración del backend: rutas y límites.

Los valores se leen del entorno para poder ajustarlos sin tocar código
(por ejemplo, en OCI). Si la variable no existe, se usa el valor por defecto.
"""

import os
from pathlib import Path

# Raíz del proyecto: este archivo vive en backend/app/, así que se suben dos niveles.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Carpeta con los esquemas JSON (fuente de verdad compartida con el frontend).
CONTRATOS_DIR = RAIZ_PROYECTO / "contracts"

# Carpeta con las secuencias grabadas (origen "grabado").
GRABACIONES_DIR = CONTRATOS_DIR / "recordings"

# Brecha máxima, en segundos, entre dos eventos consecutivos al emitirlos.
# Si el valor del entorno no es un número, falla al arrancar (error visible, no silencioso).
BRECHA_MAX_SEG = float(os.environ.get("BRECHA_MAX_SEG", "2"))

# Tamaño máximo de un evento serializado, en bytes (64 KB por defecto).
TAM_MAX_EVENTO_BYTES = int(os.environ.get("TAM_MAX_EVENTO_BYTES", str(64 * 1024)))

# Orígenes permitidos por CORS, separados por coma. Vacío = sin CORS (se usa el proxy de Vite).
CORS_ORIGENES = [
    origen.strip()
    for origen in os.environ.get("CORS_ORIGENES", "").split(",")
    if origen.strip()  # descarta entradas vacías (por ejemplo, una coma final)
]