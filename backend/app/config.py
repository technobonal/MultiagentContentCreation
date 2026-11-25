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

# PDF con texto (tanda de fuentes en PDF): páginas máximas y texto mínimo por página. Por debajo del mínimo el
# PDF se considera escaneado y se rechaza (el OCR todavía no está conectado). El tope de tamaño del texto
# extraído es FUENTE_MAX_BYTES, igual que para .md y .txt.
PDF_MAX_BYTES = int(os.environ.get("PDF_MAX_BYTES", str(10 * 1024 * 1024)))  # peso del ARCHIVO (un PDF pesa mucho más que su texto)
PDF_MAX_PAGINAS = int(os.environ.get("PDF_MAX_PAGINAS", "40"))
PDF_MIN_CARACTERES_POR_PAGINA = int(os.environ.get("PDF_MIN_CARACTERES_POR_PAGINA", "80"))

# OCR de PDF escaneados (rapidocr, local, sin red). Solo se usa cuando el PDF no trae capa de texto; con PDF_OCR=0 un
# PDF escaneado se rechaza como antes (`pdf_sin_texto`). Tarda unos 3 s por página, por eso el tope de páginas.
PDF_OCR_MAX_PAGINAS = int(os.environ.get("PDF_OCR_MAX_PAGINAS", "20"))
PDF_OCR_LADO_MAX_PX = int(os.environ.get("PDF_OCR_LADO_MAX_PX", "2000"))  # lado mayor de la imagen que se lee

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

# Segundos que un modelo queda bloqueado tras un 429 cuando el mensaje de Groq NO trae la pista de espera
# («try again in Xs»). Si la trae, se usa esa pista (ver LLM_COLCHON_429_SEG y LLM_BLOQUEO_429_MAX_SEG).
LLM_BLOQUEO_429_SEG = float(os.environ.get("LLM_BLOQUEO_429_SEG", "20"))

# --- Tanda 1 de velocidad: espera exacta tras un 429 ---
# Medido en el run run_db6c83fe: qwen tiene un límite de tokens de SALIDA por minuto (OTPM = 1000) que no aparece
# en la consola de Groq pero sí en el mensaje del 429. Groq dice cuánto esperar y el cliente lo respeta.

# Segundos que se suman a la pista de Groq para no volver a chocar justo en el borde de la ventana.
LLM_COLCHON_429_SEG = float(os.environ.get("LLM_COLCHON_429_SEG", "0.5"))

# Tope, en segundos, del bloqueo de un modelo tras un 429 con pista (una pista absurda no lo deja fuera del run).
LLM_BLOQUEO_429_MAX_SEG = float(os.environ.get("LLM_BLOQUEO_429_MAX_SEG", "60"))

# --- Tanda 10B: menos espera por cupo (medido en la tanda 10A) ---

def _mapa_de_enteros(texto: str) -> dict[str, int]:
    """Convierte «modelo=valor,modelo=valor» en un diccionario; vacío si no hay nada.

    Un par mal escrito falla al arrancar (error visible, no silencioso).
    """
    mapa: dict[str, int] = {}
    # Cada par separado por coma aporta un modelo y su valor.
    for par in texto.split(","):
        if not par.strip():  # descarta entradas vacías (por ejemplo, una coma final)
            continue
        modelo, _, valor = par.partition("=")
        mapa[modelo.strip()] = int(valor)  # int() falla si falta el "=" o el valor no es un número
    return mapa


# Tokens por minuto de cada modelo cuando difieren de GROQ_TPM, por ejemplo
# GROQ_TPM_POR_MODELO="qwen/qwen3.8-27b=6000,openai/gpt-oss-20b=8000". Sin valor, todos usan GROQ_TPM.
# Los números reales de tu cuenta están en la consola de Groq (sección de límites).
GROQ_TPM_POR_MODELO = _mapa_de_enteros(os.environ.get("GROQ_TPM_POR_MODELO", ""))

# Tokens de salida que se piden (y se reservan en el límite por minuto) en cada llamada del revisor de
# fidelidad. Medido en la 10A: una llamada gasta entre 1.200 y 1.750 tokens en total, entrada incluida.
LLM_MAX_TOKENS_REVISOR = int(os.environ.get("LLM_MAX_TOKENS_REVISOR", "2000"))

