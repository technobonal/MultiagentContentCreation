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
  6. aprobacion_solicitada (8F): estado de la revisión, hallazgos abiertos y sello. Se emite SIEMPRE,
     justo antes del cierre. Todavía no existe el endpoint de aprobación humana, así que el run no
     espera: termina solo con run_finalizada (la espera real, HITL, queda para una fase posterior).
  7. run_finalizada: estado final, referencia al fact ledger y sello. El sello lo calcula el código
     a partir de las verificaciones VIGENTES, nunca el LLM. Atribución, licencia y sello los dibuja
     el lienzo como campos calculados: aquí no se escriben con escribir_texto.

Errores: AgenteError y LLMError cortan la ejecución con su mensaje visible (`run_error`); un evento
inválido ya deja la ejecución FALLIDA con los motivos; la cancelación avisa y se propaga.
Tope global (8F): si el run dura más de `RUN_TIMEOUT_SEG`, se corta con un `run_error` de tiempo máximo.

Medición de tiempos (tanda 10A, solo observa; no cambia el flujo ni los eventos):
- `_Medidor` cronometra cada etapa (estratega, cada slide del redactor, director de arte, cada
  pasada del revisor y del corrector) y, si el cliente LLM expone `metricas()`, atribuye a cada etapa
  sus peticiones a Groq, la espera por cupo y los tokens.
- Al terminar el run (también si falló o venció el tope) se escribe un resumen en el log INFO. Si el
  tope global cortó el run, la etapa que estaba en curso aparece marcada como INTERRUMPIDA: ahí está
  el cuello de botella.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from app import config
from app.agentes.adaptadores_ciclo import CorrectorCarrusel, EstadoCarrusel, RevisorCarrusel
from app.agentes.ciclo_correccion import ejecutar_ciclo as _ejecutar_ciclo
from app.agentes.cliente_llm import ClienteLLM, LLMError
from app.agentes.comun import AgenteError
from app.agentes.director_arte import componer_carrusel as _componer_carrusel
from app.agentes.director_arte import componer_slide as _componer_slide
from app.agentes.estratega import generar_brief as _generar_brief
from app.agentes.foto_de_fuente import huecos_de_ficha
from app.agentes.foto_de_fuente import preparar_fotos as _preparar_fotos
from app.agentes.redactor import TextoSlide
from app.agentes.redactor import redactar_slide as _redactar_slide
from app.agentes.revisor_codigo import con_ids as _con_ids
from app.agentes.revisor_codigo import revisar_codigo as _revisar_codigo
from app.agentes.revisor_fidelidad import revisar_fidelidad as _revisar_fidelidad
from app.fuentes.cargador_fuente import FuenteCargada
from app.runs.registro import Ejecucion, EventoInvalido
from app.runs.sello import calcular_sello, decidir_estado_final, hallazgos_abiertos, referencia_fact_ledger

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
    preparar_fotos: Callable[..., Any] = _preparar_fotos
    dormir: Callable[..., Any] = asyncio.sleep  # inyectable: las pruebas no esperan de verdad
    ciclo: Callable[..., Any] = _ejecutar_ciclo


# ---------------------------------------------------------------------------
# Medición de tiempos por etapa (tanda 10A)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Etapa:
    """Resultado de cronometrar una etapa del run."""

    nombre: str
    seg: float  # duración de la etapa (reloj de pared)
    ok: bool  # False si la etapa terminó por excepción o cancelación (por ejemplo el tope global)
    llamadas: int  # peticiones a Groq hechas durante la etapa (0 si el cliente no mide)
    espera_cupo_seg: float  # segundos dormidos esperando cupo del limitador durante la etapa
    tokens: int  # tokens consumidos durante la etapa


