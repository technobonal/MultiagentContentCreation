"""Cargador de la fuente: lee un archivo de la carpeta del servidor, lo normaliza,
calcula su sha256 y lo parte en fragmentos con su posición exacta.

Reglas que importan al resto del sistema:
- El texto normalizado (saltos de línea a "\\n", sin BOM) es la ÚNICA referencia: el sha256
  y las posiciones `inicio`/`fin` de cada fragmento se calculan sobre él, y se cumple
  siempre `texto[f.inicio:f.fin] == f.texto`. Así la `cita` del revisor puede apuntar a
  un rango exacto.
- Solo se aceptan `.md` y `.txt`. El PDF (escaneado o no) se rechaza con un error claro.
- La `referencia` es solo un nombre de archivo: nada de rutas, para no salirse de la carpeta.
- Todo problema se informa con `FuenteError`, que el endpoint convierte en un 422.
"""

import codecs
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app import config

# Extensiones aceptadas (en minúsculas).
EXTENSIONES_OK = (".md", ".txt")

# Separador entre bloques: una o más líneas en blanco (se admiten espacios en ellas).
_SEPARADOR_BLOQUES = re.compile(r"\n[ \t]*\n\s*")

# Final de frase: signo de cierre, comilla o paréntesis opcional, y un espacio en blanco.
_FIN_FRASE = re.compile(r"[.!?…][\"')\]»”]?\s")


