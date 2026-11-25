"""Redactor (paso 2): escribe los textos de UN slide y cita los hechos literales que usó.

Recibe el texto completo de los fragmentos que el estratega asignó a ese slide (no la
fuente entera). Devuelve los textos de los campos que normalmente escribe un LLM y los
hechos copiados de la fuente. El código verifica que cada hecho aparezca literal en esos
fragmentos y calcula su rango `inicio`/`fin` (ver verificar_hechos.py).

Si el slide no tiene campos para el redactor (solo imágenes o valores calculados), no se
llama al LLM: se devuelve un resultado vacío.

Reescritura (ciclo de corrección): `redactar_slide` acepta `correcciones`, una lista de
textos con lo que el revisor pidió cambiar. Van al final del mensaje de usuario, así el
prefijo fijo del prompt sigue reutilizándose en el caché.

Respuesta vacía o cortada: a veces el modelo devuelve el texto vacío o cortado (de forma
intermitente, en un slide cualquiera). `pedir_json` no lo reintenta porque repetir el mismo
pedido idéntico lo volvería a cortar; aquí se reintenta UNA vez con una temperatura algo mayor,
para que la segunda respuesta no sea una copia de la primera.

Citas no literales: mientras quedan reintentos, una cita que no aparece literal en los
fragmentos se rechaza y se le devuelve al modelo para que la corrija. En el ÚLTIMO intento ya
no se rechaza (`exigir_citas=False`): esa cita se descarta, se conserva el texto del slide y
queda un aviso en el log. No se inventa respaldo: el revisor de fidelidad verifica el texto del
slide por su cuenta contra los fragmentos. Los errores de estructura (campos, límites, JSON)
sí siguen cortando el run.

Orden del prompt (para el caché de Groq): prompt fijo primero, datos variables al final.
Para que el prefijo se reutilice, el orquestador debe llamar a los slides en SECUENCIA.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.agentes.cliente_llm import ClienteLLM
from app.agentes.comun import AgenteError, Validador, cargar_prompt, pedir_json
from app.agentes.estratega import Brief
from app.agentes.verificar_hechos import HechoUbicado, ubicar_hechos
from app.fuentes.cargador_fuente import FuenteCargada

log = logging.getLogger(__name__)

# Tokens de salida que se piden (y se reservan en el límite por minuto).
MAX_TOKENS_REDACTOR = 2000

# Reintentos de CONTENIDO del redactor (campo que se pasa del límite, cita no literal): el reintento le dice al modelo qué
# corregir. El último intento es el tolerante: descarta las citas que no sirven y RECORTA el campo que se pasa del límite
# (`recortar_a_limite`), así que un exceso ya no aborta el run. Con eso alcanza un reintento (cada uno cuesta ~1.500 tokens):
# en las pruebas con un PDF ni tres intentos evitaban que `cuerpo` saliera con 275 o 344 caracteres de 220.
REINTENTOS_CONTENIDO_REDACTOR = 1

# Un recorte por oración que deje menos de esta fracción del límite pierde demasiado: se prueba en una coma o un espacio.
RECORTE_MIN_FRACCION = 0.5

# Final de oración dentro de un campo: signo de cierre (con comilla o paréntesis opcional) seguido de un blanco o del final.
_FIN_ORACION = re.compile(r"[.!?…][\"')\]»”]?(?=\s|$)")

# Temperatura del primer intento y del reintento tras una respuesta vacía o cortada.
TEMPERATURA_REDACTOR = 0.2
TEMPERATURA_REINTENTO = 0.5

# Cuántas veces más se pide el slide si la respuesta llega vacía o cortada.
REINTENTOS_SALIDA_TRUNCADA = 1

# Límites de los hechos citados.
MAX_HECHOS = 6
HECHO_MAX_CHARS = 300

# Cuántos caracteres de una cita descartada se escriben en el log (para no inflarlo).
CITA_LOG_MAX_CHARS = 120


@dataclass(frozen=True)
class TextoSlide:
    """Resultado del redactor para un slide."""

    numero: int
    campos: dict[str, str]  # nombre de campo (sin llaves) -> texto
    hechos: tuple[HechoUbicado, ...]  # hechos verificados, con su rango en la fuente
    modelo: str  # modelo que realmente contestó ("" si no hubo llamada)
    fallback: bool


def campos_del_redactor(slide: dict) -> list[tuple[str, int]]:
    """Campos del slide que escribe el LLM: (nombre sin llaves, longitud máxima)."""
    campos = []
    # Solo los campos de texto cuyo valor viene del LLM (no imágenes ni valores calculados o dados por el usuario).
    for c in slide["campos"]:
        if c["tipo"] == "texto" and c["origen_valor"] == "llm":
            campos.append((c["nombre"].strip("{}"), c["longitud_max"]))
    return campos


def construir_mensajes(
    entrada: dict,
    brief: Brief,
    slide: dict,
    campos: list[tuple[str, int]],
    fragmentos: list,
    correcciones: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Arma los mensajes: prompt fijo (system) y datos variables del slide al final (user).

    `correcciones` (opcional) son los cambios que pidió el revisor; se añaden al final del
    mensaje de usuario para no alterar el prefijo reutilizable por el caché.
    """
    lista_campos = "\n".join(f"- {nombre} (máximo {maximo} caracteres)" for nombre, maximo in campos)
    # Cada fragmento va delimitado y con su número, para que el modelo cite del texto correcto.
    bloques = "\n\n".join(f"[Fragmento {f.indice}]\n{f.texto}" for f in fragmentos)
    usuario = (
        f"Ángulo: {brief.angulo}\n"
        f"Tono: {brief.tono}\n"
        f"Idioma de salida: {entrada['fuente']['idioma_salida']}\n"
        f"Slide {slide['numero']}, rol: {slide['rol']}\n"
        f"Campos a escribir:\n{lista_campos}\n\n"
        f"Fragmentos de la fuente:\n{bloques}"
    )
    # Reescritura: se agregan las correcciones al final, sin permitir hechos fuera de los fragmentos.
    if correcciones:
        lista = "\n".join(f"- {c}" for c in correcciones)
        usuario += (
            "\n\nCorrecciones requeridas (aplícalas al reescribir; "
            f"no uses hechos que no estén en los fragmentos):\n{lista}"
        )
    return [
        {"role": "system", "content": cargar_prompt("redactor")},
        {"role": "user", "content": usuario},
    ]