class _Medidor:
    """Cronometra las etapas de UN run y arma el resumen final para el log.

    Medir nunca debe romper un run: cualquier fallo al leer las métricas del cliente se ignora.
    `reloj` se inyecta en las pruebas.
    """

    def __init__(self, run_id: str, cliente: Any, reloj: Callable[[], float] = time.monotonic):
        self.run_id = run_id
        self.cliente = cliente
        self.reloj = reloj
        self.etapas: list[_Etapa] = []  # etapas terminadas, en orden de cierre
        self._inicio = reloj()  # instante en que empezó el run (para el total)

    def _foto(self) -> dict:
        """Foto de los contadores del cliente LLM; vacía si el cliente no tiene `metricas()` o falla."""
        leer = getattr(self.cliente, "metricas", None)
        # Los clientes falsos de las pruebas no miden: sin `metricas()` no hay nada que atribuir.
        if not callable(leer):
            return {}
        try:
            return dict(leer())
        except Exception:  # noqa: BLE001 - medir no puede tumbar el run
            return {}

    @contextlib.contextmanager
    def etapa(self, nombre: str) -> Iterator[None]:
        """Cronometra el bloque `with`. Registra la etapa aunque el bloque falle o se cancele."""
        antes = self._foto()
        t0 = self.reloj()
        ok = False  # solo pasa a True si el bloque terminó sin excepción
        try:
            yield
            ok = True
        finally:
            despues = self._foto()
            self.etapas.append(
                _Etapa(
                    nombre=nombre,
                    seg=self.reloj() - t0,
                    ok=ok,
                    # Diferencia de los contadores acumulados: lo que consumió ESTA etapa.
                    llamadas=int(despues.get("llamadas_red", 0) - antes.get("llamadas_red", 0)),
                    espera_cupo_seg=float(despues.get("espera_cupo_seg", 0.0) - antes.get("espera_cupo_seg", 0.0)),
                    tokens=int(despues.get("tokens", 0) - antes.get("tokens", 0)),
                )
            )

    def resumen(self) -> str:
        """Texto multilínea con el tiempo total y una línea por etapa."""
        lineas = [f"Resumen de tiempos del run {self.run_id}: total {self.reloj() - self._inicio:.1f} s"]
        # Una línea por etapa, en el orden en que terminaron.
        for e in self.etapas:
            marca = "" if e.ok else "  <-- INTERRUMPIDA"
            lineas.append(
                f"  {e.nombre:<22} {e.seg:7.1f} s  llamadas={e.llamadas}  "
                f"cupo={e.espera_cupo_seg:.1f} s  tokens={e.tokens}{marca}"
            )
        return "\n".join(lineas)


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


async def _colocar_fotos(ejecucion: Ejecucion, fuente: FuenteCargada, agentes: Agentes) -> None:
    """Coloca en los huecos de imagen de la plantilla fotos recortadas de la fuente (PDF), una distinta por hueco.

    Es opcional y nunca tumba el run: sin licencia liberada (`FOTOS_LICENCIA`), sin huecos en la plantilla, sin fotos
    que sirvan o ante cualquier falla local, el carrusel sale igual, solo con texto. La licencia bloqueada por defecto
    evita incluso el trabajo de recortar. Un hueco sin foto simplemente queda oculto.
    """
    licencia = config.FOTOS_LICENCIA
    if not licencia:
        return
    if not 2 <= len(licencia) <= 120:  # el contrato exige de 2 a 120 caracteres: no se arriesga un evento inválido
        log.warning("FOTOS_LICENCIA debe tener entre 2 y 120 caracteres; no se colocan fotos")
        return
    huecos = huecos_de_ficha(ejecucion.resolucion.ficha)
    if not huecos:
        return
    try:
        fotos = await agentes.preparar_fotos(fuente, huecos)
    except Exception as exc:  # las fotos son opcionales: se registra y se sigue sin ellas
        log.warning("No se pudieron preparar las fotos de la fuente (%s): %s", type(exc).__name__, exc)
        return
    colocadas = 0
    for hueco in huecos:  # en orden de slide, así el lienzo las ve colocarse de la primera a la última
        foto = fotos.get(hueco.campo)
        if foto is None:
            continue
        if config.FOTOS_PAUSA_SEG > 0:
            await agentes.dormir(config.FOTOS_PAUSA_SEG)  # cada foto con su momento: el lienzo anima de a un evento
        referencia = f"foto-{hueco.slide}"
        try:
            ejecucion.guardar_imagen(referencia, foto.datos, foto.mime)
        except ValueError as exc:  # una imagen que el run no acepta no impide las demás
            log.warning("No se guardó la foto del slide %s: %s", hueco.slide, exc)
            continue
        await ejecucion.emitir(
            agente="director_arte", tipo="colocar_imagen", slide=hueco.slide,
            payload={"campo": hueco.campo, "referencia": referencia, "licencia": licencia, "texto_alternativo": foto.texto_alternativo},
        )
        colocadas += 1
    # También después de la última: el revisor puede responder en menos de lo que dura la escena y la cortaría.
    if colocadas and config.FOTOS_PAUSA_SEG > 0:
        await agentes.dormir(config.FOTOS_PAUSA_SEG)


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


def _medir_llamable(medidor: _Medidor, base: str, llamable: Callable[..., Any]) -> Callable[..., Any]:
    """Envuelve una corutina-llamable del ciclo (revisor o corrector) para cronometrar cada llamada.

    Pasa los argumentos tal cual (`*args, **kwargs`) y devuelve lo mismo que el original, así que
    el ciclo no nota la diferencia. Cada llamada es una etapa con nombre `base_1`, `base_2`, ...
    """
    contador = {"n": 0}  # cuántas veces se llamó (para numerar las etapas)

    async def medida(*args: Any, **kwargs: Any) -> Any:
        """Cronometra una llamada al revisor o al corrector y devuelve su resultado intacto."""
        contador["n"] += 1
        with medidor.etapa(f"{base}_{contador['n']}"):
            return await llamable(*args, **kwargs)

    return medida


