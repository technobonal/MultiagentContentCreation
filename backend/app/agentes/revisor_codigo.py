"""Revisor, parte determinista (rúbrica A.3): comprobaciones por código, sin LLM.

Cubre las dimensiones que se pueden decidir con reglas exactas:
- contraste:            relación WCAG entre los pares de colores del kit (mínimo AA 4,5:1).
- longitud:             campos obligatorios con texto y dentro de `longitud_max` de la ficha.
- estructura:           la ficha tiene gancho, desarrollo, cierre y fuentes, y cada slide su texto.
- atribucion_licencia:  hay atribución y licencia de la fuente para el slide de fuentes.

Cada incumplimiento es un `Hallazgo`, ya conforme al contrato `hallazgo_abierto`. El revisor
solo señala: la corrección la hacen el redactor, el director de arte o el estratega.

Este módulo también define `Hallazgo` y `con_ids`, que comparte con revisor_fidelidad.py.

Entrada:  la `Resolucion` (su `ficha` es el card.json), el kit de marca, los `TextoSlide` del
          redactor y la `entrada` del usuario (de ahí salen atribución y licencia).
Salida:   una lista de `Hallazgo` ordenada por gravedad y por slide.

Formas reales de la ficha (card.json): slides[] con `numero`, `rol` y `campos[]`; cada campo
tiene `nombre` (con llaves, como «{{titulo}}»), `obligatorio`, `origen_valor` y `longitud_max`.
Solo se revisan los campos con `origen_valor == "llm"` (los que escribe el redactor).
Los nombres se comparan sin llaves, así «{{titulo}}» y «titulo» son el mismo campo.
No se mide `lineas_max` ni el desborde real: eso lo mide el lienzo (dimensión diferida).

Se asume de `TextoSlide`: .slide (int) y .campos (nombre -> texto).
Se asume de la entrada: atribución y licencia en entrada["fuente"] (o en la raíz).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.agentes.comun import AgenteError

# TextoSlide solo se usa en anotaciones: así este módulo no depende de que redactor.py importe.
if TYPE_CHECKING:
    from app.agentes.redactor import TextoSlide

# Enumeraciones del contrato (common.schema.json y hallazgo_abierto.schema.json).
DIMENSIONES = frozenset({
    "fidelidad", "especificaciones_red", "atribucion_licencia", "claridad", "gancho",
    "gancho_slide2", "valor_guardable", "estructura", "contraste", "desbordes",
    "zona_segura", "idioma", "longitud", "marca", "variedad",
})
GRAVEDADES = ("bloqueante", "mayor", "menor")
RESPONSABLES = ("redactor", "director_arte", "estratega")

# Tope del contrato `texto` y del identificador de hallazgo (h1 a h999).
TEXTO_MAX = 400
MAX_HALLAZGOS = 999

# Mínimo de contraste WCAG AA para texto normal (A.3, dimensión 7).
UMBRAL_CONTRASTE_AA = 4.5

# Pares de roles de la paleta que el kit declara como texto sobre fondo.
PARES_CONTRASTE = (("texto", "fondo"), ("texto_sobre_acento", "acento"))

# Roles fijos de toda ficha; «desarrollo» es cualquier otro rol (p. ej. «paso» en un carrusel de pasos).
ROLES_FIJOS = ("gancho", "cierre", "fuentes")

_COLOR_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_ID_HALLAZGO = re.compile(r"h[0-9]{1,3}")

# Orden de presentación: lo más grave primero.
_ORDEN_GRAVEDAD = {g: i for i, g in enumerate(GRAVEDADES)}


def recortar_texto(texto: object, maximo: int = TEXTO_MAX) -> str:
    """Aplana el texto a una línea y lo recorta a `maximo` caracteres (con elipsis si se corta)."""
    plano = " ".join(str(texto).split())
    # Si ya cabe, se devuelve tal cual.
    if len(plano) <= maximo:
        return plano
    return plano[: maximo - 1].rstrip() + "…"


def leer_campo(origen: object, nombre: str, defecto: object = None) -> object:
    """Lee `nombre` de un dict (por clave) o de un objeto (por atributo); `defecto` si no existe."""
    # Los mapas se leen por clave y los dataclasses u objetos por atributo.
    if isinstance(origen, Mapping):
        return origen.get(nombre, defecto)
    return getattr(origen, nombre, defecto)


def nombre_campo(nombre: object) -> str:
    """Nombre de campo sin llaves ni espacios: «{{titulo}}» -> «titulo»."""
    return str(nombre).strip().strip("{}").strip()


@dataclass(frozen=True)
class Hallazgo:
    """Un problema detectado por el revisor, con motivo, evidencia, acción y responsable."""

    dimension: str
    gravedad: str
    slide: int
    evidencia: str
    explicacion: str
    accion: str
    responsable: str

    def __post_init__(self):
        """Rechaza al construirse cualquier valor que el contrato no admitiría."""
        # Las tres enumeraciones del contrato.
        if self.dimension not in DIMENSIONES:
            raise AgenteError("hallazgo_invalido", f"Dimensión desconocida: {self.dimension!r}.")
        if self.gravedad not in GRAVEDADES:
            raise AgenteError("hallazgo_invalido", f"Gravedad desconocida: {self.gravedad!r}.")
        if self.responsable not in RESPONSABLES:
            raise AgenteError("hallazgo_invalido", f"Responsable desconocido: {self.responsable!r}.")
        # El slide es un entero positivo (bool es subclase de int y no vale).
        if not isinstance(self.slide, int) or isinstance(self.slide, bool) or self.slide < 1:
            raise AgenteError("hallazgo_invalido", f"Slide inválido: {self.slide!r}.")
        # Los tres textos son cadenas no vacías y caben en el tope del contrato.
        for nombre in ("evidencia", "explicacion", "accion"):
            valor = getattr(self, nombre)
            if not isinstance(valor, str) or not valor.strip():
                raise AgenteError("hallazgo_invalido", f"El campo {nombre} no puede estar vacío.")
            if len(valor) > TEXTO_MAX:
                raise AgenteError("hallazgo_invalido", f"El campo {nombre} supera {TEXTO_MAX} caracteres.")


def crear_hallazgo(dimension: str, gravedad: str, slide: int, evidencia: object,
                   explicacion: object, accion: object, responsable: str) -> Hallazgo:
    """Construye un `Hallazgo` recortando los tres textos al tope del contrato."""
    return Hallazgo(dimension, gravedad, slide, recortar_texto(evidencia),
                    recortar_texto(explicacion), recortar_texto(accion), responsable)


def ordenar_hallazgos(hallazgos: Iterable[Hallazgo]) -> list[Hallazgo]:
    """Ordena por gravedad (bloqueante primero) y por slide; es estable con el resto."""
    return sorted(hallazgos, key=lambda h: (_ORDEN_GRAVEDAD[h.gravedad], h.slide))


def con_ids(hallazgos: Iterable[Hallazgo], primer_numero: int = 1) -> list[dict]:
    """Asigna ids h1, h2... y devuelve, por hallazgo, {"slide", "payload"} listo para `hallazgo_abierto`.

    El `slide` va fuera del payload (en el sobre del evento): el esquema del payload no lo admite.
    `primer_numero` permite seguir la numeración cuando ya hay hallazgos abiertos en la ejecución.
    """
    eventos = []
    # Cada hallazgo recibe el siguiente número, sin pasar del tope del contrato.
    for numero, h in enumerate(hallazgos, start=primer_numero):
        hallazgo_id = f"h{numero}"
        if numero > MAX_HALLAZGOS or not _ID_HALLAZGO.fullmatch(hallazgo_id):
            raise AgenteError("demasiados_hallazgos", f"No caben más de {MAX_HALLAZGOS} hallazgos por ejecución.")
        eventos.append({
            "slide": h.slide,
            "payload": {
                "hallazgo_id": hallazgo_id,
                "dimension": h.dimension,
                "gravedad": h.gravedad,
                "evidencia": h.evidencia,
                "explicacion": h.explicacion,
                "accion": h.accion,
                "responsable": h.responsable,
            },
        })
    return eventos


# ---------------------------------------------------------------- contraste (WCAG)

def _luminancia(color: str) -> float:
    """Luminancia relativa WCAG 2.x de un color "#RRGGBB"."""
    canales = []
    # Cada canal sRGB se pasa a lineal antes de ponderarlo.
    for inicio in (1, 3, 5):
        c = int(color[inicio:inicio + 2], 16) / 255
        canales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = canales
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def razon_contraste(color_a: str, color_b: str) -> float:
    """Relación de contraste WCAG entre dos colores "#RRGGBB" (de 1 a 21)."""
    # Se valida el formato antes de calcular: un color roto es un kit inválido, no un hallazgo.
    for color in (color_a, color_b):
        if not isinstance(color, str) or not _COLOR_HEX.fullmatch(color):
            raise AgenteError("kit_invalido", f"Color con formato inválido: {color!r}.")
    claro, oscuro = sorted((_luminancia(color_a), _luminancia(color_b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def _paleta_del_kit(kit: object) -> dict[str, str]:
    """Devuelve rol -> "#RRGGBB" a partir del bloque `paleta` del kit."""
    bloque = leer_campo(kit, "paleta")
    paleta = {}
    # Cada rol puede ser el hex directo o un objeto con su "hex".
    if isinstance(bloque, Mapping):
        for rol, valor in bloque.items():
            hexa = leer_campo(valor, "hex") if isinstance(valor, Mapping) else valor
            if isinstance(hexa, str):
                paleta[str(rol)] = hexa
    return paleta


def comprobar_contraste(kit: object) -> list[Hallazgo]:
    """Un hallazgo por cada par texto/fondo del kit que no llega a AA (4,5:1)."""
    paleta = _paleta_del_kit(kit)
    hallazgos = []
    evaluados = 0
    # Solo se evalúan los pares cuyos dos roles declara el kit.
    for rol_texto, rol_fondo in PARES_CONTRASTE:
        color_texto, color_fondo = paleta.get(rol_texto), paleta.get(rol_fondo)
        if color_texto is None or color_fondo is None:
            continue
        evaluados += 1
        razon = razon_contraste(color_texto, color_fondo)
        # Por debajo del mínimo AA se abre un hallazgo que corrige el director de arte.
        if razon < UMBRAL_CONTRASTE_AA:
            hallazgos.append(crear_hallazgo(
                "contraste", "bloqueante", 1,
                f"{rol_texto} {color_texto} sobre {rol_fondo} {color_fondo}: {razon:.2f}:1".replace(".", ","),
                "El contraste es menor que el mínimo WCAG AA de 4,5:1.",
                f"Cambia {rol_texto} o {rol_fondo} en el kit hasta llegar a 4,5:1.",
                "director_arte"))
    # Si el kit no declara ningún par, la comprobación no se hizo: es un fallo, no un visto bueno.
    if evaluados == 0:
        raise AgenteError("kit_invalido", "El kit no declara ningún par de colores texto/fondo para comprobar.")
    return hallazgos


# ---------------------------------------------------------------- ficha: estructura, longitud, fuentes

def _slides_ficha(resolucion: object) -> list:
    """Slides del card.json (la `ficha` de la Resolucion); vacía si no los trae."""
    # La Resolucion guarda el card.json en `.ficha`; también se acepta recibir la ficha directamente.
    ficha = leer_campo(resolucion, "ficha", resolucion)
    slides = leer_campo(ficha, "slides", ())
    return list(slides) if isinstance(slides, Sequence) and not isinstance(slides, str) else []


def _numero(slide_ficha: object) -> int:
    """Número del slide en la ficha (`numero`, o `slide` si la ficha usa ese nombre)."""
    n = leer_campo(slide_ficha, "numero")
    return int(n if n is not None else leer_campo(slide_ficha, "slide"))


def _campos_llm(slide_ficha: object) -> list[tuple[str, object]]:
    """Pares (nombre sin llaves, regla) de los campos que escribe el LLM en un slide de la ficha."""
    campos = leer_campo(slide_ficha, "campos", ())
    # Los campos pueden venir como lista de reglas con su nombre o como mapa nombre -> regla.
    if isinstance(campos, Mapping):
        pares = list(campos.items())
    else:
        pares = [(leer_campo(c, "nombre"), c) for c in campos]
    resultado = []
    for nombre, regla in pares:
        origen = leer_campo(regla, "origen_valor", leer_campo(regla, "origen", "llm"))
        # Solo cuentan los campos con nombre cuyo valor escribe el LLM.
        if nombre and origen == "llm":
            resultado.append((nombre_campo(nombre), regla))
    return resultado


def _textos_por_slide(textos: Iterable[TextoSlide]) -> dict[int, dict[str, object]]:
    """Indexa los campos de texto del redactor por número de slide, con nombres sin llaves."""
    indice = {}
    # Un slide sin campos en forma de mapa se ignora.
    for t in textos:
        campos = leer_campo(t, "campos", {})
        if isinstance(campos, Mapping):
            numero = leer_campo(t, "slide", leer_campo(t, "numero"))
            indice[numero] = {nombre_campo(k): v for k, v in campos.items()}
    return indice


def _numero_slide_fuentes(resolucion: object) -> int:
    """Número del slide de fuentes (el último si la ficha no lo marca con ese rol)."""
    slides = _slides_ficha(resolucion)
    # Se busca el slide con rol "fuentes"; si no hay, el último; si no hay slides, el 1.
    for s in slides:
        if leer_campo(s, "rol") == "fuentes":
            return _numero(s)
    return _numero(slides[-1]) if slides else 1


def comprobar_estructura(resolucion: object, textos: Iterable[TextoSlide]) -> list[Hallazgo]:
    """Comprueba que la ficha tenga gancho, desarrollo, cierre y fuentes, y que cada slide tenga su texto."""
    slides = _slides_ficha(resolucion)
    roles = {leer_campo(s, "rol") for s in slides}
    hallazgos = []
    # Faltan los roles fijos: es un error de planificación del estratega.
    faltan = [rol for rol in ROLES_FIJOS if rol not in roles]
    # Desarrollo = cualquier slide cuyo rol no sea de los fijos.
    if not (roles - set(ROLES_FIJOS)):
        faltan.insert(1, "desarrollo")
    for rol in faltan:
        hallazgos.append(crear_hallazgo(
            "estructura", "bloqueante", 1, f"Roles de la ficha: {', '.join(sorted(map(str, roles))) or 'ninguno'}",
            f"La estructura del carrusel no tiene un slide de «{rol}».",
            f"Añade a la ficha un slide de «{rol}».", "estratega"))
    # Cada slide con campos del LLM necesita su texto; si falta, es del redactor.
    por_slide = _textos_por_slide(textos)
    for s in slides:
        n = _numero(s)
        if _campos_llm(s) and n not in por_slide:
            hallazgos.append(crear_hallazgo(
                "estructura", "bloqueante", n, f"Slide {n} sin texto",
                "El redactor no entregó texto para un slide que lo necesita.",
                f"Escribe el texto del slide {n}.", "redactor"))
    return hallazgos


def comprobar_longitud(resolucion: object, textos: Iterable[TextoSlide]) -> list[Hallazgo]:
    """Campos obligatorios vacíos o ausentes y campos que superan `longitud_max` de la ficha."""
    por_slide = _textos_por_slide(textos)
    hallazgos = []
    # Se recorre la ficha slide a slide y campo a campo.
    for s in _slides_ficha(resolucion):
        n = _numero(s)
        campos_texto = por_slide.get(n)
        # El slide sin texto ya lo señala comprobar_estructura.
        if campos_texto is None:
            continue
        for nombre, regla in _campos_llm(s):
            valor = campos_texto.get(nombre)
            texto = valor.strip() if isinstance(valor, str) else ""
            maximo = leer_campo(regla, "longitud_max") or leer_campo(regla, "max_chars")
            # Obligatorio y vacío: bloquea. Si no, se mide contra el máximo de la ficha.
            if leer_campo(regla, "obligatorio", False) and not texto:
                hallazgos.append(crear_hallazgo(
                    "longitud", "bloqueante", n, f"Campo «{nombre}» vacío",
                    "El campo es obligatorio en la ficha y no tiene texto.",
                    f"Escribe el campo «{nombre}» del slide {n}.", "redactor"))
            elif maximo and len(texto) > int(maximo):
                hallazgos.append(crear_hallazgo(
                    "longitud", "mayor", n, f"«{nombre}»: {len(texto)} caracteres (máximo {maximo})",
                    "El texto supera la longitud máxima de la ficha y desbordaría la plantilla.",
                    f"Acorta «{nombre}» a {maximo} caracteres o menos.", "redactor"))
    return hallazgos


def _dato_fuente(entrada: object, nombre: str) -> object:
    """Atribución o licencia de la entrada: entrada["fuente"][nombre], entrada[nombre] o entrada[nombre_fuente]."""
    fuente = leer_campo(entrada, "fuente")
    # Se prueba primero el bloque `fuente` y luego la raíz de la entrada.
    if isinstance(fuente, Mapping) and fuente.get(nombre):
        return fuente.get(nombre)
    return leer_campo(entrada, nombre) or leer_campo(entrada, f"{nombre}_fuente")


def comprobar_atribucion_licencia(resolucion: object, entrada: object) -> list[Hallazgo]:
    """Exige atribución y licencia de la fuente para poder mostrarlas en el slide de fuentes."""
    slide = _numero_slide_fuentes(resolucion)
    hallazgos = []
    # Cada dato ausente o en blanco es un hallazgo bloqueante.
    for nombre, etiqueta in (("atribucion", "atribución"), ("licencia", "licencia")):
        valor = _dato_fuente(entrada, nombre)
        if not isinstance(valor, str) or not valor.strip():
            hallazgos.append(crear_hallazgo(
                "atribucion_licencia", "bloqueante", slide, f"Falta la {etiqueta} de la fuente",
                f"Sin {etiqueta} no se puede publicar el slide de fuentes.",
                f"Indica la {etiqueta} de la fuente en la entrada.", "estratega"))
    return hallazgos


def revisar_codigo(resolucion: object, kit: object, textos: Sequence[TextoSlide],
                   entrada: object) -> list[Hallazgo]:
    """Ejecuta todas las comprobaciones deterministas y devuelve los hallazgos ordenados."""
    hallazgos = [
        *comprobar_contraste(kit),
        *comprobar_estructura(resolucion, textos),
        *comprobar_longitud(resolucion, textos),
        *comprobar_atribucion_licencia(resolucion, entrada),
    ]
    return ordenar_hallazgos(hallazgos)