def recortar_a_limite(texto: str, maximo: int) -> str:
    """Recorta `texto` para que quepa en `maximo` caracteres sin inventar nada: siempre es un prefijo del original.

    Prefiere cortar al final de una oración; si eso deja menos de la mitad del límite, corta en la última coma,
    punto y coma o espacio y cierra con «…». Solo como último recurso corta en seco. Un texto que ya cabe no se toca.
    """
    texto = texto.strip()
    if len(texto) <= maximo:
        return texto
    minimo = int(maximo * RECORTE_MIN_FRACCION)
    # 1) Última oración completa que quepa.
    ventana = texto[: maximo + 1]
    finales = [m.end() for m in _FIN_ORACION.finditer(ventana) if m.end() <= maximo]
    if finales and finales[-1] >= minimo:
        return texto[: finales[-1]].strip()
    # 2) Última coma, punto y coma o espacio, dejando lugar para «…».
    ventana = texto[: maximo - 1]
    for separadores in (",;:", " "):
        corte = max(ventana.rfind(s) for s in separadores)
        if corte >= minimo:
            return texto[:corte].rstrip(" ,;:") + "…"
    # 3) Corte en seco.
    return texto[: maximo - 1].rstrip() + "…"


def validar_redaccion(
    dato: Any,
    campos: list[tuple[str, int]],
    fragmentos: list,
    exigir_citas: bool = True,
    exigir_longitud: bool | None = None,
) -> list[str]:
    """Comprueba el JSON del redactor y devuelve los motivos de rechazo (lista vacía = válido).

    `exigir_citas=True` rechaza las citas no literales o de más de HECHO_MAX_CHARS (así un reintento
    le pide al modelo que cite bien); con False se aceptan y `redactar_slide` las descarta.
    `exigir_longitud` (por defecto, igual que `exigir_citas`) rechaza el campo que se pasa de su
    límite; con False se acepta y `redactar_slide` lo recorta. Claves, tipos y cantidad de citas
    se exigen siempre.
    """
    if exigir_longitud is None:
        exigir_longitud = exigir_citas
    # Debe ser un objeto.
    if not isinstance(dato, dict):
        return ["la respuesta debe ser un objeto JSON"]
    motivos: list[str] = []

    textos = dato.get("campos")
    if not isinstance(textos, dict):
        motivos.append("'campos' debe ser un objeto")
    else:
        esperados = {nombre for nombre, _ in campos}
        # Deben estar exactamente los campos pedidos.
        if set(textos) != esperados:
            motivos.append(f"'campos' debe tener exactamente estas claves: {sorted(esperados)} (recibido {sorted(textos)})")
        # Cada campo pedido: texto no vacío y dentro de su límite.
        for nombre, maximo in campos:
            valor = textos.get(nombre)
            if valor is None:
                continue  # su ausencia ya se informó arriba
            if not isinstance(valor, str) or not valor.strip():
                motivos.append(f"el campo '{nombre}' debe ser un texto no vacío")
            # Sin exigir la longitud (último intento) el exceso no se rechaza: `redactar_slide` recorta el campo.
            elif len(valor.strip()) > maximo and exigir_longitud:
                motivos.append(f"el campo '{nombre}' supera {maximo} caracteres ({len(valor.strip())})")

    hechos = dato.get("hechos")
    if not isinstance(hechos, list) or not all(isinstance(h, str) for h in hechos):
        motivos.append("'hechos' debe ser una lista de textos")
        return motivos
    # Cantidad y longitud de las citas.
    if len(hechos) > MAX_HECHOS:
        motivos.append(f"'hechos' tiene {len(hechos)} citas y el máximo es {MAX_HECHOS}")
    # Modo tolerante (último intento): una cita demasiado larga tampoco aborta el run, `redactar_slide` la descarta.
    largos = [h for h in hechos if len(h) > HECHO_MAX_CHARS]
    if largos and exigir_citas:
        motivos.append(f"hay citas de más de {HECHO_MAX_CHARS} caracteres; usa citas más cortas")

    # Modo tolerante: no se rechaza por citas no literales (se descartarán al ubicarlas).
    if not exigir_citas:
        return motivos

    # Verificación literal contra los fragmentos del slide.
    _, faltan = ubicar_hechos(hechos, fragmentos)
    # Se muestran recortadas para no inflar el mensaje de corrección.
    for h in faltan:
        motivos.append(f"la cita «{h[:80]}» no aparece literal en los fragmentos; cópiala exactamente o quítala")
    return motivos