@dataclass(frozen=True)
class _Cierre:
    """Lo que `_correr` deja listo para `_finalizar`: el estado y el sello ya calculados por código."""

    estado_final: str
    sello: dict


async def _correr(
    ejecucion: Ejecucion, fuente: FuenteCargada, cliente: ClienteLLM, kit: dict, agentes: Agentes,
    medidor: _Medidor | None = None, esperar_aprobacion: bool = False,
) -> _Cierre:
    """Todo el flujo de los agentes, de run_iniciada a aprobacion_solicitada (este incluido).

    Con `esperar_aprobacion` abre la espera de la decisión humana ANTES de emitir `aprobacion_solicitada`
    (así nadie decide antes de tiempo). El cierre del run lo hace `_finalizar`, fuera del tope de tiempo de los agentes.
    """
    entrada = ejecucion.entrada
    resolucion = ejecucion.resolucion
    # Sin medidor externo (por ejemplo, una prueba que llama a `_correr` directo) se crea uno local.
    medidor = medidor or _Medidor(ejecucion.run_id, cliente)

    await ejecucion.emitir(agente="sistema", tipo="run_iniciada", payload=_payload_run_iniciada(ejecucion))
    await ejecucion.emitir(agente="sistema", tipo="fuente_indexada", payload=_payload_fuente_indexada(fuente))

    with medidor.etapa("estratega"):
        brief = await agentes.generar_brief(cliente, entrada, resolucion, fuente)
    await ejecucion.emitir(agente="estratega", tipo="brief_emitido", payload=brief.payload_evento(resolucion))
    await ejecucion.emitir(agente="director_arte", tipo="plantilla_elegida", payload=_payload_plantilla(resolucion))

    # El redactor trabaja los slides EN SECUENCIA para reutilizar el prefijo fijo del prompt (caché de Groq).
    textos: dict[int, TextoSlide] = {}
    for slide in resolucion.ficha["slides"]:
        numero = slide["numero"]
        # Cada slide es su propia etapa: así se ve cuál redacción tarda más o reintenta.
        with medidor.etapa(f"redactor_slide_{numero}"):
            texto = await agentes.redactar(cliente, entrada, resolucion, fuente, brief, numero)
        textos[numero] = texto
        await _emitir_textos_propuestos(ejecucion, texto)

    # El director de arte compone todo el carrusel con los textos ya redactados.
    with medidor.etapa("director_arte"):
        await _emitir_arte(ejecucion, agentes.componer_carrusel(resolucion, kit, textos))
    with medidor.etapa("fotos"):
        await _colocar_fotos(ejecucion, fuente, agentes)

    # Ciclo de corrección con el revisor real (código + fidelidad) y el corrector envuelto.
    revisor = RevisorCarrusel(
        cliente, resolucion, kit, entrada, fuente,
        revisar_codigo=agentes.revisar_codigo, revisar_fidelidad=agentes.revisar_fidelidad, con_ids=agentes.con_ids,
    )
    corrector = CorrectorCarrusel(cliente, entrada, resolucion, fuente, redactar=agentes.redactar)
    # Se cronometra cada pasada del revisor y del corrector dentro del ciclo (el ciclo solo ve llamables).
    revisar_medido = _medir_llamable(medidor, "revisor", revisor)
    corregir_medido = _medir_llamable(medidor, "corrector", _crear_corrector(ejecucion, corrector, kit, agentes))
    resultado = await agentes.ciclo(
        EstadoCarrusel(textos, brief),
        revisar=revisar_medido,
        corregir=corregir_medido,
        emitir=ejecucion.emitir,
    )

    # Sello: solo con las verificaciones vigentes (si un slide se re-revisó, cuentan las últimas).
    sello = calcular_sello(revisor.todas_las_verificaciones())
    # Si el ciclo escaló, requiere_humano; si no, depende de los hallazgos que sigan abiertos.
    estado_final = decidir_estado_final(
        ejecucion.eventos, escalado=(resultado.estado_final == "requiere_humano")
    )

    # Se pide la aprobación con el mismo estado y sello del cierre.
    if esperar_aprobacion:
        ejecucion.abrir_decision()
    await ejecucion.emitir(
        agente="sistema", tipo="aprobacion_solicitada",
        payload={
            "estado_revision": estado_final,
            "hallazgos_abiertos": len(hallazgos_abiertos(ejecucion.eventos)),
            "sello": sello,
        },
    )
    return _Cierre(estado_final, sello)


