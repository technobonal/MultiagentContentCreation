"""Registro en memoria de las ejecuciones (runs) y su buffer de eventos.

Cada ejecución guarda sus eventos ya validados, con seq consecutivo desde 1. El SSE lee de
ese buffer y se despierta con una Condition cuando llega un evento nuevo o la ejecución termina.
No hay base de datos: todo vive en la memoria del proceso (la app debe correr con UN solo worker).
"""

import asyncio
import logging
import re
import secrets
from collections.abc import Coroutine
from datetime import datetime
from enum import Enum
from functools import lru_cache

from app import config
from app.events.validador import comprobar_evento

log = logging.getLogger(__name__)


# Imágenes de un run (recortes de la fuente): referencia segura para una URL, tipos permitidos y topes de memoria.
REFERENCIA_IMAGEN = re.compile(r"[a-z0-9_-]{1,40}")
MIME_IMAGEN = ("image/jpeg", "image/png")
IMAGEN_MAX_BYTES = 2 * 1024 * 1024
IMAGENES_MAX_POR_RUN = 8


class EstadoRun(str, Enum):
    """Ciclo de vida de una ejecución."""

    EN_CURSO = "en_curso"  # el orquestador sigue emitiendo
    TERMINADA = "terminada"  # emitió run_finalizada y no hay más eventos
    FALLIDA = "fallida"  # un evento fue inválido o el orquestador falló


class EventoInvalido(Exception):
    """Un evento no cumple el contrato: la ejecución se corta con error visible."""

    def __init__(self, motivos: list[str]):
        super().__init__("; ".join(motivos))
        self.motivos = motivos  # los mismos motivos que viajan por SSE en evento_invalido


class LimiteDeRuns(Exception):
    """Ya hay el máximo de ejecuciones simultáneas en curso."""


class Ejecucion:
    """Una ejecución: su entrada, su resolución, su buffer de eventos y su estado."""

    def __init__(self, run_id: str, entrada: dict, resolucion, origen: str):
        self.run_id = run_id
        self.entrada = entrada  # entrada ya validada contra el esquema
        self.resolucion = resolucion  # plantilla y número de slides ya decididos
        self.origen = origen  # "real" o "grabado"; el servidor no lo reescribe después
        self.estado = EstadoRun.EN_CURSO
        self.eventos: list[dict] = []  # eventos válidos; el evento de seq N está en el índice N-1
        # Si falla: {"nombre": "evento_invalido" | "run_error", "datos": {...}} para el SSE.
        self.fallo: dict | None = None
        self._cond = asyncio.Condition()  # despierta a los lectores del SSE
        # Aprobación humana: el orquestador abre la espera, el endpoint registra la decisión y despierta al orquestador.
        self._esperando_decision = False
        self._decision = None  # la `Decision` registrada (aprobacion.py); solo se acepta una
        self._decision_lista = asyncio.Event()
        # Imágenes del run (recortes de la fuente) que el navegador pide por URL: referencia -> (bytes, tipo MIME).
        self._imagenes: dict[str, tuple[bytes, str]] = {}

    def guardar_imagen(self, referencia: str, datos: bytes, mime: str) -> None:
        """Guarda una imagen del run. Lanza ValueError si la referencia, el tipo o el tamaño no valen, o si ya hay demasiadas."""
        if not REFERENCIA_IMAGEN.fullmatch(referencia):
            raise ValueError(f"Referencia de imagen inválida: {referencia!r} (solo a-z, 0-9, _ y -, hasta 40).")
        if mime not in MIME_IMAGEN:
            raise ValueError(f"Tipo de imagen no permitido: {mime!r}.")
        if not datos or len(datos) > IMAGEN_MAX_BYTES:
            raise ValueError(f"La imagen debe pesar entre 1 byte y {IMAGEN_MAX_BYTES} bytes.")
        if referencia not in self._imagenes and len(self._imagenes) >= IMAGENES_MAX_POR_RUN:
            raise ValueError(f"Un run guarda como mucho {IMAGENES_MAX_POR_RUN} imágenes.")
        self._imagenes[referencia] = (datos, mime)

    def obtener_imagen(self, referencia: str) -> tuple[bytes, str] | None:
        """(bytes, MIME) de la imagen guardada, o None si no existe."""
        return self._imagenes.get(referencia)

    @property
    def esperando_decision(self) -> bool:
        """True mientras el run espera la decisión de una persona (el endpoint responde 409 si no)."""
        return self._esperando_decision

    def abrir_decision(self) -> None:
        """Abre la espera. Se llama ANTES de emitir `aprobacion_solicitada`, así nadie decide antes de tiempo."""
        self._esperando_decision = True

    def registrar_decision(self, decision) -> bool:
        """Guarda la decisión y despierta al orquestador. False si no se esperaba o ya había una (solo vale la primera)."""
        if not self._esperando_decision or self._decision is not None:
            return False
        self._decision = decision
        self._decision_lista.set()
        return True

    async def esperar_decision(self, timeout: float | None):
        """Espera la decisión hasta `timeout` segundos (None = sin límite). Devuelve None si venció sin decisión.

        Al salir, por decisión o por tiempo, la espera queda cerrada: una decisión tardía recibe 409.
        """
        try:
            await asyncio.wait_for(self._decision_lista.wait(), timeout)
            return self._decision
        except asyncio.TimeoutError:
            return None
        finally:
            self._esperando_decision = False

    async def emitir(self, agente: str, tipo: str, payload: dict, slide: int | None = None, causa: int | None = None) -> dict:
        """Arma el evento, lo valida contra el contrato y lo agrega al buffer.

        Un evento inválido NO entra al buffer: la ejecución pasa a FALLIDA con los motivos
        (el SSE los entrega como evento_invalido) y se lanza EventoInvalido.
        """
        evento = {
            "version": "0.1",
            "run_id": self.run_id,
            "seq": len(self.eventos) + 1,  # consecutivo, sin huecos
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "origen": self.origen,
            "agente": agente,
            "tipo": tipo,
            "payload": payload,
        }
        # slide y causa solo viajan en los eventos que los usan.
        if slide is not None:
            evento["slide"] = slide
        if causa is not None:
            evento["causa"] = causa
        motivos = comprobar_evento(evento)
        if motivos:  # contrato roto: error visible, nunca se silencia
            await self.terminar(
                EstadoRun.FALLIDA,
                {"nombre": "evento_invalido", "datos": {"seq": evento["seq"], "tipo": tipo, "motivos": motivos}},
            )
            raise EventoInvalido(motivos)
        async with self._cond:
            self.eventos.append(evento)
            self._cond.notify_all()  # avisa a los lectores que hay un evento nuevo
        return evento

    async def terminar(self, estado: EstadoRun, fallo: dict | None = None) -> None:
        """Cierra la ejecución (una sola vez) y despierta a los lectores."""
        async with self._cond:
            if self.estado != EstadoRun.EN_CURSO:  # ya estaba cerrada: no se pisa el primer resultado
                return
            self.estado = estado
            self.fallo = fallo
            self._cond.notify_all()

    async def cerrar(self) -> None:
        """Marca la ejecución como terminada con éxito."""
        await self.terminar(EstadoRun.TERMINADA)

    async def fallar(self, mensaje: str) -> None:
        """Marca la ejecución como fallida por un error inesperado (mensaje SSE run_error)."""
        await self.terminar(EstadoRun.FALLIDA, {"nombre": "run_error", "datos": {"motivos": [mensaje]}})

    async def esperar_cambio(self, indice: int, timeout: float) -> bool:
        """Espera hasta que haya un evento más allá de `indice` o la ejecución se cierre.

        Devuelve False si pasó el `timeout` sin cambios (el SSE envía entonces un latido).
        """
        async with self._cond:
            try:
                await asyncio.wait_for(
                    self._cond.wait_for(lambda: len(self.eventos) > indice or self.estado != EstadoRun.EN_CURSO),
                    timeout,
                )
            except asyncio.TimeoutError:  # nada nuevo en este intervalo
                return False
        return True


