"""Cargador de la fuente: lee un archivo de la carpeta del servidor, lo normaliza,
calcula su sha256 y lo parte en fragmentos con su posición exacta.

Reglas que importan al resto del sistema:
- El texto normalizado (saltos de línea a "\\n", sin BOM) es la ÚNICA referencia: el sha256
  y las posiciones `inicio`/`fin` de cada fragmento se calculan sobre él, y se cumple
  siempre `texto[f.inicio:f.fin] == f.texto`. Así la `cita` del revisor puede apuntar a
  un rango exacto.
- Se aceptan `.md`, `.txt` y `.pdf` con texto. El PDF se convierte a texto plano (un párrafo por bloque,
  separados por una línea en blanco) y desde ahí es igual que cualquier otra fuente: el texto extraído es
  la referencia de las citas. El PDF escaneado (sin texto) se rechaza con un error claro.
- La `referencia` es solo un nombre de archivo: nada de rutas, para no salirse de la carpeta.
- Todo problema se informa con `FuenteError`, que el endpoint convierte en un 422.
"""

import codecs
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.fuentes.ocr_pdf import Motor, ocr_de_paginas

# Extensiones aceptadas (en minúsculas).
EXTENSIONES_OK = (".md", ".txt", ".pdf")

# Guion de fin de línea entre dos letras (la segunda en minúscula): palabra cortada por el ajuste de línea del PDF.
_GUION_DE_CORTE = re.compile(r"(\w)-\n(?=[a-záéíóúüñ])")

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
    """Acepta solo .md, .txt y .pdf."""
    sufijo = Path(nombre).suffix.lower()
    if sufijo not in EXTENSIONES_OK:
        raise FuenteError(
            "extension_no_soportada",
            f"Extensión no soportada ({sufijo or 'sin extensión'}). Solo se aceptan .md, .txt y .pdf.",
        )


# Un encabezado o pie se repite casi igual en muchas páginas, solo cambia el número de página.
_DIGITOS = re.compile(r"\d+")
_BLOQUES_DE_BORDE = 2  # cuántos bloques del inicio y del final de cada página se miran
_MIN_PAGINAS_PARA_LIMPIAR = 4  # con menos páginas no hay forma fiable de saber qué se repite