async def _finalizar(ejecucion: Ejecucion, cierre: _Cierre, esperar_aprobacion: bool, timeout_seg: float) -> None:
    """Cierra el run: con aprobación humana espera la decisión, emite sus eventos y después `run_finalizada`.

    Orden: [editada]* → aprobada → run_finalizada. Si nadie decide en `timeout_seg` (0 o menos = sin límite),
    el run termina igual con estado `requiere_humano`. Con bloqueantes abiertos la persona puede aprobar, pero el
    estado final no cambia: el sello cubre lo que escribió el modelo, no las ediciones de la persona.
    """
    estado_final = cierre.estado_final
    if esperar_aprobacion:
        decision = await ejecucion.esperar_decision(timeout_seg if timeout_seg > 0 else None)
        if decision is None:
            log.warning("El run %s no recibió decisión en %s s: queda en requiere_humano", ejecucion.run_id, timeout_seg)
            estado_final = "requiere_humano"
        else:
            for ed in decision.ediciones:
                await ejecucion.emitir(
                    agente="humano", tipo="editada", slide=ed.slide,
                    payload={"campo": ed.campo, "texto_antes": ed.texto_antes, "texto_despues": ed.texto_despues},
                )
            payload = {"decision": "aprobada"}
            if decision.comentario:
                payload["comentario"] = decision.comentario
            await ejecucion.emitir(agente="humano", tipo="aprobada", payload=payload)
    await ejecucion.emitir(
        agente="sistema", tipo="run_finalizada",
        payload={
            "estado_final": estado_final,
            "fact_ledger_ref": referencia_fact_ledger(ejecucion.run_id),
            "sello": cierre.sello,
        },
    )
    await ejecucion.cerrar()


async def ejecutar_run_real(
    ejecucion: Ejecucion,
    fuente: FuenteCargada,
    cliente: ClienteLLM,
    kit: dict,
    agentes: Agentes | None = None,
    timeout_seg: float | None = None,
    esperar_aprobacion: bool | None = None,
    aprobacion_timeout_seg: float | None = None,
) -> None:
    """Ejecuta el flujo real de una ejecución y cierra la `Ejecucion` (terminada o fallida).

    `cliente` se construye una sola vez al arrancar el servidor; `kit` es el kit de marca ya
    cargado; `agentes` solo se pasa en las pruebas (por defecto, los agentes reales).
    `timeout_seg` es el tope del trabajo de los agentes; sin valor se usa config.RUN_TIMEOUT_SEG (0 o menos = sin tope).
    `esperar_aprobacion` (sin valor, config.APROBACION_HUMANA) hace que el run espere la decisión de una persona
    hasta `aprobacion_timeout_seg` (sin valor, config.APROBACION_TIMEOUT_SEG); esa espera NO cuenta para `timeout_seg`.
    Al terminar, sea cual sea el desenlace, deja en el log el resumen de tiempos por etapa.
    """
    agentes = agentes or Agentes()
    tope = config.RUN_TIMEOUT_SEG if timeout_seg is None else timeout_seg
    esperar = config.APROBACION_HUMANA if esperar_aprobacion is None else esperar_aprobacion
    espera_max = config.APROBACION_TIMEOUT_SEG if aprobacion_timeout_seg is None else aprobacion_timeout_seg
    # El medidor se crea aquí (y no dentro de `_correr`) para poder imprimir el resumen aunque el run falle.
    medidor = _Medidor(ejecucion.run_id, cliente)
    # El límite se guarda en una variable para poder preguntarle después si fue él quien venció.
    limite = asyncio.timeout(tope if tope > 0 else None)
    try:
        async with limite:
            cierre = await _correr(ejecucion, fuente, cliente, kit, agentes, medidor, esperar)
        # Fuera del tope de los agentes: esperar a una persona no debe agotar el tiempo del run.
        await _finalizar(ejecucion, cierre, esperar, espera_max)
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
    except TimeoutError:
        # Solo es el tope global si venció nuestro límite; un TimeoutError de otro origen es un fallo inesperado.
        if limite.expired():
            log.warning("El run %s superó el tope de %s s", ejecucion.run_id, tope)
            await ejecucion.fallar(f"La ejecución superó el tiempo máximo ({tope:g} s) y se detuvo.")
        else:
            log.exception("Timeout inesperado en %s", ejecucion.run_id)
            await ejecucion.fallar(
                "Error inesperado del orquestador (TimeoutError); el detalle está en el registro del servidor."
            )
    except Exception as exc:  # cualquier fallo inesperado: visible, pero sin filtrar detalles al cliente
        log.exception("Fallo inesperado en %s", ejecucion.run_id)
        await ejecucion.fallar(
            f"Error inesperado del orquestador ({type(exc).__name__}); el detalle está en el registro del servidor."
        )
    finally:
        # Siempre se deja el resumen de tiempos (éxito, error, tope o cancelación): es el dato que buscamos.
        log.info("%s", medidor.resumen())