"""Estratega (paso 2): decide el ángulo, el tono y qué fragmentos de la fuente respalda cada slide.

No recibe la fuente entera sino un ÍNDICE compacto (número + primeros caracteres de cada
fragmento). Así un único camino de código sirve para fuentes chicas y grandes, y el pedido
cabe en el límite de tokens por minuto del plan gratuito.

Entrada:  la entrada del run (ya validada), la resolución (ficha y número de slides) y la
          fuente cargada (`FuenteCargada`).
Salida:   un `Brief` con ángulo, tono y los fragmentos asignados a cada slide.

El código, no el modelo, comprueba que el brief sea coherente (slides completos, fragmentos
existentes, longitudes) antes de aceptarlo.
"""

from dataclasses import dataclass
from typing import Any

from app.agentes.cliente_llm import ClienteLLM
from app.agentes.comun import AgenteError, cargar_prompt, pedir_json
from app.fuentes.cargador_fuente import FuenteCargada, Fragmento

# Tokens de salida que se piden (y se reservan en el límite por minuto).
MAX_TOKENS_ESTRATEGA = 1200

# Límites de longitud del brief (el contrato del evento brief_emitido puede ajustarlos).
ANGULO_MAX = 200
TONO_MAX = 80

# Fragmentos por slide: acota lo que recibirá el redactor (3 x 1.000 caracteres como mucho).
MIN_FRAGMENTOS_POR_SLIDE = 1
MAX_FRAGMENTOS_POR_SLIDE = 3

# Vista previa de cada fragmento en el índice: ideal y mínimo, en caracteres.
PREVIA_IDEAL = 250
PREVIA_MIN = 30

# Presupuesto total del índice, en caracteres (~3.300 tokens a 3 caracteres por token).
# Con 1.200 de salida y el prompt fijo, el pedido queda por debajo de los 6.400 utilizables.
PRESUPUESTO_INDICE_CHARS = 10_000


@dataclass(frozen=True)
class Brief:
    """Resultado del estratega."""

    angulo: str
    tono: str
    fragmentos_por_slide: dict[int, tuple[int, ...]]  # número de slide -> índices de fragmento
    modelo: str  # modelo que realmente contestó (puede diferir del pedido si hubo fallback)
    fallback: bool

    def payload_evento(self, resolucion) -> dict:
        """Payload del evento `brief_emitido`. Los fragmentos asignados no viajan: los usa el redactor."""
        ficha = resolucion.ficha
        return {
            "angulo": self.angulo,
            "tono": self.tono,
            "num_slides": resolucion.num_slides,
            "tipo_mensaje": ficha["tipo_mensaje"],
            "roles": [s["rol"] for s in ficha["slides"]],
        }


def _una_linea(texto: str) -> str:
    """Aplana el texto a una sola línea (saltos y espacios repetidos pasan a un espacio)."""
    return " ".join(texto.split())


