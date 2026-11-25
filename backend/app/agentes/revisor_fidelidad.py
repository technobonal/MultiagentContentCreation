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
- Fallback solo dentro de la cadena propia del revisor (`config.GROQ_FALLBACK_REVISOR`, tanda 10B): ambos
  modelos son gpt-oss, de otra familia que el redactor (qwen), así que la independencia se mantiene y,
  cuando un modelo no tiene cupo de tokens, el otro responde en vez de esperar. El revisor nunca cae al
  modelo del redactor. El cliente decide el modelo según el rol «revisor_a».

Entrada:  el `Brief`, la fuente cargada y los `TextoSlide` del redactor.
Salida:   un `ResultadoFidelidad` con las afirmaciones verificadas, los hallazgos y el sello.

`TextoSlide` trae .numero (int) y .campos (nombre sin llaves -> texto); también se acepta .slide.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app import config
from app.agentes.cliente_llm import ClienteLLM
from app.agentes.comun import AgenteError, cargar_prompt, pedir_json
from app.agentes.estratega import Brief
from app.agentes.revisor_codigo import (
    Hallazgo, crear_hallazgo, leer_campo, nombre_campo, ordenar_hallazgos, recortar_texto)
from app.agentes.verificar_hechos import ubicar_hecho
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


# ---------------------------------------------------------------- citas y afirmaciones

def _localizar_cita(cita: object, fragmentos: Sequence[Fragmento]) -> dict | None:
    """Ubica una cita literal en los fragmentos asignados con `ubicar_hecho`.

    Devuelve {fragmento, inicio, fin} con posiciones absolutas en la fuente, o None si no es literal.
    """
    # Solo se aceptan cadenas con contenido y dentro del tope.
    if not isinstance(cita, str) or not cita.strip() or len(cita.strip()) > CITA_MAX_CHARS:
        return None
    cita = cita.strip()
    # La cita estricta es un único trozo: nada de puntos suspensivos.
    if "..." in cita or "…" in cita:
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
    """Validador para `pedir_json`: lista de errores si falta la lista «afirmaciones»."""
    if not isinstance(dato, Mapping) or not isinstance(dato.get("afirmaciones"), list):
        return ["Devuelve un objeto JSON con la clave «afirmaciones» (lista)."]
    return []


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


def pedir_al_revisor(cliente: ClienteLLM) -> Pedir:
    """Función `Pedir` que usa el cliente real. Es el único punto que toca `pedir_json`."""
    async def pedir(sistema: str, usuario: str) -> Mapping[str, Any]:
        """Envía el prompt al rol «revisor», con la cadena de modelos propia del rol, y devuelve el JSON validado."""
        mensajes = [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
        dato, _respuesta = await pedir_json(
            cliente, ROL_REVISOR, mensajes, _validar_respuesta,
            max_tokens=MAX_TOKENS_REVISOR, permitir_fallback=None, extra=EXTRA_REVISOR)
        return dato
    return pedir


async def verificar_slide(pedir: Pedir, sistema: str, slide: int, campos: Mapping[str, str],
                          fragmentos: Sequence[Fragmento], primer_numero: int) -> list[Afirmacion]:
    """Verifica un slide: una llamada al modelo y normalización de sus afirmaciones."""
    respuesta = await pedir(sistema, _mensaje_usuario(slide, campos, [f.texto for f in fragmentos]))
    crudas = respuesta.get("afirmaciones") if isinstance(respuesta, Mapping) else None
    # Sin la lista esperada, la respuesta no sirve y se corta con un error claro.
    if not isinstance(crudas, list):
        raise AgenteError("revisor_respuesta_invalida", f"El revisor no devolvió «afirmaciones» para el slide {slide}.")
    afirmaciones = []
    # Se normalizan solo las primeras N; los ids siguen la numeración de toda la ejecución.
    for crudo in crudas[:MAX_AFIRMACIONES_SLIDE]:
        numero = primer_numero + len(afirmaciones)
        if numero > MAX_AFIRMACIONES_RUN:
            raise AgenteError("demasiadas_afirmaciones", f"No caben más de {MAX_AFIRMACIONES_RUN} afirmaciones.")
        af = _normalizar_afirmacion(crudo, slide, numero, fragmentos)
        if af is not None:
            afirmaciones.append(af)
    return afirmaciones


async def revisar_fidelidad(cliente: ClienteLLM, brief: Brief, fuente: FuenteCargada,
                            textos: Sequence[TextoSlide], pedir: Pedir | None = None) -> ResultadoFidelidad:
    """Revisa la fidelidad de todos los slides con texto y devuelve afirmaciones, hallazgos y sello.

    `pedir` permite inyectar un falso en los tests; por defecto se usa el cliente real (rol «revisor»).
    """
    pedir = pedir or pedir_al_revisor(cliente)
    sistema = _prompt_sistema()
    afirmaciones: list[Afirmacion] = []
    hallazgos: list[Hallazgo] = []
    verificados = sin_fragmentos = 0
    # Un slide a la vez: respeta el límite de tokens por minuto y deja ids deterministas.
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
        verificados += 1
        nuevas = await verificar_slide(pedir, sistema, slide, campos, fragmentos, len(afirmaciones) + 1)
        afirmaciones += nuevas
        hallazgos_slide = [h for h in map(hallazgo_de_afirmacion, nuevas) if h is not None]
        # Control por código de las cifras, sin repetir lo que el LLM ya marcó.
        hallazgos_slide += hallazgos_por_cifras(slide, campos, [f.texto for f in fragmentos], hallazgos_slide)
        hallazgos += hallazgos_slide
    factuales = [a for a in afirmaciones if a.clasificacion == "factual"]
    sello = {
        "slides_verificados": verificados,
        "slides_sin_fragmentos": sin_fragmentos,
        "afirmaciones_factuales": len(factuales),
        "respaldadas": sum(a.veredicto == "respaldada" for a in factuales),
        "no_verificadas": sum(a.veredicto == "no_verificada" for a in factuales),
        "hallazgos": len(hallazgos),
    }
    return ResultadoFidelidad(afirmaciones, ordenar_hallazgos(hallazgos), sello)