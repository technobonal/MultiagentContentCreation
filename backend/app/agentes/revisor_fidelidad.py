"""Revisor de fidelidad: comprueba cada afirmación factual del texto de un slide contra la fuente.

Basado en el verificador del spike v3b, con estas decisiones:
- Se verifica POR SLIDE y solo con los fragmentos que el estratega le asignó (`Brief.fragmentos_por_slide`),
  no con la fuente entera: cabe en el límite de tokens por minuto y la evidencia queda acotada.
- La cita debe ser un único trozo literal (tolerando espacios) dentro de esos fragmentos. Se ubica
  con `ubicar_hecho` (verificar_hechos.py), de modo que se cumple `fuente.texto[inicio:fin] ==
  cita.fragmento`. Si no es literal, un veredicto que respalda pasa a `no_verificada`, que nunca
  abre un hallazgo.
- El código impone las reglas del contrato `verificacion_fidelidad` (una opinión o CTA nunca
  lleva veredicto distinto de `no_aplica`; una cifra o un `contradice` la vuelven factual).
- Además, el código comprueba por su cuenta que las cifras del slide existan en los fragmentos,
  sin depender del LLM. El hallazgo de cifra lleva la frase donde aparece la cifra (para que el
  corrector la ubique), compara cifras exactas (no subcadenas) e ignora los marcadores de lista
  («1.», «2)») al inicio de línea.
- Gravedad: `contradice` y `no_respaldada` son bloqueantes; `parcialmente_respaldada` es mayor.
  Una cifra que el código no encuentra en los fragmentos es mayor (respaldo del LLM, con más
  riesgo de falso positivo por cifras derivadas, como «3 pasos»).
- Ningún slide con texto pasa sin veredictos: si vuelve sin afirmaciones se pide una vez más, solo; si sigue
  vacío, abre un hallazgo que nadie corrige solo, así que el run lo tiene que mirar una persona. Una afirmación
  ajena al texto del slide no puede sumar al sello (si abre un hallazgo se conserva: nunca se esconde un problema).
- Fallback solo dentro de la cadena propia del revisor (`config.GROQ_FALLBACK_REVISOR`, tanda 10B): ambos
  modelos son gpt-oss, de otra familia que el redactor (qwen), así que la independencia se mantiene y,
  cuando un modelo no tiene cupo de tokens, el otro responde en vez de esperar. El revisor nunca cae al
  modelo del redactor. El cliente decide el modelo según el rol «revisor_a».

Entrada:  el `Brief`, la fuente cargada y los `TextoSlide` del redactor.
Salida:   un `ResultadoFidelidad` con las afirmaciones verificadas, los hallazgos y el sello.

`TextoSlide` trae .numero (int) y .campos (nombre sin llaves -> texto); también se acepta .slide.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app import config
from app.agentes.cliente_llm import ClienteLLM
from app.agentes.comun import AgenteError, cargar_prompt, pedir_json
from app.agentes.estratega import Brief
from app.agentes.revisor_codigo import (
    Hallazgo, crear_hallazgo, leer_campo, nombre_campo, ordenar_hallazgos, recortar_texto)
from app.agentes.verificar_hechos import quitar_bordes, ubicar_hecho
from app.fuentes.cargador_fuente import Fragmento, FuenteCargada

# TextoSlide solo se usa en anotaciones: así este módulo no depende de que redactor.py importe.
if TYPE_CHECKING:
    from app.agentes.redactor import TextoSlide

# Rol del cliente LLM para el revisor: debe existir en ClienteGroq.modelos (revisor_a = gpt-oss-120b).
# Su cadena de fallback propia sale de config.GROQ_FALLBACK_REVISOR (ver el docstring del módulo).
ROL_REVISOR = "revisor_a"

# Tokens de salida que se piden (y se reservan en el límite por minuto). Antes eran 4000 (valor del spike): esa
# reserva casi llenaba la ventana y cada llamada esperaba ~1 minuto. Ahora sale de config (2000 por defecto,
# medido en la 10A); si el modelo se queda corto aparece finish_reason=length y se sube LLM_MAX_TOKENS_REVISOR.
MAX_TOKENS_REVISOR = config.LLM_MAX_TOKENS_REVISOR

# Slides por llamada del revisor real (ver config). Con un `pedir` inyectado se usa 1, salvo que se pida otro valor.
SLIDES_POR_LLAMADA = config.LLM_REVISOR_SLIDES_POR_LLAMADA

# Separador entre slides en el mensaje de una llamada agrupada.
SEPARADOR_SLIDES = "\n\n---\n\n"

# Parámetros extra de la API para el revisor: razonamiento bajo deja espacio al JSON (valor del spike).
EXTRA_REVISOR = {"reasoning_effort": "low"}

# Cota de afirmaciones por slide y de longitud de la cita.
MAX_AFIRMACIONES_SLIDE = 12
CITA_MAX_CHARS = 300

# Largo máximo (en caracteres) de la frase de contexto que acompaña a una cifra sin respaldo. Es corto a
# propósito: `crear_hallazgo` puede tener un tope de longitud para la evidencia.
FRASE_CIFRA_MAX_CHARS = 100

# Identificadores de afirmación a1 a a999 (contrato `verificacion_fidelidad`).
MAX_AFIRMACIONES_RUN = 999
_ID_AFIRMACION = re.compile(r"a[0-9]{1,3}")

TIPOS = ("factual", "opinion_cta")
VEREDICTOS_FACTUALES = ("respaldada", "parcialmente_respaldada", "no_respaldada", "contradice")
VEREDICTOS_QUE_RESPALDAN = ("respaldada", "parcialmente_respaldada")
VEREDICTOS = (*VEREDICTOS_FACTUALES, "no_verificada", "no_aplica")

# Un número con separadores opcionales y, si lo hay, su símbolo de porcentaje.
_CIFRA = re.compile(r"(\d+(?:[.,]\d+)*)(\s?%)?")

# Marcador de lista: 1 o 2 dígitos al inicio de línea (tras una viñeta opcional), seguidos de «.» o «)» y un
# espacio. «1.5 millones» no cuenta (tras el punto no hay espacio) y una cifra a mitad de línea tampoco.
_MARCADOR_LISTA = re.compile(r"[ \t]*(?:[-*•][ \t]+)?(?P<n>\d{1,2})[.)]\s")

# Quita los comentarios HTML del prompt (no deben viajar al modelo).
_COMENTARIO_HTML = re.compile(r"<!--.*?-->", re.DOTALL)

# Fracción mínima de las palabras con contenido de una afirmación que tienen que estar en el texto del slide.
COINCIDENCIA_MINIMA = 0.5
# Se comparan los primeros caracteres, para tolerar «controla» frente a «controlar».
LARGO_RAIZ = 5
# Palabras de 4 letras o más que no dicen de qué habla la frase (sin tildes). Las más cortas ya se ignoran.
PALABRAS_VACIAS = frozenset(
    "algo ante aqui cada como cuando debe deben desde donde ellos entre eres esta estan este esto hace hacia "
    "hasta mismo mucho nada otra otro para pero poco porque puede pueden puedes sean segun sera sino sobre solo "
    "tambien tanto tiene tienen toda todas todo todos unas unos usted".split())

# Función que envía (sistema, usuario) al revisor y devuelve el JSON ya interpretado.
Pedir = Callable[[str, str], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True)
class Afirmacion:
    """Una afirmación verificada, conforme al payload de `verificacion_fidelidad`."""

    afirmacion_id: str
    slide: int
    afirmacion: str
    clasificacion: str  # "factual" u "opinion_cta"
    veredicto: str
    cita: dict | None  # {"fragmento", "inicio", "fin"} o None
    motivo: str

    def __post_init__(self):
        """Impone las 4 reglas de coherencia del contrato para no emitir nunca un evento inválido."""
        v, c = self.veredicto, self.clasificacion
        # Valores básicos: id, enumeraciones y textos no vacíos.
        if not _ID_AFIRMACION.fullmatch(self.afirmacion_id):
            raise AgenteError("afirmacion_invalida", f"Id de afirmación inválido: {self.afirmacion_id!r}.")
        if c not in TIPOS or v not in VEREDICTOS:
            raise AgenteError("afirmacion_invalida", f"Clasificación o veredicto desconocido: {c!r}/{v!r}.")
        if not self.afirmacion.strip() or not self.motivo.strip():
            raise AgenteError("afirmacion_invalida", "La afirmación y el motivo no pueden estar vacíos.")
        # Regla 1: un veredicto que respalda exige una cita literal.
        if v in VEREDICTOS_QUE_RESPALDAN and self.cita is None:
            raise AgenteError("afirmacion_invalida", f"El veredicto {v!r} exige una cita.")
        # Regla 2: una opinión o CTA solo puede tener el veredicto no_aplica.
        if c == "opinion_cta" and v != "no_aplica":
            raise AgenteError("afirmacion_invalida", "Una opinión o CTA solo admite el veredicto no_aplica.")
        # Regla 3: no_aplica solo es legítimo para opinión o CTA.
        if v == "no_aplica" and c != "opinion_cta":
            raise AgenteError("afirmacion_invalida", "El veredicto no_aplica exige clasificación opinion_cta.")
        # Regla 4: «contradice» habla de un hecho, así que la afirmación es siempre factual.
        if v == "contradice" and c != "factual":
            raise AgenteError("afirmacion_invalida", "El veredicto contradice exige clasificación factual.")
        # Comprobación extra: la cita, si existe, tiene fragmento y posiciones coherentes.
        if self.cita is not None:
            fragmento, inicio, fin = (self.cita.get(k) for k in ("fragmento", "inicio", "fin"))
            if (not isinstance(fragmento, str) or not fragmento or len(fragmento) > CITA_MAX_CHARS
                    or not isinstance(inicio, int) or not isinstance(fin, int) or not 0 <= inicio < fin):
                raise AgenteError("afirmacion_invalida", "La cita no tiene fragmento y posiciones válidas.")

    def a_evento(self) -> dict:
        """{"slide", "payload"} listo para el evento `verificacion_fidelidad` (el slide va en el sobre)."""
        return {
            "slide": self.slide,
            "payload": {
                "afirmacion_id": self.afirmacion_id,
                "afirmacion": self.afirmacion,
                "clasificacion": self.clasificacion,
                "veredicto": self.veredicto,
                "cita": self.cita,
                "motivo": self.motivo,
            },
        }


@dataclass(frozen=True)
class ResultadoFidelidad:
    """Resultado de revisar todos los slides: afirmaciones, hallazgos y resumen (sello)."""

    afirmaciones: list[Afirmacion]
    hallazgos: list[Hallazgo]
    sello: dict


# ---------------------------------------------------------------- cifras

def _normalizar_cifra(numero: str) -> str:
    """Unifica la coma decimal con el punto para comparar «1,5» con «1.5»."""
    return numero.replace(",", ".")


def _sin_separadores(numero: str) -> str:
    """Deja solo los dígitos, para que «1.000» y «1000» se reconozcan como la misma cifra."""
    return re.sub(r"[.,]", "", numero)


def _cifras(texto: str) -> list[str]:
    """Cifras del texto tal como están escritas, sin repetidas y en orden de aparición."""
    vistas = []
    # Cada coincidencia aporta su número (el símbolo % no cuenta para comparar).
    for m in _CIFRA.finditer(texto):
        if m.group(1) not in vistas:
            vistas.append(m.group(1))
    return vistas


def _cifras_de_fragmentos(fragmentos: Sequence[str]) -> set[str]:
    """Conjunto de cifras de los fragmentos, en forma normalizada y sin separadores."""
    conjunto = set()
    # Se guardan las dos formas para tolerar «1.000» frente a «1000».
    for fragmento in fragmentos:
        for cifra in _cifras(fragmento):
            conjunto.add(_normalizar_cifra(cifra))
            conjunto.add(_sin_separadores(cifra))
    return conjunto


def _cifras_exactas(texto: str) -> set[str]:
    """Cifras de un texto como conjunto de formas exactas (normalizada y sin separadores), sin subcadenas.

    Sirve para decidir si una cifra ya está señalada: «1» coincide con «1», pero no con «11» ni con «2024».
    """
    conjunto = set()
    for cifra in _cifras(texto):
        conjunto.add(_normalizar_cifra(cifra))
        conjunto.add(_sin_separadores(cifra))
    return conjunto


def _es_marcador_de_lista(texto: str, inicio: int) -> bool:
    """True si el número que empieza en `inicio` es un marcador de lista («1.», «2)») al inicio de línea."""
    inicio_linea = texto.rfind("\n", 0, inicio) + 1
    m = _MARCADOR_LISTA.match(texto, inicio_linea)
    return m is not None and m.start("n") == inicio


def _frase_de_cifra(texto: str, inicio: int, fin: int) -> str:
    """Trozo corto de `texto` alrededor de la cifra (posiciones inicio:fin), para que el corrector la ubique."""
    mitad = max(0, (FRASE_CIFRA_MAX_CHARS - (fin - inicio)) // 2)
    desde = max(0, inicio - mitad)
    hasta = min(len(texto), fin + mitad)
    # Si el corte cae a mitad de palabra, se acerca al siguiente espacio sin pasar de la cifra.
    if desde > 0 and not texto[desde - 1].isspace():
        espacio = texto.find(" ", desde, inicio)
        if espacio != -1:
            desde = espacio + 1
    frase = " ".join(texto[desde:hasta].split())
    return ("…" if desde > 0 else "") + frase + ("…" if hasta < len(texto) else "")


def hallazgos_por_cifras(slide: int, campos: Mapping[str, str], fragmentos: Sequence[str],
                         hallazgos_llm: Sequence[Hallazgo]) -> list[Hallazgo]:
    """Marca las cifras del slide que no aparecen en los fragmentos asignados (control por código).

    Ignora los marcadores de lista y compara cifras exactas con lo que el LLM ya señaló. La evidencia
    incluye la frase donde aparece la cifra, para que el corrector sepa dónde actuar.
    """
    disponibles = _cifras_de_fragmentos(fragmentos)
    # Cifras exactas que el LLM ya señaló en este slide (sin tratar «1» como parte de «11»).
    senaladas = set()
    for h in hallazgos_llm:
        if h.slide == slide:
            senaladas |= _cifras_exactas(h.evidencia)
    hallazgos = []
    vistas = set()
    # Se recorren todos los campos del slide buscando cifras.
    for nombre, texto in campos.items():
        if not isinstance(texto, str):
            continue
        for m in _CIFRA.finditer(texto):
            cifra = m.group(1)
            clave = _normalizar_cifra(cifra)
            # Un marcador de lista no es una cifra factual: no se verifica.
            if _es_marcador_de_lista(texto, m.start(1)):
                continue
            esta = clave in disponibles or _sin_separadores(cifra) in disponibles
            ya_senalada = clave in senaladas or _sin_separadores(cifra) in senaladas
            # Una cifra respaldada, repetida o ya señalada por el LLM no abre hallazgo nuevo.
            if esta or clave in vistas or ya_senalada:
                continue
            vistas.add(clave)
            frase = _frase_de_cifra(texto, m.start(1), m.end(1))
            hallazgos.append(crear_hallazgo(
                "fidelidad", "mayor", slide,
                f"«{nombre_campo(nombre)}»: la cifra {cifra} no está en los fragmentos asignados "
                f"(frase: «{frase}»)",
                "La cifra no aparece en la fuente que respalda este slide.",
                f"Los fragmentos asignados no contienen la cifra {cifra}. Quítala de esa frase "
                "(o describe el elemento sin cantidad); no la reformules con otro número.",
                "redactor"))
    return hallazgos


log = logging.getLogger(__name__)

# ---------------------------------------------------------------- citas y afirmaciones

def _raices(texto: str) -> set[str]:
    """Raíces de las palabras con contenido (y las cifras) de un texto, sin tildes ni mayúsculas."""
    plano = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")
    return {
        p[:LARGO_RAIZ] for p in re.findall(r"[a-z0-9]+", plano)
        if p.isdigit() or (len(p) >= 4 and p not in PALABRAS_VACIAS)
    }


def es_del_texto(afirmacion: str, campos: Mapping[str, str]) -> bool:
    """True si la afirmación habla del texto del slide. Sin palabras con las que decidir, se da por buena."""
    propias = _raices(afirmacion)
    if not propias:
        return True
    del_slide = _raices(" ".join(v for v in campos.values() if isinstance(v, str)))
    return len(propias & del_slide) / len(propias) >= COINCIDENCIA_MINIMA


def _por_que_no_es_literal(cita: object) -> str:
    """Causa legible de una cita rechazada, solo para el log (el contrato no la guarda)."""
    if not isinstance(cita, str) or not cita.strip():
        return "sin cita"
    if len(cita.strip()) > CITA_MAX_CHARS:
        return f"demasiado larga ({len(cita.strip())} caracteres, tope {CITA_MAX_CHARS})"
    limpia = quitar_bordes(cita)
    if "..." in limpia or "…" in limpia:
        return "une trozos con puntos suspensivos"
    return "no aparece en los fragmentos asignados"


def _localizar_cita(cita: object, fragmentos: Sequence[Fragmento]) -> dict | None:
    """Ubica una cita literal en los fragmentos asignados con `ubicar_hecho`.

    Devuelve {fragmento, inicio, fin} con posiciones absolutas en la fuente, o None si no es literal.
    """
    # Solo se aceptan cadenas con contenido y dentro del tope.
    if not isinstance(cita, str) or not cita.strip() or len(cita.strip()) > CITA_MAX_CHARS:
        return None
    # Las comillas y los «...» de los extremos no son parte de la cita (el modelo los suele agregar al recortar).
    cita = quitar_bordes(cita)
    # La cita estricta es un único trozo: nada de puntos suspensivos EN EL MEDIO (unir trozos no es citar).
    if not cita or "..." in cita or "…" in cita:
        return None
    ubicado = ubicar_hecho(cita, fragmentos)
    # El fragmento guardado es el trozo exacto de la fuente (cumple fuente.texto[inicio:fin]).
    if ubicado is None or len(ubicado.texto) > CITA_MAX_CHARS:
        return None
    return {"fragmento": ubicado.texto, "inicio": ubicado.inicio, "fin": ubicado.fin}


def _normalizar_afirmacion(crudo: object, slide: int, numero: int,
                           fragmentos: Sequence[Fragmento]) -> Afirmacion | None:
    """Convierte una afirmación cruda del modelo en `Afirmacion`, imponiendo las reglas del contrato."""
    if not isinstance(crudo, Mapping):
        return None
    texto = crudo.get("afirmacion")
    # Sin texto no hay nada que verificar.
    if not isinstance(texto, str) or not texto.strip():
        return None
    texto = recortar_texto(texto)
    motivo = recortar_texto(crudo.get("motivo") or "Sin motivo indicado.")
    tipo = crudo.get("tipo")
    veredicto = crudo.get("veredicto")
    # Ante la duda es factual; una cifra o un «contradice» la vuelven factual siempre.
    if tipo not in TIPOS or _cifras(texto) or veredicto == "contradice":
        tipo = "factual"
    ident = f"a{numero}"
    # Una opinión o CTA nunca lleva veredicto distinto de no_aplica ni cita.
    if tipo == "opinion_cta":
        return Afirmacion(ident, slide, texto, "opinion_cta", "no_aplica", None, motivo)
    cita = _localizar_cita(crudo.get("cita"), fragmentos)
    # Respaldo sin cita literal o veredicto inválido: no se puede verificar, nunca abre hallazgo.
    if veredicto in VEREDICTOS_QUE_RESPALDAN and cita is None:
        veredicto = "no_verificada"
        crudo_cita = crudo.get("cita")
        log.warning(
            "Cita rechazada (slide %d, %s): %s. Cita del modelo: %r",
            slide, ident, _por_que_no_es_literal(crudo_cita),
            crudo_cita[:400] if isinstance(crudo_cita, str) else crudo_cita,
        )
        motivo = recortar_texto(f"La cita no es literal de la fuente. {motivo}")
    elif veredicto not in VEREDICTOS_FACTUALES:
        veredicto, cita = "no_verificada", None
        motivo = recortar_texto(f"El modelo no dio un veredicto válido. {motivo}")
    return Afirmacion(ident, slide, texto, "factual", veredicto, cita, motivo)


def hallazgo_de_afirmacion(af: Afirmacion) -> Hallazgo | None:
    """Hallazgo de una afirmación: bloqueante si contradice o no está respaldada, mayor si es parcial."""
    # Solo estos tres veredictos abren hallazgo; respaldada, no_verificada y no_aplica no.
    if af.veredicto in ("contradice", "no_respaldada"):
        gravedad = "bloqueante"
    elif af.veredicto == "parcialmente_respaldada":
        gravedad = "mayor"
    else:
        return None
    return crear_hallazgo(
        "fidelidad", gravedad, af.slide, af.afirmacion, af.motivo,
        "Reescribe la afirmación para que coincida con la fuente o elimínala.", "redactor")


# ---------------------------------------------------------------- llamada al modelo

def _prompt_sistema() -> str:
    """Prompt de sistema del revisor (revisor.md, junto a los demás prompts), sin los comentarios HTML."""
    return _COMENTARIO_HTML.sub("", cargar_prompt("revisor")).strip()


def _validar_respuesta(dato: Any) -> list[str]:
    """Validador para `pedir_json`: acepta {"slides": [{"slide", "afirmaciones"}]} o, de un solo slide,
    {"afirmaciones": [...]}. Devuelve la lista de errores (vacía si la forma sirve)."""
    # Tolerante a propósito: un elemento ilegible de «slides» no tumba el run, ese slide se revisa solo después.
    if isinstance(dato, Mapping) and (
        isinstance(dato.get("afirmaciones"), list) or isinstance(dato.get("slides"), list)
    ):
        return []
    return ['Devuelve un objeto JSON {"slides": [{"slide": N, "afirmaciones": [...]}]}, un elemento por slide.']


_NUMERO = re.compile(r"\d+")


def _numero_slide(valor: Any) -> int | None:
    """Número de slide de un elemento de la respuesta: acepta 4, "4" o "SLIDE 4" (None si no hay número)."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str):
        m = _NUMERO.search(valor)
        return int(m.group()) if m else None
    return None


