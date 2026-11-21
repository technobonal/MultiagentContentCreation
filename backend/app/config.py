"""Configuración del backend: rutas y límites.

Los valores se leen del entorno para poder ajustarlos sin tocar código
(por ejemplo, en OCI). Si la variable no existe, se usa el valor por defecto.
"""

import os
from pathlib import Path

# Raíz del proyecto: este archivo vive en backend/app/, así que se suben dos niveles.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

# Si existe un archivo .env en la raíz (y python-dotenv está instalado), se cargan sus variables.
# Nunca pisa variables ya definidas en el entorno. El .env NO debe subirse a git.
try:
    from dotenv import load_dotenv

    load_dotenv(RAIZ_PROYECTO / ".env", override=False)
except ImportError:
    pass  # sin python-dotenv, solo se usa el entorno del sistema

# Carpeta con los esquemas JSON (fuente de verdad compartida con el frontend).
CONTRATOS_DIR = RAIZ_PROYECTO / "contracts"

# Carpeta con las secuencias grabadas (origen "grabado").
GRABACIONES_DIR = CONTRATOS_DIR / "recordings"

# Catálogo de plantillas: una carpeta por plantilla, con su card.json dentro.
CATALOGO_DIR = RAIZ_PROYECTO / "templates" / "catalog"

# Carpeta con los kits de marca y nombre (sin .json) del kit que usa el relleno del paso 1.
KITS_DIR = RAIZ_PROYECTO / "templates" / "brand-kits"
KIT_MARCA = os.environ.get("KIT_MARCA", "mvp")

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

# Modo de ejecución de POST /api/runs: "relleno" (secuencia grabada, sin LLM) o "real" (agentes con Groq).
# Se normaliza (espacios y mayúsculas) y un valor vacío cuenta como "relleno". Un valor inválido
# falla al arrancar (error visible, no silencioso).
MODOS_RUN = ("relleno", "real")
MODO_RUN = os.environ.get("MODO_RUN", "").strip().lower() or "relleno"
if MODO_RUN not in MODOS_RUN:  # valor fuera de la lista: no se arranca con un modo desconocido
    raise ValueError(f"MODO_RUN debe ser uno de {MODOS_RUN}; llegó {MODO_RUN!r}")

# Ejecuciones simultáneas en curso. Superado el límite, POST /api/runs responde 429.
# En modo real el límite por defecto es menor (2): los runs comparten el cupo de tokens de Groq,
# así que más ejecuciones a la vez solo se encolan y parecen congeladas.
MAX_RUNS_ACTIVOS = int(os.environ.get("MAX_RUNS_ACTIVOS", "2" if MODO_RUN == "real" else "3"))

# Ejecuciones terminadas que se conservan en memoria; las más viejas se descartan.
MAX_RUNS_CONSERVADOS = int(os.environ.get("MAX_RUNS_CONSERVADOS", "20"))

# Pausa, en segundos, entre eventos del relleno (para que el lienzo se vea avanzar).
RITMO_RELLENO_SEG = float(os.environ.get("RITMO_RELLENO_SEG", "0.6"))

# Cada cuántos segundos sin eventos se envía un latido ": ping" (Nginx corta a los 60 s sin tráfico).
LATIDO_SEG = float(os.environ.get("LATIDO_SEG", "15"))

# --- Paso 2 (fase 2): carga de la fuente ---

# Carpeta del servidor donde viven las fuentes (.md y .txt). La `referencia` de la
# entrada se resuelve solo por nombre de archivo dentro de esta carpeta.
FUENTES_DIR = Path(os.environ.get("FUENTES_DIR", str(RAIZ_PROYECTO / "backend" / "fuentes")))

# Tamaño máximo de un archivo de fuente, en bytes (200 KB por defecto).
FUENTE_MAX_BYTES = int(os.environ.get("FUENTE_MAX_BYTES", str(200 * 1024)))

# Tamaño máximo, en caracteres, de cada fragmento en que se indexa la fuente.
FRAGMENTO_MAX_CHARS = int(os.environ.get("FRAGMENTO_MAX_CHARS", "1000"))

# --- Paso 2 (fase 2): cliente LLM (Groq) ---

# Clave de Groq. Vacía = sin clave (el modo real no arranca; MODO_RUN=relleno sigue disponible).
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Modelos por rol (los del spike de fidelidad v3b). Redactor y revisores deben ser de familias distintas.
GROQ_MODELO_REDACTOR = os.environ.get("GROQ_MODELO_REDACTOR", "qwen/qwen3.8-27b")
GROQ_MODELO_ESTRATEGA = os.environ.get("GROQ_MODELO_ESTRATEGA", GROQ_MODELO_REDACTOR)
GROQ_MODELO_REVISOR_A = os.environ.get("GROQ_MODELO_REVISOR_A", "openai/gpt-oss-120b")
GROQ_MODELO_REVISOR_B = os.environ.get("GROQ_MODELO_REVISOR_B", "openai/gpt-oss-20b")

# Límites del plan gratuito de Groq por modelo (tokens y peticiones por minuto). Ajustar si cambia el plan.
GROQ_TPM = int(os.environ.get("GROQ_TPM", "8000"))
GROQ_RPM = int(os.environ.get("GROQ_RPM", "30"))

# Tope por llamada al LLM, en segundos.
LLM_TIMEOUT_SEG = float(os.environ.get("LLM_TIMEOUT_SEG", "30"))

# Máximo de segundos que una llamada espera cupo de tokens antes de fallar con "sin_cupo".
LLM_ESPERA_MAX_SEG = float(os.environ.get("LLM_ESPERA_MAX_SEG", "90"))

# Tokens de salida que se piden por defecto (y que se reservan en el límite por minuto).
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1500"))

# Segundos que un modelo queda bloqueado tras un 429.
LLM_BLOQUEO_429_SEG = float(os.environ.get("LLM_BLOQUEO_429_SEG", "20"))