class FuenteError(Exception):
    """Fallo al cargar la fuente. `codigo` es estable (para pruebas y mensajes); `mensaje` va al usuario."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True)
class Fragmento:
    """Trozo de la fuente. `inicio` y `fin` son posiciones sobre el texto normalizado (fin exclusivo)."""

    indice: int
    inicio: int
    fin: int
    texto: str


@dataclass(frozen=True)
class FuenteCargada:
    """Resultado de cargar una fuente: texto normalizado, huella y fragmentos."""

    referencia: str
    texto: str
    sha256: str
    caracteres: int
    fragmentos: tuple[Fragmento, ...]


def _validar_referencia(referencia: str) -> str:
    """Devuelve el nombre de archivo limpio o lanza FuenteError si no es un nombre simple."""
    nombre = (referencia or "").strip()
    # Vacía: no hay nada que buscar.
    if not nombre:
        raise FuenteError("referencia_invalida", "La referencia de la fuente está vacía.")
    # Separadores, unidad de disco (o flujo alterno de NTFS), "." / ".." y NUL no son un nombre simple.
    if nombre in (".", "..") or "\x00" in nombre or any(c in nombre for c in "/\\:"):
        raise FuenteError(
            "referencia_invalida",
            "La referencia debe ser solo el nombre del archivo (sin carpetas ni rutas).",
        )
    return nombre


def _validar_extension(nombre: str) -> None:
    """Acepta solo .md y .txt; da un mensaje específico para PDF."""
    sufijo = Path(nombre).suffix.lower()
    # PDF: por ahora no se lee (escaneado o con texto); se explica el camino.
    if sufijo == ".pdf":
        raise FuenteError(
            "pdf_no_soportado",
            "Los PDF no se cargan directamente. Conviértelo antes a .md o .txt "
            "(si es un PDF escaneado, con el script de OCR) y revisa el texto.",
        )
    # Cualquier otra extensión fuera de la lista.
    if sufijo not in EXTENSIONES_OK:
        raise FuenteError(
            "extension_no_soportada",
            f"Extensión no soportada ({sufijo or 'sin extensión'}). Solo se aceptan .md y .txt.",
        )


def _decodificar(datos: bytes) -> str:
    """Convierte bytes a texto: UTF-16 si trae BOM (lo que genera PowerShell), si no UTF-8 (con o sin BOM)."""
    try:
        # UTF-16 con BOM: el códec "utf-16" lo detecta y lo quita.
        if datos.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            texto = datos.decode("utf-16")
        else:
            texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FuenteError(
            "codificacion_invalida",
            "El archivo no está en UTF-8 (ni UTF-16 con BOM). Guárdalo como UTF-8.",
        ) from exc
    # Un NUL indica un archivo binario renombrado como .txt.
    if "\x00" in texto:
        raise FuenteError("codificacion_invalida", "El archivo parece binario, no texto.")
    return texto


def _normalizar(texto: str) -> str:
    """Unifica los saltos de línea a "\\n". No toca nada más: las posiciones se miden sobre este texto."""
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def _bloques(texto: str) -> list[tuple[int, int]]:
    """Posiciones (inicio, fin) de cada bloque de texto separado por líneas en blanco, sin espacios en los bordes."""
    bloques: list[tuple[int, int]] = []

    def agregar(a: int, b: int) -> None:
        """Recorta los blancos de los bordes del tramo [a, b) y lo guarda si queda algo."""
        trozo = texto[a:b]
        # Tramo vacío o solo blancos: se ignora.
        if not trozo.strip():
            return
        a += len(trozo) - len(trozo.lstrip())
        b -= len(trozo) - len(trozo.rstrip())
        bloques.append((a, b))

    pos = 0
    # Cada separador cierra el bloque anterior.
    for sep in _SEPARADOR_BLOQUES.finditer(texto):
        agregar(pos, sep.start())
        pos = sep.end()
    agregar(pos, len(texto))  # último bloque
    return bloques


def _partir_bloque(texto: str, ini: int, fin: int, maximo: int) -> list[tuple[int, int]]:
    """Parte un bloque más largo que `maximo` en trozos <= `maximo`.

    Prefiere cortar al final de una frase, luego en un espacio o salto de línea, y solo
    como último recurso corta en seco. No admite trozos menores a la mitad del máximo
    salvo el último.
    """
    partes: list[tuple[int, int]] = []
    # Mientras lo que queda no quepa en un trozo, se saca uno del principio.
    while fin - ini > maximo:
        ventana = texto[ini:ini + maximo + 1]  # +1 para ver el blanco que sigue al límite
        fin_pieza = None
        siguiente = None

        # 1) Final de frase: el último que deje un trozo de al menos la mitad del máximo.
        for m in _FIN_FRASE.finditer(ventana):
            if m.end() - 1 > maximo // 2:
                fin_pieza, siguiente = ini + m.end() - 1, ini + m.end()

        # 2) Sin frase útil: último blanco (salto de línea o espacio) en la misma condición.
        if fin_pieza is None:
            idx = max(ventana.rfind("\n"), ventana.rfind(" "))
            if idx > maximo // 2:
                fin_pieza, siguiente = ini + idx, ini + idx + 1

        # 3) Último recurso: corte en seco en el límite.
        if fin_pieza is None:
            fin_pieza, siguiente = ini + maximo, ini + maximo

        # Un corte en seco puede dejar blancos al final del trozo: se recortan.
        while fin_pieza > ini and texto[fin_pieza - 1].isspace():
            fin_pieza -= 1
        partes.append((ini, fin_pieza))

        ini = siguiente
        # El siguiente trozo empieza en el primer carácter que no sea blanco.
        while ini < fin and texto[ini].isspace():
            ini += 1

    # Resto final, si queda algo.
    if ini < fin:
        partes.append((ini, fin))
    return partes


def fragmentar(texto: str, max_chars: int | None = None) -> tuple[Fragmento, ...]:
    """Parte el texto en fragmentos de hasta `max_chars` caracteres, cortando en límites de párrafo.

    Une bloques consecutivos mientras quepan; un bloque más largo que el máximo se parte
    por frases. Cada fragmento es una porción exacta del texto: `texto[inicio:fin]`.
    """
    maximo = max_chars if max_chars is not None else config.FRAGMENTO_MAX_CHARS
    # Un máximo menor que 1 no tiene sentido.
    if maximo < 1:
        raise ValueError("max_chars debe ser al menos 1")

    # Se arma la lista de piezas: cada bloque, partido si es demasiado largo.
    piezas: list[tuple[int, int]] = []
    for a, b in _bloques(texto):
        if b - a > maximo:
            piezas.extend(_partir_bloque(texto, a, b, maximo))
        else:
            piezas.append((a, b))

    fragmentos: list[Fragmento] = []
    grupo_ini = grupo_fin = None
    # Se agrupan piezas consecutivas mientras el grupo no pase del máximo.
    for a, b in piezas:
        if grupo_ini is None:
            grupo_ini, grupo_fin = a, b  # primera pieza
        elif b - grupo_ini <= maximo:
            grupo_fin = b  # cabe: se une (incluye el hueco entre ambas)
        else:
            fragmentos.append(Fragmento(len(fragmentos), grupo_ini, grupo_fin, texto[grupo_ini:grupo_fin]))
            grupo_ini, grupo_fin = a, b
    # Se cierra el último grupo.
    if grupo_ini is not None:
        fragmentos.append(Fragmento(len(fragmentos), grupo_ini, grupo_fin, texto[grupo_ini:grupo_fin]))
    return tuple(fragmentos)


def cargar_fuente(
    referencia: str,
    carpeta: Path | None = None,
    max_bytes: int | None = None,
    max_chars: int | None = None,
) -> FuenteCargada:
    """Carga `referencia` (nombre de archivo) desde la carpeta de fuentes y la deja indexada.

    Lanza FuenteError ante cualquier problema (referencia, extensión, archivo, tamaño,
    codificación o contenido vacío). Los parámetros opcionales existen para las pruebas.
    """
    carpeta = Path(carpeta) if carpeta is not None else config.FUENTES_DIR
    limite = max_bytes if max_bytes is not None else config.FUENTE_MAX_BYTES

    nombre = _validar_referencia(referencia)
    _validar_extension(nombre)

    ruta = carpeta / nombre
    # Un enlace simbólico podría apuntar fuera de la carpeta: se compara la ruta real.
    if ruta.resolve().parent != carpeta.resolve():
        # Si ni siquiera existe, es un "no encontrada" normal; si existe, es un intento de salir.
        if ruta.exists() or ruta.is_symlink():
            raise FuenteError("referencia_invalida", "La referencia apunta fuera de la carpeta de fuentes.")
    # Debe ser un archivo regular que exista.
    if not ruta.is_file():
        raise FuenteError("no_encontrada", f"No existe la fuente «{nombre}» en la carpeta del servidor.")

    # Se comprueba el tamaño antes de leer.
    tam = ruta.stat().st_size
    if tam > limite:
        raise FuenteError(
            "demasiado_grande",
            f"La fuente pesa {tam} bytes y el máximo es {limite}.",
        )

    try:
        datos = ruta.read_bytes()
    except OSError as exc:
        raise FuenteError("no_legible", f"No se pudo leer la fuente «{nombre}».") from exc

    texto = _normalizar(_decodificar(datos))
    # Sin contenido útil, no hay nada que redactar.
    if not texto.strip():
        raise FuenteError("vacia", f"La fuente «{nombre}» está vacía.")

    return FuenteCargada(
        referencia=nombre,
        texto=texto,
        sha256=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        caracteres=len(texto),
        fragmentos=fragmentar(texto, max_chars),
    )