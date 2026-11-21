"""Ciclo de corrección del revisor: revisar → corregir → re-revisar, con tope de rondas.

No conoce a `Ejecucion` ni a los agentes concretos: todo entra por inyección (`revisar`,
`corregir`, `emitir`). Así se prueba sin LLM ni servidor, y cada pieza se puede envolver
como nodo de LangGraph sin reescribirla.

Ronda = una revisión. Con `max_rondas=3` hay la revisión inicial y hasta 2 reintentos de
corrección, que coincide con "escala a humano tras el segundo reintento" del contrato
`hallazgo_corregido` y con el tope de 3 rondas del roadmap.

Detección de "sin cambios": `corregir` devuelve el MISMO objeto de estado cuando no pudo corregir
(por ejemplo, un responsable sin corrección automática). Si ningún grupo cambió el estado, el ciclo
escala de inmediato (motivo "sin_cambios") en lugar de gastar una re-revisión idéntica; los grupos
que no cambiaron nada tampoco cuentan como intento ni amplían el alcance de la re-revisión.

El ciclo NO emite `run_finalizada`: devuelve un `ResultadoCiclo` y el orquestador decide.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

MAX_RONDAS = 3  # revisión inicial + 2 reintentos
GRAVEDADES_CORREGIBLES = ("bloqueante", "mayor")  # las demás se reportan pero no abren corrección
RESPONSABLES_GLOBALES = ("estratega",)  # reasignar fragmentos afecta a todo: se re-revisa todo
_ORDEN_GRAVEDAD = {"bloqueante": 0, "mayor": 1}  # los bloqueantes se corrigen primero
_MAX_HALLAZGOS = 999  # el contrato limita hallazgo_id a ^h[0-9]{1,3}$


@dataclass(frozen=True)
class Revision:
    """Resultado de una pasada del revisor.

    `hallazgos`: lista de {"slide", "payload"} SIN `hallazgo_id` (el ciclo lo asigna).
    `verificaciones`: lista de {"slide", "payload"} de `verificacion_fidelidad`.
    """

    hallazgos: list[dict] = field(default_factory=list)
    verificaciones: list[dict] = field(default_factory=list)


@dataclass
class HallazgoAbierto:
    """Un hallazgo que sigue abierto, con el seq de su `hallazgo_abierto` original."""

    hallazgo_id: str
    slide: int | None
    payload: dict  # ya incluye hallazgo_id
    seq_abierto: int  # va en `causa` de hallazgo_corregido
    intentos: int = 0  # cuántas veces se intentó corregir


@dataclass
class ResultadoCiclo:
    """Cómo terminó el ciclo, para que el orquestador cierre la ejecución."""

    estado_final: str  # "aprobado" | "requiere_humano"
    motivo: str  # "sin_pendientes" | "tope_de_rondas" | "sin_progreso" | "sin_cambios"
    rondas: int  # revisiones realizadas
    estado: Any  # el estado de trabajo después de las correcciones
    pendientes: list[HallazgoAbierto]  # lo que sigue abierto al terminar
    corregidos: list[str]  # ids cerrados como corregidos


Revisar = Callable[[Any, "set[int] | None"], Awaitable[Revision]]
Corregir = Callable[[str | None, int | None, list[HallazgoAbierto], Any], Awaitable[Any]]
Emitir = Callable[..., Awaitable[dict]]


def _clave(hallazgo: dict) -> tuple:
    """Identidad de un hallazgo entre rondas: (slide, dimensión, evidencia)."""
    payload = hallazgo["payload"]
    return (hallazgo.get("slide"), payload.get("dimension"), str(payload.get("evidencia")))


def _en_alcance(slide: int | None, alcance: set[int] | None) -> bool:
    """True si la revisión cubrió ese slide (sin alcance o sin slide se considera cubierto)."""
    return alcance is None or slide is None or slide in alcance


async def ejecutar_ciclo(
    estado: Any,
    *,
    revisar: Revisar,
    corregir: Corregir,
    emitir: Emitir,
    max_rondas: int = MAX_RONDAS,
    gravedades: tuple[str, ...] = GRAVEDADES_CORREGIBLES,
    cortar_sin_progreso: bool = False,
) -> ResultadoCiclo:
    """Ejecuta revisar → corregir → re-revisar hasta aprobar o agotar el tope.

    - `revisar(estado, alcance)`: `alcance` es None (todo) o el conjunto de slides a re-revisar.
    - `corregir(responsable, slide, hallazgos, estado)`: un llamado por (responsable, slide),
      con todos los hallazgos de ese grupo; devuelve el estado nuevo.
    - `emitir(agente=, tipo=, payload=, slide=, causa=)`: es `Ejecucion.emitir`; devuelve el evento.
    - `cortar_sin_progreso`: si es True, escala en cuanto una re-revisión no cierra ningún hallazgo.
    """
    # Un tope menor que 1 no tiene sentido: ni siquiera habría revisión inicial.
    if max_rondas < 1:
        raise ValueError("max_rondas debe ser al menos 1")

    abiertos: dict[tuple, HallazgoAbierto] = {}  # hallazgos vigentes por clave
    corregidos: list[str] = []
    contador = 0  # numeración h1, h2, ... estable durante todo el ciclo
    alcance: set[int] | None = None  # la primera revisión cubre todo
    ronda = 0

    while True:  # una vuelta por ronda de revisión
        ronda += 1
        revision = await revisar(estado, alcance)

        # Cada afirmación verificada se emite tal cual la entrega el revisor.
        for verificacion in revision.verificaciones:
            await emitir(
                agente="revisor",
                tipo="verificacion_fidelidad",
                slide=verificacion.get("slide"),
                payload=verificacion["payload"],
            )

        vistos: set[tuple] = set()  # claves presentes en esta revisión
        for hallazgo in revision.hallazgos:  # concilia lo nuevo con lo ya abierto
            clave = _clave(hallazgo)
            # Duplicado dentro de la misma revisión: se trata una sola vez.
            if clave in vistos:
                continue
            vistos.add(clave)
            existente = abiertos.get(clave)
            if existente is None:  # hallazgo nuevo: se abre con id propio
                contador += 1
                if contador > _MAX_HALLAZGOS:
                    raise RuntimeError("se superó el máximo de hallazgos que admite el contrato (h999)")
                payload = {**hallazgo["payload"], "hallazgo_id": f"h{contador}"}
                evento = await emitir(
                    agente="revisor", tipo="hallazgo_abierto", slide=hallazgo.get("slide"), payload=payload
                )
                abiertos[clave] = HallazgoAbierto(
                    hallazgo_id=payload["hallazgo_id"],
                    slide=hallazgo.get("slide"),
                    payload=payload,
                    seq_abierto=evento["seq"],
                )
            elif existente.intentos > 0:  # ya se intentó corregir y sigue ahí
                await emitir(
                    agente="revisor",
                    tipo="hallazgo_corregido",
                    slide=existente.slide,
                    causa=existente.seq_abierto,
                    payload={
                        "hallazgo_id": existente.hallazgo_id,
                        "resultado": "persiste",
                        "reevaluacion": f"Sigue presente tras el intento {existente.intentos} de corrección (ronda {ronda}).",
                    },
                )

        resueltos_en_ronda = 0
        for clave in list(abiertos):  # cierra lo que ya no aparece en lo que se revisó
            pendiente = abiertos[clave]
            # Visto en esta revisión, o en un slide que no se re-revisó: no se puede dar por cerrado.
            if clave in vistos or not _en_alcance(pendiente.slide, alcance):
                continue
            await emitir(
                agente="revisor",
                tipo="hallazgo_corregido",
                slide=pendiente.slide,
                causa=pendiente.seq_abierto,
                payload={
                    "hallazgo_id": pendiente.hallazgo_id,
                    "resultado": "corregido",
                    "reevaluacion": f"Ya no aparece en la revisión de la ronda {ronda}.",
                },
            )
            corregidos.append(pendiente.hallazgo_id)
            del abiertos[clave]
            resueltos_en_ronda += 1

        # Solo los hallazgos de gravedad corregible bloquean la aprobación; bloqueantes primero.
        corregibles = sorted(
            (h for h in abiertos.values() if h.payload.get("gravedad") in gravedades),
            key=lambda h: _ORDEN_GRAVEDAD.get(h.payload.get("gravedad"), 9),
        )

        def _resultado(estado_final: str, motivo: str) -> ResultadoCiclo:
            """Arma el resultado con lo que sigue abierto en este momento."""
            return ResultadoCiclo(estado_final, motivo, ronda, estado, list(abiertos.values()), corregidos)

        # Nada corregible pendiente: aprobado (los menores quedan listados en `pendientes`).
        if not corregibles:
            return _resultado("aprobado", "sin_pendientes")
        # Se agotó el tope de rondas con pendientes: escala a humano.
        if ronda >= max_rondas:
            return _resultado("requiere_humano", "tope_de_rondas")
        # Opcional: una re-revisión sin ningún cierre no justifica gastar otra ronda de LLM.
        if cortar_sin_progreso and ronda > 1 and resueltos_en_ronda == 0:
            return _resultado("requiere_humano", "sin_progreso")

        # Agrupa por (responsable, slide): un solo llamado por grupo, en orden de gravedad.
        grupos: dict[tuple, list[HallazgoAbierto]] = defaultdict(list)
        for pendiente in corregibles:
            grupos[(pendiente.payload.get("responsable"), pendiente.slide)].append(pendiente)

        slides_tocados: set[int] = set()
        revision_total = False  # True si alguna corrección afecta a todo el carrusel
        hubo_cambio = False  # True si algún corrector devolvió un estado distinto del que recibió
        for (responsable, slide), lista in grupos.items():  # un llamado de corrección por grupo
            nuevo = await corregir(responsable, slide, lista, estado)
            # Mismo objeto = el corrector no pudo (o no supo) cambiar nada: no cuenta como intento.
            if nuevo is estado:
                continue
            estado = nuevo
            hubo_cambio = True
            for pendiente in lista:  # cuenta el intento de cada hallazgo del grupo corregido
                pendiente.intentos += 1
            # Sin slide, o responsable global: la siguiente revisión debe cubrir todo.
            if slide is None or responsable in RESPONSABLES_GLOBALES:
                revision_total = True
            else:
                slides_tocados.add(slide)
        # Ningún corrector cambió nada: re-revisar daría lo mismo y gastaría LLM, se escala ya.
        if not hubo_cambio:
            return _resultado("requiere_humano", "sin_cambios")
        alcance = None if revision_total else slides_tocados