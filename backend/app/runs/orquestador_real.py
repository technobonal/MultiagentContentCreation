"""Orquestador real (paso 2): estratega → redactor → director de arte → ciclo de corrección → sello.

Una corutina por ejecución que emite los eventos al buffer de su `Ejecucion`. El orquestador de
relleno (`orquestador.py`) no se toca. Orden de emisión:

  1. run_iniciada (verificacion "verificada") y fuente_indexada (huella de la fuente exacta).
  2. brief_emitido (estratega) y plantilla_elegida (ya resuelta en `resolucion`, sin LLM).
  3. texto_propuesto por campo, slide por slide y EN SECUENCIA (así se reutiliza el caché de Groq).
  4. colocar_fondo y escribir_texto de todo el carrusel (director de arte, determinista).
  5. Ciclo de corrección: el ciclo emite verificacion_fidelidad, hallazgo_abierto y hallazgo_corregido.
     Cuando el redactor reescribe un slide, aquí se emite texto_propuesto con `causa` igual al seq
     del hallazgo y se vuelven a emitir los escribir_texto de ESE slide (sin repetir el fondo).
  6. run_finalizada: estado final, referencia al fact ledger y sello. El sello lo calcula el código
     a partir de las verificaciones VIGENTES, nunca el LLM. Atribución, licencia y sello los dibuja
     el lienzo como campos calculados: aquí no se escriben con escribir_texto.

Errores: AgenteError y LLMError cortan la ejecución con su mensaje visible (`run_error`); un evento
inválido ya deja la ejecución FALLIDA con los motivos; la cancelación avisa y se propaga.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agentes.adaptadores_ciclo import CorrectorCarrusel, EstadoCarrusel, RevisorCarrusel
from app.agentes.ciclo_correccion import ejecutar_ciclo as _ejecutar_ciclo
from app.agentes.cliente_llm import ClienteLLM, LLMError
from app.agentes.comun import AgenteError
from app.agentes.director_arte import componer_carrusel as _componer_carrusel
from app.agentes.director_arte import componer_slide as _componer_slide
from app.agentes.estratega import generar_brief as _generar_brief
from app.agentes.redactor import TextoSlide
from app.agentes.redactor import redactar_slide as _redactar_slide
from app.agentes.revisor_codigo import con_ids as _con_ids
from app.agentes.revisor_codigo import revisar_codigo as _revisar_codigo
from app.agentes.revisor_fidelidad import revisar_fidelidad as _revisar_fidelidad
from app.fuentes.cargador_fuente import FuenteCargada
from app.runs.registro import Ejecucion, EventoInvalido
from app.runs.sello import calcular_sello, decidir_estado_final, referencia_fact_ledger

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Agentes:
    """Las piezas que usa el orquestador. Por defecto son las reales; las pruebas pasan falsas."""

    generar_brief: Callable[..., Any] = _generar_brief
    redactar: Callable[..., Any] = _redactar_slide
    revisar_codigo: Callable[..., Any] = _revisar_codigo
    revisar_fidelidad: Callable[..., Any] = _revisar_fidelidad
    con_ids: Callable[..., Any] = _con_ids
    componer_carrusel: Callable[..., Any] = _componer_carrusel
    componer_slide: Callable[..., Any] = _componer_slide
    ciclo: Callable[..., Any] = _ejecutar_ciclo


def _payload_run_iniciada(ejecucion: Ejecucion) -> dict:
    """Payload de run_iniciada: resumen de la entrada y datos de atribución de la fuente."""
    entrada = ejecucion.entrada
    fuente = entrada["fuente"]
    return {
        "entrada_ref": ejecucion.run_id,  # la entrada vive en memoria: su identificador es el run_id
        "plataforma": entrada["destino"]["red"],
        "idioma_salida": fuente["idioma_salida"],
        "num_slides": ejecucion.resolucion.num_slides,
        "verificacion": "verificada",  # la fuente se cargó, se indexó y tiene huella sha256
        "fuente": {"tipo": fuente["tipo"], "atribucion": fuente["atribucion"], "licencia": fuente["licencia"]},
    }


def _payload_fuente_indexada(fuente: FuenteCargada) -> dict:
    """Payload de fuente_indexada: datos mínimos de la indexación (nunca el texto de la fuente)."""
    return {
        "num_fragmentos": len(fuente.fragmentos),
        "num_caracteres": fuente.caracteres,
        "sha256": fuente.sha256,
    }


def _payload_plantilla(resolucion: Any) -> dict:
    """Payload de plantilla_elegida con lo ya resuelto (el director de arte aún no elige con LLM)."""
    fijo = resolucion.modo_plantilla == "fijo"
    return {
        "plantilla_id": resolucion.plantilla_id,
        "modo": resolucion.modo_plantilla,
        "motivo": (
            "Se respetó la plantilla fijada por el usuario"
            if fijo
            else "Plantilla compatible del catálogo (resolución determinista, sin LLM)"
        ),
        "confianza": 1.0,
    }


async def _emitir_textos_propuestos(ejecucion: Ejecucion, texto: TextoSlide, causa: int | None = None) -> None:
    """Emite un texto_propuesto por cada campo que redactó el redactor para ese slide."""
    # Un evento por campo, en el orden en que llegó la redacción.
    for campo, valor in texto.campos.items():
        await ejecucion.emitir(
            agente="redactor", tipo="texto_propuesto", slide=texto.numero, causa=causa,
            payload={"campo": campo, "texto": valor},
        )


async def _emitir_arte(ejecucion: Ejecucion, eventos: list, solo_texto: bool = False) -> None:
    """Emite los EventoArte del director de arte; con `solo_texto` se omite el fondo (reescrituras)."""
    for evento in eventos:  # el director de arte ya los entrega en orden
        # En una reescritura el fondo no cambia: solo se vuelven a escribir los textos.
        if solo_texto and evento.tipo != "escribir_texto":
            continue
        await ejecucion.emitir(agente=evento.agente, tipo=evento.tipo, payload=evento.payload, slide=evento.slide)


def _crear_corrector(
    ejecucion: Ejecucion, corrector: CorrectorCarrusel, kit: dict, agentes: Agentes,
) -> Callable[..., Any]:
    """Envuelve al corrector del ciclo para emitir los eventos de cada reescritura.

    Si el corrector no cambió nada devuelve el MISMO estado (el ciclo lo usa para detectar
    "sin cambios") y no se emite nada.
    """
    ficha = ejecucion.resolucion.ficha

    async def corregir(responsable: str | None, slide: int | None, hallazgos: list, estado: EstadoCarrusel):
        """Corrige un grupo de hallazgos y, si el slide cambió, deja constancia en los eventos."""
        nuevo = await corrector(responsable, slide, hallazgos, estado)
        # Sin cambio de estado, o sin slide concreto: no hay nada que emitir.
        if nuevo is estado or slide is None:
            return nuevo
        texto = nuevo.textos.get(slide)
        # Solo se emite si el texto de ese slide es realmente otro.
        if texto is None or texto is estado.textos.get(slide):
            return nuevo
        # `causa` apunta al hallazgo_abierto más grave del grupo (el ciclo los entrega ordenados).
        await _emitir_textos_propuestos(ejecucion, texto, causa=hallazgos[0].seq_abierto)
        slide_ficha = next(s for s in ficha["slides"] if s["numero"] == slide)
        await _emitir_arte(ejecucion, agentes.componer_slide(slide_ficha, kit, texto), solo_texto=True)
        return nuevo

    return corregir


async def _correr(
    ejecucion: Ejecucion, fuente: FuenteCargada, cliente: ClienteLLM, kit: dict, agentes: Agentes,
) -> None:
    """Todo el flujo de una ejecución real, de run_iniciada a run_finalizada."""
    entrada = ejecucion.entrada
    resolucion = ejecucion.resolucion

    await ejecucion.emitir(agente="sistema", tipo="run_iniciada", payload=_payload_run_iniciada(ejecucion))
    await ejecucion.emitir(agente="sistema", tipo="fuente_indexada", payload=_payload_fuente_indexada(fuente))

    brief = await agentes.generar_brief(cliente, entrada, resolucion, fuente)
    await ejecucion.emitir(agente="estratega", tipo="brief_emitido", payload=brief.payload_evento(resolucion))
    await ejecucion.emitir(agente="director_arte", tipo="plantilla_elegida", payload=_payload_plantilla(resolucion))

    # El redactor trabaja los slides EN SECUENCIA para reutilizar el prefijo fijo del prompt (caché de Groq).
    textos: dict[int, TextoSlide] = {}
    for slide in resolucion.ficha["slides"]:
        numero = slide["numero"]
        texto = await agentes.redactar(cliente, entrada, resolucion, fuente, brief, numero)
        textos[numero] = texto
        await _emitir_textos_propuestos(ejecucion, texto)

    # El director de arte compone todo el carrusel con los textos ya redactados.
    await _emitir_arte(ejecucion, agentes.componer_carrusel(resolucion, kit, textos))

    # Ciclo de corrección con el revisor real (código + fidelidad) y el corrector envuelto.
    revisor = RevisorCarrusel(
        cliente, resolucion, kit, entrada, fuente,
        revisar_codigo=agentes.revisar_codigo, revisar_fidelidad=agentes.revisar_fidelidad, con_ids=agentes.con_ids,
    )
    corrector = CorrectorCarrusel(cliente, entrada, resolucion, fuente, redactar=agentes.redactar)
    resultado = await agentes.ciclo(
        EstadoCarrusel(textos, brief),
        revisar=revisor,
        corregir=_crear_corrector(ejecucion, corrector, kit, agentes),
        emitir=ejecucion.emitir,
    )

    # Sello: solo con las verificaciones vigentes (si un slide se re-revisó, cuentan las últimas).
    sello = calcular_sello(revisor.todas_las_verificaciones())
    # Si el ciclo escaló, requiere_humano; si no, depende de los hallazgos que sigan abiertos.
    estado_final = decidir_estado_final(
        ejecucion.eventos, escalado=(resultado.estado_final == "requiere_humano")
    )
    await ejecucion.emitir(
        agente="sistema", tipo="run_finalizada",
        payload={
            "estado_final": estado_final,
            "fact_ledger_ref": referencia_fact_ledger(ejecucion.run_id),
            "sello": sello,
        },
    )
    await ejecucion.cerrar()


async def ejecutar_run_real(
    ejecucion: Ejecucion,
    fuente: FuenteCargada,
    cliente: ClienteLLM,
    kit: dict,
    agentes: Agentes | None = None,
) -> None:
    """Ejecuta el flujo real de una ejecución y cierra la `Ejecucion` (terminada o fallida).

    `cliente` se construye una sola vez al arrancar el servidor; `kit` es el kit de marca ya
    cargado; `agentes` solo se pasa en las pruebas (por defecto, los agentes reales).
    """
    agentes = agentes or Agentes()
    try:
        await _correr(ejecucion, fuente, cliente, kit, agentes)
    except EventoInvalido:
        # La Ejecucion ya quedó FALLIDA con los motivos; no hay nada más que hacer.
        log.error("Evento inválido en %s: la ejecución se cortó", ejecucion.run_id)
    except asyncio.CancelledError:
        # Apagado del servidor: se avisa a los lectores y se deja propagar la cancelación.
        await ejecucion.fallar("La ejecución se canceló porque el servidor se apagó.")
        raise
    except (AgenteError, LLMError) as exc:
        # Fallo esperable de un agente o del cliente LLM: se muestra su mensaje, que es apto para el usuario.
        log.warning("Fallo de agente en %s (%s): %s", ejecucion.run_id, getattr(exc, "codigo", "?"), exc)
        await ejecucion.fallar(getattr(exc, "mensaje", None) or str(exc))
    except Exception as exc:  # cualquier fallo inesperado: visible, pero sin filtrar detalles al cliente
        log.exception("Fallo inesperado en %s", ejecucion.run_id)
        await ejecucion.fallar(
            f"Error inesperado del orquestador ({type(exc).__name__}); el detalle está en el registro del servidor."
        )