def _crudas_por_slide(respuesta: Any, slides: Sequence[int]) -> dict[int, list]:
    """Afirmaciones crudas de cada slide pedido. Un slide que la respuesta no trae queda fuera del mapa."""
    if not isinstance(respuesta, Mapping):
        return {}
    por_slide: dict[int, list] = {}
    lista = respuesta.get("slides")
    if isinstance(lista, list):
        for s in lista:
            numero = _numero_slide(s.get("slide")) if isinstance(s, Mapping) else None
            # Solo cuentan los slides pedidos; el primero que aparece manda si el modelo repite uno.
            if numero in slides and isinstance(s.get("afirmaciones"), list):
                por_slide.setdefault(numero, s["afirmaciones"])
    # Forma de un solo slide (la de siempre): solo vale si se pidió un único slide.
    elif len(slides) == 1 and isinstance(respuesta.get("afirmaciones"), list):
        por_slide[slides[0]] = respuesta["afirmaciones"]
    return por_slide


def _mensaje_usuario(slide: int, campos: Mapping[str, str], fragmentos: Sequence[str]) -> str:
    """Mensaje variable: número de slide, texto de cada campo y fragmentos asignados."""
    lineas = [f"SLIDE: {slide}", "", "TEXTO DEL SLIDE:"]
    # Cada campo con texto va etiquetado con su nombre (sin llaves).
    for nombre, texto in campos.items():
        if isinstance(texto, str) and texto.strip():
            lineas.append(f"[{nombre_campo(nombre)}] {' '.join(texto.split())}")
    lineas += ["", "FRAGMENTOS DE LA FUENTE:"]
    # Los fragmentos se numeran para que el modelo los distinga, sin que cuenten para la cita.
    for i, fragmento in enumerate(fragmentos, start=1):
        lineas.append(f"[F{i}] {fragmento}")
    return "\n".join(lineas)