class RegistroRuns:
    """Todas las ejecuciones del proceso, con límites de ejecuciones simultáneas y conservadas."""

    def __init__(self, max_activos: int, max_conservados: int):
        self.max_activos = max_activos
        self.max_conservados = max_conservados
        self._runs: dict[str, Ejecucion] = {}  # en orden de creación
        self._tareas: set[asyncio.Task] = set()  # referencia fuerte: si no, el recolector las borra

    def _nuevo_id(self) -> str:
        """Genera un run_id `run_` + 8 hex (cumple ^run_[a-z0-9_]{3,40}$) que no esté en uso."""
        while True:  # un choque entre 4.300 millones de valores es casi imposible, pero se comprueba
            run_id = "run_" + secrets.token_hex(4)
            if run_id not in self._runs:
                return run_id

    def crear(self, entrada: dict, resolucion, origen: str) -> Ejecucion:
        """Registra una ejecución nueva. Lanza LimiteDeRuns si ya hay el máximo en curso."""
        activos = sum(1 for r in self._runs.values() if r.estado == EstadoRun.EN_CURSO)
        if activos >= self.max_activos:  # protege la cuota (más adelante cada run gasta LLM)
            raise LimiteDeRuns(f"ya hay {activos} ejecuciones en curso (máximo {self.max_activos})")
        ejecucion = Ejecucion(self._nuevo_id(), entrada, resolucion, origen)
        self._runs[ejecucion.run_id] = ejecucion
        self._podar()
        return ejecucion

    def _podar(self) -> None:
        """Descarta las ejecuciones terminadas más viejas por encima del máximo conservado."""
        terminadas = [rid for rid, r in self._runs.items() if r.estado != EstadoRun.EN_CURSO]
        exceso = len(terminadas) - self.max_conservados
        # Las más viejas están primero (el diccionario conserva el orden de creación).
        for rid in terminadas[: max(exceso, 0)]:
            del self._runs[rid]

    def obtener(self, run_id: str) -> Ejecucion | None:
        """Devuelve la ejecución con ese id, o None si no existe (o ya se descartó)."""
        return self._runs.get(run_id)

    def lanzar(self, corutina: Coroutine) -> asyncio.Task:
        """Lanza la corutina del orquestador y guarda la tarea hasta que termine."""
        tarea = asyncio.create_task(corutina)
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)  # se suelta sola al terminar
        return tarea

    async def cancelar_todo(self) -> None:
        """Cancela las tareas pendientes (apagado de la app) y espera a que acaben."""
        tareas = list(self._tareas)
        for tarea in tareas:  # cada tarea pendiente recibe la cancelación
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)


@lru_cache(maxsize=1)
def obtener_registro_runs() -> RegistroRuns:
    """Dependencia de FastAPI: el registro único del proceso (las pruebas la reemplazan)."""
    return RegistroRuns(config.MAX_RUNS_ACTIVOS, config.MAX_RUNS_CONSERVADOS)