def quitar_encabezados_y_pies(paginas: list[list[str]]) -> list[list[str]]:
    """Quita los bloques de borde que se repiten en la mayoría de las páginas (encabezados, pies, números de página).

    Un bloque cuenta como repetido si, con los dígitos reemplazados, aparece en el borde de al menos la mitad de las
    páginas (y no menos de 3). Un número de página suelto en el borde también se quita. El texto del medio de la
    página nunca se toca, y con menos de 4 páginas no se limpia nada.
    """
    if len(paginas) < _MIN_PAGINAS_PARA_LIMPIAR:
        return paginas

    def clave(texto: str) -> str:
        return _DIGITOS.sub("#", texto)

    def indices_de_borde(n: int) -> set[int]:
        return set(range(min(_BLOQUES_DE_BORDE, n))) | set(range(max(0, n - _BLOQUES_DE_BORDE), n))

    paginas_por_clave: dict[str, set[int]] = {}
    for i, bloques in enumerate(paginas):
        for j in indices_de_borde(len(bloques)):
            paginas_por_clave.setdefault(clave(bloques[j]), set()).add(i)
    minimo = max(3, (len(paginas) + 1) // 2)
    repetidas = {k for k, donde in paginas_por_clave.items() if len(donde) >= minimo}

    limpias: list[list[str]] = []
    for bloques in paginas:
        borde = indices_de_borde(len(bloques))
        limpias.append([
            b for j, b in enumerate(bloques)
            if not (j in borde and (clave(b) in repetidas or re.fullmatch(r"\d{1,4}", b)))
        ])
    return limpias


def _texto_de_pdf(datos: bytes, nombre: str, motor_ocr: Motor | None = None) -> str:
    """Extrae el texto de un PDF con texto: un párrafo por bloque, separados por una línea en blanco.

    Lanza FuenteError si el archivo no es un PDF legible, está protegido, tiene demasiadas páginas
    o no trae texto (PDF escaneado: el OCR todavía no está conectado).
    """
    try:
        # PyMuPDF; se importa aquí para que el resto del módulo no dependa de él. `fitz` es el nombre antiguo.
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise FuenteError("pdf_no_disponible", "El servidor no tiene instalado el lector de PDF (pymupdf).") from exc

    try:
        doc = fitz.open(stream=datos, filetype="pdf")
    except Exception as exc:  # PyMuPDF lanza varios tipos según el daño del archivo
        raise FuenteError("pdf_invalido", f"«{nombre}» no es un PDF válido o está dañado.") from exc

    with doc:
        if doc.needs_pass:
            raise FuenteError("pdf_protegido", f"«{nombre}» está protegido con contraseña.")
        if doc.page_count > config.PDF_MAX_PAGINAS:
            raise FuenteError(
                "pdf_demasiadas_paginas",
                f"El PDF tiene {doc.page_count} páginas y el máximo es {config.PDF_MAX_PAGINAS}.",
            )
        por_pagina: list[list[str]] = []
        for pagina in doc:
            parrafos: list[str] = []
            por_pagina.append(parrafos)
            # sort=True ordena los bloques en el orden de lectura; el tipo 0 es texto (el 1 es imagen).
            for bloque in pagina.get_text("blocks", sort=True):
                if bloque[6] != 0:
                    continue
                texto = bloque[4].replace("\xad", "")  # guion blando
                texto = _GUION_DE_CORTE.sub(r"\1", texto)  # «organi-\nzado» -> «organizado»
                texto = " ".join(texto.split())  # el salto de línea dentro de un párrafo es solo ajuste
                if texto:
                    parrafos.append(texto)
        paginas = doc.page_count

        def armar(bloques_por_pagina: list[list[str]]) -> str:
            return "\n\n".join(b for pagina in quitar_encabezados_y_pies(bloques_por_pagina) for b in pagina)

        def basta(texto: str) -> bool:
            return len(texto) >= config.PDF_MIN_CARACTERES_POR_PAGINA * max(1, paginas)

        texto = armar(por_pagina)
        # Un PDF escaneado casi no trae capa de texto: se lee con OCR (si está encendido y cabe en el tope de páginas).
        if not basta(texto) and config.PDF_OCR:
            if paginas > config.PDF_OCR_MAX_PAGINAS:
                raise FuenteError(
                    "pdf_demasiadas_paginas_ocr",
                    f"«{nombre}» es un PDF escaneado de {paginas} páginas y el OCR lee como mucho {config.PDF_OCR_MAX_PAGINAS}.",
                )
            try:
                texto = armar(ocr_de_paginas(doc, motor_ocr))
            except ImportError as exc:  # pragma: no cover - depende del entorno
                raise FuenteError("ocr_no_disponible", "El servidor no tiene instalado el OCR (rapidocr).") from exc
            ocr_usado = True
        else:
            ocr_usado = False

    if not basta(texto):
        detalle = "El OCR no encontró texto legible." if ocr_usado else "El OCR está apagado (PDF_OCR=0)."
        raise FuenteError(
            "pdf_sin_texto",
            f"«{nombre}» casi no tiene texto (¿PDF escaneado?). {detalle} "
            "Convierte el PDF a .md o .txt y revisa el texto.",
        )
    return texto


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

    # Se comprueba el tamaño antes de leer. Un PDF pesa mucho más que su texto: su tope de archivo es propio
    # (el tope de `limite` se aplica después, al texto extraído).
    es_pdf = Path(nombre).suffix.lower() == ".pdf"
    limite_archivo = (max_bytes if max_bytes is not None else config.PDF_MAX_BYTES) if es_pdf else limite
    tam = ruta.stat().st_size
    if tam > limite_archivo:
        raise FuenteError(
            "demasiado_grande",
            f"La fuente pesa {tam} bytes y el máximo es {limite_archivo}.",
        )

    try:
        datos = ruta.read_bytes()
    except OSError as exc:
        raise FuenteError("no_legible", f"No se pudo leer la fuente «{nombre}».") from exc

    if es_pdf:
        texto = _normalizar(_texto_de_pdf(datos, nombre))
        # El tope de tamaño del texto es el mismo que para .md y .txt: lo que viaja a los agentes es el texto.
        if len(texto.encode("utf-8")) > limite:
            raise FuenteError(
                "demasiado_grande",
                f"El texto del PDF pesa {len(texto.encode('utf-8'))} bytes y el máximo es {limite}.",
            )
    else:
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