async def _pedir_redaccion(
    cliente: ClienteLLM,
    mensajes: list[dict[str, str]],
    validar: Validador,
    validar_ultimo: Validador | None = None,
) -> tuple[Any, Any]:
    """Pide la redacción al LLM y reintenta si la respuesta llega vacía o cortada.

    Solo se reintenta el código `salida_truncada`; cualquier otro error (JSON inválido tras sus
    reintentos, fallos del cliente) se propaga sin tocar. El reintento usa una temperatura mayor.
    `validar_ultimo` (opcional) es el validador tolerante que `pedir_json` aplica en el último
    intento de cada pedido. Devuelve (dato_validado, respuesta), igual que `pedir_json`.
    """
    # Intento inicial más los reintentos permitidos por salida vacía o cortada.
    for intento in range(REINTENTOS_SALIDA_TRUNCADA + 1):
        try:
            return await pedir_json(
                cliente,
                "redactor",
                mensajes,
                validar,
                max_tokens=MAX_TOKENS_REDACTOR,
                permitir_fallback=True,
                temperatura=TEMPERATURA_REDACTOR if intento == 0 else TEMPERATURA_REINTENTO,
                reintentos=REINTENTOS_CONTENIDO_REDACTOR,
                validar_ultimo=validar_ultimo,
            )
        except AgenteError as exc:
            # Otro tipo de fallo, o ya no quedan reintentos: se deja pasar el error tal cual.
            if exc.codigo != "salida_truncada" or intento == REINTENTOS_SALIDA_TRUNCADA:
                raise
            log.warning("Redactor: respuesta vacía o cortada; se reintenta (intento %d)", intento + 2)
    raise AssertionError("inalcanzable: el bucle siempre devuelve o lanza")  # pragma: no cover