# Cuántos slides revisa el revisor de fidelidad en UNA llamada (tanda 2 de velocidad, 2026-11-25). El prompt fijo
# pesa ~813 tokens de los ~1.100 de entrada de cada llamada y Groq no devolvió tokens cacheados, así que revisar
# 3 slides por llamada ahorra ~1.600 tokens por pasada. 1 = una llamada por slide (comportamiento anterior).
LLM_REVISOR_SLIDES_POR_LLAMADA = int(os.environ.get("LLM_REVISOR_SLIDES_POR_LLAMADA", "3"))
if LLM_REVISOR_SLIDES_POR_LLAMADA < 1:  # sin slides por llamada no hay revisión posible
    raise ValueError(f"LLM_REVISOR_SLIDES_POR_LLAMADA debe ser 1 o más; llegó {LLM_REVISOR_SLIDES_POR_LLAMADA}")

# Cadena de modelos del revisor, separados por coma (el primero es el que se pide). Ambos son gpt-oss, distintos
# de la familia del redactor (qwen), así el revisor sigue siendo independiente y gana una segunda ventana de tokens.
GROQ_FALLBACK_REVISOR = [
    m.strip()
    for m in os.environ.get("GROQ_FALLBACK_REVISOR", f"{GROQ_MODELO_REVISOR_A},{GROQ_MODELO_REVISOR_B}").split(",")
    if m.strip()  # descarta entradas vacías
]

# --- Tanda 8F: tope global por ejecución real ---

# Máximo de segundos que puede durar UN run real completo (de run_iniciada a run_finalizada).
# Al vencer, el run se corta con un run_error visible y libera su cupo de MAX_RUNS_ACTIVOS.
# Debe dar margen a varias llamadas al LLM con espera de cupo (ver LLM_ESPERA_MAX_SEG). 0 o menos = sin tope.
RUN_TIMEOUT_SEG = float(os.environ.get("RUN_TIMEOUT_SEG", "600"))

# --- Tanda 2A: cadenas por rol, reserva realista y respaldo solo por falla ---
# Medido en el run run_348cc81c: el redactor saltaba a gpt-oss sin falla técnica (qwen sin cupo por una reserva
# inflada), gastaba 2 o 3 veces más tokens y dejaba sin ventana al revisor. Estas variables lo corrigen.


def _lista_de_texto(texto: str) -> list[str]:
    """Convierte «a,b,c» en una lista de textos sin espacios y sin entradas vacías."""
    # Cada entrada separada por coma se limpia; las vacías (por ejemplo, una coma final) se descartan.
    return [parte.strip() for parte in texto.split(",") if parte.strip()]


# Modelo de respaldo del estratega y el redactor (solo se usa si qwen falla por motivos técnicos).
GROQ_MODELO_RESPALDO = os.environ.get("GROQ_MODELO_RESPALDO", "openai/gpt-oss-20b")

# Cadena de cada rol: el primero es el que se pide y los siguientes son el respaldo, en orden.
# Por defecto el 120b queda libre para el revisor (el respaldo es solo el 20b).
GROQ_FALLBACK_ESTRATEGA = _lista_de_texto(
    os.environ.get("GROQ_FALLBACK_ESTRATEGA", f"{GROQ_MODELO_ESTRATEGA},{GROQ_MODELO_RESPALDO}")
)
# Último recurso del redactor (y del corrector): el modelo principal del revisor. Solo entra si qwen y el 20b no tienen
# cupo (run_d95dcd67: 45 s de espera con ambos llenos). Rompe la independencia con el revisor solo en ese caso, y el log
# lo marca con fallback=True. Para quitarlo: GROQ_FALLBACK_REDACTOR="qwen/qwen3.8-27b,openai/gpt-oss-20b".
GROQ_MODELO_RESPALDO_FINAL = os.environ.get("GROQ_MODELO_RESPALDO_FINAL", GROQ_MODELO_REVISOR_A)
GROQ_FALLBACK_REDACTOR = _lista_de_texto(
    os.environ.get(
        "GROQ_FALLBACK_REDACTOR",
        f"{GROQ_MODELO_REDACTOR},{GROQ_MODELO_RESPALDO},{GROQ_MODELO_RESPALDO_FINAL}",
    )
)

# Roles cuyo respaldo entra SOLO ante una falla técnica (429, 413, 5xx, timeout, conexión) y no por falta de cupo:
# si su modelo principal está lleno, esperan unos segundos en vez de gastar la ventana de otro rol.
ROLES_RESPALDO_SOLO_POR_FALLA = tuple(
    _lista_de_texto(os.environ.get("ROLES_RESPALDO_SOLO_POR_FALLA", "estratega,redactor"))
)