def construir_indice(fragmentos: tuple[Fragmento, ...], presupuesto: int = PRESUPUESTO_INDICE_CHARS) -> str:
    """Arma el índice: una línea `[n] comienzo del fragmento…` por fragmento.

    La vista previa se acorta sola (de PREVIA_IDEAL a PREVIA_MIN) para que el índice entero
    quepa en `presupuesto`. Si ni con el mínimo cabe, lanza AgenteError `fuente_demasiado_larga`.
    """
    n = len(fragmentos)
    # Sin fragmentos no hay nada que indexar (la fuente vacía ya la rechaza el cargador).
    if n == 0:
        raise AgenteError("fuente_vacia", "La fuente no tiene fragmentos que indexar.")

    sobrecosto = len(f"[{n - 1}] …\n")  # etiqueta, elipsis y salto de línea de la línea más larga
    previa = min(PREVIA_IDEAL, presupuesto // n - sobrecosto)
    # Ni con la vista previa mínima cabe: se informa en lugar de truncar el índice a ciegas.
    if previa < PREVIA_MIN:
        raise AgenteError(
            "fuente_demasiado_larga",
            f"La fuente tiene {n} fragmentos y su índice no cabe en el límite de tokens. "
            "Usa una fuente más corta o fragmentos más grandes.",
        )

    lineas = []
    # Una línea por fragmento, con su número real (el que el estratega devolverá).
    for f in fragmentos:
        plano = _una_linea(f.texto)
        corte = plano[:previa]
        lineas.append(f"[{f.indice}] {corte}{'…' if len(plano) > previa else ''}")
    return "\n".join(lineas)


def construir_mensajes(entrada: dict, resolucion, fuente: FuenteCargada) -> list[dict[str, str]]:
    """Arma los mensajes: prompt fijo primero (system) y datos variables al final (user)."""
    ficha = resolucion.ficha
    slides = "\n".join(f"- Slide {s['numero']}: {s['rol']}" for s in ficha["slides"])
    usuario = (
        f"Plataforma: {entrada['destino']['red']}\n"
        f"Idioma de salida: {entrada['fuente']['idioma_salida']}\n"
        f"Tipo de mensaje: {ficha['tipo_mensaje']}\n"
        f"Slides ({resolucion.num_slides}):\n{slides}\n\n"
        f"Índice de la fuente ({len(fuente.fragmentos)} fragmentos):\n{construir_indice(fuente.fragmentos)}"
    )
    return [
        {"role": "system", "content": cargar_prompt("estratega")},
        {"role": "user", "content": usuario},
    ]


def validar_brief(dato: Any, numeros_slide: list[int], num_fragmentos: int) -> list[str]:
    """Comprueba el JSON del estratega y devuelve los motivos de rechazo (lista vacía = válido)."""
    # Debe ser un objeto: cualquier otra cosa (lista, texto) no tiene campos que revisar.
    if not isinstance(dato, dict):
        return ["la respuesta debe ser un objeto JSON"]
    motivos: list[str] = []

    # Ángulo y tono: texto no vacío y dentro de su longitud máxima.
    for campo, maximo in (("angulo", ANGULO_MAX), ("tono", TONO_MAX)):
        valor = dato.get(campo)
        if not isinstance(valor, str) or not valor.strip():
            motivos.append(f"'{campo}' debe ser un texto no vacío")
        elif len(valor.strip()) > maximo:
            motivos.append(f"'{campo}' supera {maximo} caracteres ({len(valor.strip())})")

    slides = dato.get("slides")
    if not isinstance(slides, list):
        return motivos + ["'slides' debe ser una lista"]

    vistos: list[int] = []
    # Cada elemento de slides: su número y sus fragmentos.
    for pos, s in enumerate(slides):
        # Un elemento que no es objeto no se puede revisar más.
        if not isinstance(s, dict):
            motivos.append(f"slides[{pos}] debe ser un objeto")
            continue
        numero = s.get("numero")
        # bool es subclase de int: se excluye para que true no cuente como slide 1.
        if not isinstance(numero, int) or isinstance(numero, bool):
            motivos.append(f"slides[{pos}].numero debe ser un entero")
            continue
        vistos.append(numero)

        frs = s.get("fragmentos")
        if not isinstance(frs, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in frs):
            motivos.append(f"slide {numero}: 'fragmentos' debe ser una lista de enteros")
            continue
        # Cantidad permitida de fragmentos por slide.
        if not MIN_FRAGMENTOS_POR_SLIDE <= len(frs) <= MAX_FRAGMENTOS_POR_SLIDE:
            motivos.append(
                f"slide {numero}: debe tener entre {MIN_FRAGMENTOS_POR_SLIDE} y {MAX_FRAGMENTOS_POR_SLIDE} fragmentos"
            )
        # Cada número debe existir en el índice.
        fuera = [i for i in frs if not 0 <= i < num_fragmentos]
        if fuera:
            motivos.append(f"slide {numero}: fragmentos inexistentes {fuera} (válidos: 0 a {num_fragmentos - 1})")

    # Debe haber un elemento por cada slide de la ficha, sin repetidos ni sobrantes.
    if sorted(vistos) != sorted(numeros_slide):
        motivos.append(f"'slides' debe cubrir exactamente los números {numeros_slide} (recibido {sorted(vistos)})")
    return motivos


async def generar_brief(cliente: ClienteLLM, entrada: dict, resolucion, fuente: FuenteCargada) -> Brief:
    """Pide el brief al estratega, lo valida y lo devuelve.

    Con fallback permitido: un run caído pesa más que mezclar familias de modelos; la
    respuesta dice qué modelo contestó (`Brief.modelo`) y queda registrado.
    Lanza AgenteError (salida truncada o inválida, fuente demasiado larga) o LLMError (cliente).
    """
    numeros = [s["numero"] for s in resolucion.ficha["slides"]]
    n_frag = len(fuente.fragmentos)
    mensajes = construir_mensajes(entrada, resolucion, fuente)

    dato, resp = await pedir_json(
        cliente,
        "estratega",
        mensajes,
        lambda d: validar_brief(d, numeros, n_frag),  # el validador conoce los slides y fragmentos de este run
        max_tokens=MAX_TOKENS_ESTRATEGA,
        permitir_fallback=True,
    )
    return Brief(
        angulo=dato["angulo"].strip(),
        tono=dato["tono"].strip(),
        # dict.fromkeys quita fragmentos repetidos dentro de un slide sin alterar el orden (no gasta tokens del redactor dos veces).
        fragmentos_por_slide={s["numero"]: tuple(dict.fromkeys(s["fragmentos"])) for s in dato["slides"]},
        modelo=resp.modelo,
        fallback=resp.fallback,
    )