async def redactar_slide(
    cliente: ClienteLLM,
    entrada: dict,
    resolucion,
    fuente: FuenteCargada,
    brief: Brief,
    numero: int,
    correcciones: tuple[str, ...] = (),
) -> TextoSlide:
    """Redacta el slide `numero` con los fragmentos que le asignó el estratega.

    `correcciones` (opcional) activa la reescritura: lo que el revisor pidió cambiar.
    Con fallback permitido (un run caído pesa más que mezclar familias; queda registrado en
    `TextoSlide.modelo`). Una respuesta vacía o cortada se reintenta una vez. Las citas no literales o
    demasiado largas NO provocan un reintento (cuesta ~1.500 tokens y nada aguas abajo usa las citas del
    redactor: el revisor verifica por su cuenta): se descartan con aviso en el log. Solo se reintenta por
    estructura o por un campo que se pasa del límite; si el exceso sigue, el campo se recorta.
    Lanza AgenteError (salida truncada o inválida) o LLMError (cliente).
    """
    slide = next(s for s in resolucion.ficha["slides"] if s["numero"] == numero)
    campos = campos_del_redactor(slide)
    # Sin campos para el LLM no se gasta una llamada.
    if not campos:
        return TextoSlide(numero, {}, (), "", False)

    # Fragmentos asignados a este slide, en el orden que dio el estratega.
    fragmentos = [fuente.fragmentos[i] for i in brief.fragmentos_por_slide[numero]]
    mensajes = construir_mensajes(entrada, brief, slide, campos, fragmentos, tuple(correcciones))

    # Primer intento: exige estructura y longitud, pero no reintenta por citas. Último: tolera también la longitud.
    dato, resp = await _pedir_redaccion(
        cliente,
        mensajes,
        lambda d: validar_redaccion(d, campos, fragmentos, exigir_citas=False, exigir_longitud=True),
        lambda d: validar_redaccion(d, campos, fragmentos, exigir_citas=False, exigir_longitud=False),
    )
    # Una cita de más de HECHO_MAX_CHARS se descarta sin ubicarla.
    largos = [h for h in dato["hechos"] if len(h) > HECHO_MAX_CHARS]
    ubicados, faltan = ubicar_hechos([h for h in dato["hechos"] if len(h) <= HECHO_MAX_CHARS], fragmentos)
    faltan = [*faltan, *largos]
    # Las citas que siguen sin ser literales se descartan; el texto del slide se conserva y queda constancia.
    if faltan:
        log.warning(
            "Redactor: slide %s, %d cita(s) no literal(es) o demasiado larga(s) descartada(s): %s",
            numero, len(faltan), [h[:CITA_LOG_MAX_CHARS] for h in faltan],
        )
    # Un campo que sigue pasándose del límite tras el reintento se recorta (prefijo del original, nunca texto nuevo).
    textos = {}
    for nombre, maximo in campos:
        original = dato["campos"][nombre].strip()
        textos[nombre] = recortar_a_limite(original, maximo)
        if textos[nombre] != original:
            log.warning(
                "Redactor: slide %s, campo '%s' recortado de %d a %d caracteres (límite %d) tras el reintento",
                numero, nombre, len(original), len(textos[nombre]), maximo,
            )
    return TextoSlide(
        numero=numero,
        campos=textos,
        hechos=tuple(ubicados),
        modelo=resp.modelo,
        fallback=resp.fallback,
    )