# Si el modelo principal de uno de esos roles tendría que esperar MÁS de estos segundos, deja de esperar y se
# permite el salto por cupo al respaldo (evita que un run falle con «sin_cupo» o se quede dormido un minuto).
# Desde la tanda 1 de velocidad también decide si un 429 de qwen se espera (pista de Groq dentro de este tope)
# o salta al respaldo. Con qwen limitado a 1000 tokens de salida por minuto conviene 40 en el .env
# (LLM_ESPERA_ANTES_DE_SALTAR_SEG=40): esperar unos segundos sale más barato que ensuciar la ventana del revisor.
LLM_ESPERA_ANTES_DE_SALTAR_SEG = float(os.environ.get("LLM_ESPERA_ANTES_DE_SALTAR_SEG", "20"))

# Tokens de SALIDA que el limitador reserva por rol (se suman a la entrada estimada). Antes se reservaba el
# `max_tokens` completo (1500 a 2000) aunque el gasto real era de 1.050 tokens (redactor) y 1.200 a 1.750
# (revisor), entrada incluida. Esto es solo la reserva: el tope que se envía a Groq sigue siendo `max_tokens`.
# Si Groq empieza a responder 429 con frecuencia, sube estos valores; los reales salen de `tokens=` en el log.
# Formato de la variable de entorno (pisa solo los roles que nombres): "redactor=700,revisor_a=1100".
# Desde la tanda 2 de velocidad esto es solo el valor de ARRANQUE: con LLM_CALIBRAR_RESERVA activo, cuando el
# cliente ya tiene muestras reales de un rol, usa lo que ese rol gastó de verdad (ver abajo).
LLM_RESERVA_SALIDA_POR_ROL = {
    **_mapa_de_enteros("estratega=700,redactor=600,revisor_a=1000,revisor_b=1000"),
    **_mapa_de_enteros(os.environ.get("LLM_RESERVA_SALIDA_POR_ROL", "")),
}

# Fracción del límite por minuto de Groq que el limitador considera utilizable (0.8 = deja un 20 % de colchón).
# Probar 0.9 solo después de comprobar los límites reales de cada modelo en la consola de Groq.
GROQ_MARGEN = float(os.environ.get("GROQ_MARGEN", "0.8"))
if not 0 < GROQ_MARGEN <= 1:  # fuera de rango: no se arranca con un margen sin sentido
    raise ValueError(f"GROQ_MARGEN debe estar entre 0 (excluido) y 1; llegó {GROQ_MARGEN}")

# Nivel de razonamiento de los modelos gpt-oss (low, medium o high; vacío = no se envía). En «low» el modelo
# gasta pocos tokens pensando y no se come la salida: el redactor sobre gpt-oss-120b se cortó con finish=length.
NIVEL_RAZONAMIENTO_GPT_OSS = os.environ.get("NIVEL_RAZONAMIENTO_GPT_OSS", "low").strip().lower()
if NIVEL_RAZONAMIENTO_GPT_OSS not in ("", "low", "medium", "high"):  # valor desconocido: falla al arrancar
    raise ValueError(f"NIVEL_RAZONAMIENTO_GPT_OSS debe ser low, medium, high o vacío; llegó {NIVEL_RAZONAMIENTO_GPT_OSS!r}")

# Parámetros fijos por modelo que el cliente añade a cada petición (el llamador puede pisarlos con `extra`).
# Hoy solo el razonamiento de los dos gpt-oss; qwen no recibe nada.
GROQ_EXTRA_POR_MODELO = (
    {
        modelo: {"reasoning_effort": NIVEL_RAZONAMIENTO_GPT_OSS}
        for modelo in dict.fromkeys((GROQ_MODELO_REVISOR_A, GROQ_MODELO_REVISOR_B, GROQ_MODELO_RESPALDO))
    }
    if NIVEL_RAZONAMIENTO_GPT_OSS
    else {}
)

# --- Tanda 2 de velocidad: reserva calibrada con el gasto real ---
# Medido en el run run_4e47da95 (85 s, 64 s de espera por cupo, 53,7 s en una sola llamada del revisor): la reserva
# del limitador era la entrada estimada con «1 token por cada 3 caracteres» más una salida fija por rol, bastante
# por encima del gasto real (~1.300 tokens por llamada del revisor). Con el 20b ya cargado por respaldos del
# redactor, esa reserva inflada no cabía en la ventana y la llamada dormía casi un minuto. Ahora el cliente aprende,
# por rol, cuántos caracteres caben en un token y cuántos tokens de salida se gastan de verdad.