def _fragmentos_del_slide(brief: Brief, fuente: FuenteCargada, slide: int) -> list[Fragmento]:
    """Fragmentos que el estratega asignó al slide, en su orden (vacío si no hay ninguno)."""
    fragmentos = []
    # Mismo criterio que el redactor: el índice asignado es la posición en fuente.fragmentos.
    for i in brief.fragmentos_por_slide.get(slide, ()):
        if 0 <= i < len(fuente.fragmentos):
            fragmentos.append(fuente.fragmentos[i])
    return fragmentos


def pedir_al_revisor(cliente: ClienteLLM, max_tokens: int = MAX_TOKENS_REVISOR) -> Pedir:
    """Función `Pedir` que usa el cliente real. Es el único punto que toca `pedir_json`."""
    async def pedir(sistema: str, usuario: str) -> Mapping[str, Any]:
        """Envía el prompt al rol «revisor», con la cadena de modelos propia del rol, y devuelve el JSON validado."""
        mensajes = [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
        dato, _respuesta = await pedir_json(
            cliente, ROL_REVISOR, mensajes, _validar_respuesta,
            max_tokens=max_tokens, permitir_fallback=None, extra=EXTRA_REVISOR)
        return dato
    return pedir


def _normalizar_lista(crudas: list, slide: int, campos: Mapping[str, str], fragmentos: Sequence[Fragmento],
                      primer_numero: int) -> list[Afirmacion]:
    """Normaliza las afirmaciones crudas de un slide; los ids siguen la numeración de toda la ejecución."""
    afirmaciones = []
    # Se normalizan solo las primeras N.
    for crudo in crudas[:MAX_AFIRMACIONES_SLIDE]:
        numero = primer_numero + len(afirmaciones)
        if numero > MAX_AFIRMACIONES_RUN:
            raise AgenteError("demasiadas_afirmaciones", f"No caben más de {MAX_AFIRMACIONES_RUN} afirmaciones.")
        af = _normalizar_afirmacion(crudo, slide, numero, fragmentos)
        if af is None:
            continue
        # El modelo a veces afirma cosas de los fragmentos que el slide no dice: no pueden contar a favor.
        if hallazgo_de_afirmacion(af) is None and not es_del_texto(af.afirmacion, campos):
            log.warning("Afirmación descartada (slide %d): no está en su texto: %r", slide, af.afirmacion[:200])
            continue
        afirmaciones.append(af)
    log.info("Revisor, slide %d: llegaron %d afirmaciones y cuentan %d", slide, len(crudas), len(afirmaciones))
    return afirmaciones


async def verificar_slide(pedir: Pedir, sistema: str, slide: int, campos: Mapping[str, str],
                          fragmentos: Sequence[Fragmento], primer_numero: int) -> list[Afirmacion]:
    """Verifica un slide: una llamada al modelo y normalización de sus afirmaciones."""
    respuesta = await pedir(sistema, _mensaje_usuario(slide, campos, [f.texto for f in fragmentos]))
    crudas = _crudas_por_slide(respuesta, [slide]).get(slide)
    # Sin la lista esperada, la respuesta no sirve y se corta con un error claro.
    if not isinstance(crudas, list):
        raise AgenteError("revisor_respuesta_invalida", f"El revisor no devolvió «afirmaciones» para el slide {slide}.")
    return _normalizar_lista(crudas, slide, campos, fragmentos, primer_numero)


async def _verificar_grupo(pedir: Pedir, sistema: str, grupo: Sequence[tuple[int, Mapping[str, str], list]],
                           primer_numero: int) -> list[list[Afirmacion]]:
    """Verifica varios slides en UNA llamada; devuelve las afirmaciones de cada slide, en el orden del grupo.

    Cada slide lleva sus propios fragmentos y su cita se ubica solo en ellos (la evidencia sigue acotada).
    Un slide que el modelo omite, o que vuelve sin afirmaciones, se verifica una vez más él solo. Si tampoco
    así trae ninguna, su lista queda vacía y `revisar_fidelidad` lo marca como sin verificar.
    """
    por_slide: dict[int, list] = {}
    if len(grupo) > 1:
        usuario = SEPARADOR_SLIDES.join(
            _mensaje_usuario(slide, campos, [f.texto for f in fragmentos]) for slide, campos, fragmentos in grupo)
        por_slide = _crudas_por_slide(await pedir(sistema, usuario), [slide for slide, _, _ in grupo])
    resultado = []
    numero = primer_numero
    # En el orden del grupo (no en el que respondió el modelo), para que los ids sean deterministas.
    for slide, campos, fragmentos in grupo:
        if len(grupo) == 1:
            nuevas = await verificar_slide(pedir, sistema, slide, campos, fragmentos, numero)
        else:
            nuevas = _normalizar_lista(por_slide.get(slide, []), slide, campos, fragmentos, numero)
        # Un slide omitido en el grupo todavía no se pidió solo; uno vacío merece un segundo intento.
        if not nuevas:
            log.warning("El slide %d volvió sin afirmaciones: se verifica de nuevo por separado", slide)
            nuevas = await verificar_slide(pedir, sistema, slide, campos, fragmentos, numero)
        resultado.append(nuevas)
        numero += len(nuevas)
    return resultado


def hallazgo_sin_verificar(slide: int) -> Hallazgo:
    """Un slide con texto del que no se obtuvo ningún veredicto. Responsable «estratega»: hoy nadie corrige eso
    solo, así que el ciclo escala y lo tiene que mirar una persona (no se reescribe un texto que nadie juzgó)."""
    return crear_hallazgo(
        "fidelidad", "mayor", slide, f"El slide {slide} quedó sin verificar.",
        "El revisor no devolvió ninguna afirmación sobre su texto, tampoco al pedirlo por separado.",
        "Compara a mano el texto de este slide con la fuente antes de aprobar.", "estratega")


async def revisar_fidelidad(cliente: ClienteLLM, brief: Brief, fuente: FuenteCargada,
                            textos: Sequence[TextoSlide], pedir: Pedir | None = None,
                            slides_por_llamada: int | None = None) -> ResultadoFidelidad:
    """Revisa la fidelidad de todos los slides con texto y devuelve afirmaciones, hallazgos y sello.

    `pedir` permite inyectar un falso en los tests; por defecto se usa el cliente real (rol «revisor»).
    `slides_por_llamada`: cuántos slides van en cada llamada. Sin valor, el cliente real usa
    `SLIDES_POR_LLAMADA` (config) y un `pedir` inyectado usa 1 (una llamada por slide, como antes).
    """
    if slides_por_llamada is None:
        slides_por_llamada = SLIDES_POR_LLAMADA if pedir is None else 1
    slides_por_llamada = max(1, slides_por_llamada)
    pedir_inyectado = pedir
    sistema = _prompt_sistema()
    afirmaciones: list[Afirmacion] = []
    hallazgos: list[Hallazgo] = []
    sin_fragmentos = 0
    sin_veredictos = 0
    # Primero se juntan los slides verificables, en orden; después se revisan en grupos.
    verificables: list[tuple[int, Mapping[str, str], list]] = []
    for t in textos:
        slide = leer_campo(t, "slide", leer_campo(t, "numero"))
        campos = leer_campo(t, "campos", {})
        if not isinstance(campos, Mapping) or not any(isinstance(v, str) and v.strip() for v in campos.values()):
            continue
        fragmentos = _fragmentos_del_slide(brief, fuente, slide)
        # Sin fragmentos asignados no hay contra qué verificar: se anota en el sello y se sigue.
        if not fragmentos:
            sin_fragmentos += 1
            continue
        verificables.append((slide, campos, fragmentos))
    verificados = len(verificables)
    # Un grupo a la vez: respeta el límite de tokens por minuto y deja ids deterministas.
    for inicio in range(0, len(verificables), slides_por_llamada):
        grupo = verificables[inicio:inicio + slides_por_llamada]
        # Una llamada agrupada devuelve más afirmaciones: el tope de salida crece con el grupo (hasta el doble).
        pedir = pedir_inyectado or pedir_al_revisor(cliente, MAX_TOKENS_REVISOR * min(len(grupo), 2))
        por_slide = await _verificar_grupo(pedir, sistema, grupo, len(afirmaciones) + 1)
        for (slide, campos, fragmentos), nuevas in zip(grupo, por_slide):
            if not nuevas:
                sin_veredictos += 1
                hallazgos.append(hallazgo_sin_verificar(slide))
            afirmaciones += nuevas
            hallazgos_slide = [h for h in map(hallazgo_de_afirmacion, nuevas) if h is not None]
            # Control por código de las cifras, sin repetir lo que el LLM ya marcó.
            hallazgos_slide += hallazgos_por_cifras(slide, campos, [f.texto for f in fragmentos], hallazgos_slide)
            hallazgos += hallazgos_slide
    factuales = [a for a in afirmaciones if a.clasificacion == "factual"]
    sello = {
        "slides_verificados": verificados - sin_veredictos,
        "slides_sin_fragmentos": sin_fragmentos,
        "afirmaciones_factuales": len(factuales),
        "respaldadas": sum(a.veredicto == "respaldada" for a in factuales),
        "no_verificadas": sum(a.veredicto == "no_verificada" for a in factuales),
        "hallazgos": len(hallazgos),
    }
    return ResultadoFidelidad(afirmaciones, ordenar_hallazgos(hallazgos), sello)