def _booleano(texto: str, defecto: bool) -> bool:
    """Interpreta «1/0», «true/false», «si/no», «on/off»; vacío = el valor por defecto. Un valor raro falla al arrancar."""
    limpio = texto.strip().lower()
    if not limpio:  # variable ausente o vacía: se queda con el valor por defecto
        return defecto
    if limpio in ("1", "true", "si", "sí", "on", "yes"):
        return True
    if limpio in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Valor booleano no reconocido: {texto!r} (usa 1/0, true/false, si/no, on/off)")


# Interruptor: 1 = reserva calibrada (por defecto); 0 = vuelve a la fórmula de siempre (chars // 3 + salida fija).
LLM_CALIBRAR_RESERVA = _booleano(os.environ.get("LLM_CALIBRAR_RESERVA", ""), True)

# Cuántas respuestas recientes de un rol se recuerdan para calibrar (ventana deslizante por rol).
LLM_CALIBRACION_MUESTRAS = int(os.environ.get("LLM_CALIBRACION_MUESTRAS", "5"))

# Cuántas respuestas reales hacen falta antes de fiarse de la calibración; con menos se usa la fórmula de siempre.
LLM_CALIBRACION_MIN_MUESTRAS = int(os.environ.get("LLM_CALIBRACION_MIN_MUESTRAS", "2"))

# Factor de seguridad sobre lo medido (1.15 = 15 % de colchón). Debe ser 1 o más.
LLM_CALIBRACION_COLCHON = float(os.environ.get("LLM_CALIBRACION_COLCHON", "1.15"))
if LLM_CALIBRACION_MUESTRAS < 1 or LLM_CALIBRACION_MIN_MUESTRAS < 1:  # sin muestras no hay calibración posible
    raise ValueError("LLM_CALIBRACION_MUESTRAS y LLM_CALIBRACION_MIN_MUESTRAS deben ser 1 o más")
if LLM_CALIBRACION_COLCHON < 1:  # un colchón menor que 1 reservaría MENOS de lo medido
    raise ValueError(f"LLM_CALIBRACION_COLCHON debe ser 1 o más; llegó {LLM_CALIBRACION_COLCHON}")

# Aprobación humana (HITL). Con APROBACION_HUMANA activa, tras `aprobacion_solicitada` el run espera la decisión de una
# persona (POST /api/runs/{id}/aprobacion) antes de emitir `run_finalizada`. Arranca ENCENDIDA (el lienzo ya tiene el panel);
# APROBACION_HUMANA=0 la apaga para scripts sin pantalla, donde cada run esperaría y ocuparía un cupo de MAX_RUNS_ACTIVOS.
APROBACION_HUMANA = _booleano(os.environ.get("APROBACION_HUMANA", ""), True)

# Segundos que el run espera esa decisión (el tope RUN_TIMEOUT_SEG solo cubre el trabajo de los agentes, no esta espera).
# Si vence, el run termina con estado `requiere_humano` y libera su cupo. 0 o menos = espera sin límite.
APROBACION_TIMEOUT_SEG = float(os.environ.get("APROBACION_TIMEOUT_SEG", "900"))

# OCR de PDF escaneados: ver PDF_OCR_MAX_PAGINAS arriba. Arranca encendido; PDF_OCR=0 vuelve a rechazarlos con `pdf_sin_texto`.
PDF_OCR = _booleano(os.environ.get("PDF_OCR", ""), True)

# Visión (describir imágenes) por OpenRouter, solo con modelos gratis. La key va en el .env (`OPENROUTER_API_KEY`) y nunca
# se imprime. Los modelos se prueban en orden: salta al siguiente ante 429, 5xx, timeout o respuesta vacía. Los gratis de
# OpenRouter se limitan seguido y pueden usar lo que se les envía para entrenar: no mandarles fuentes privadas.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODELOS_VISION = tuple(
    m.strip() for m in os.environ.get(
        "OPENROUTER_MODELOS_VISION",
        "nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free,inclusionai/ling-3.2-flash:free",
    ).split(",") if m.strip()
)
OPENROUTER_TIMEOUT_SEG = float(os.environ.get("OPENROUTER_TIMEOUT_SEG", "60"))
