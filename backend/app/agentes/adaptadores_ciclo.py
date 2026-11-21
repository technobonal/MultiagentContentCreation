"""Adaptadores entre el ciclo de corrección y los agentes reales (tanda 8B).

`ejecutar_ciclo` pide dos funciones: `revisar(estado, alcance)` y `corregir(responsable, slide,
hallazgos, estado)`. Aquí se construyen con los agentes de verdad:

  - `RevisorCarrusel`: revisor de código (todo, es barato y determinista) + revisor de fidelidad
    (LLM, solo los slides en `alcance`). Las funciones del revisor se inyectan para no depender de
    dónde vivan (`revisar_codigo`, `revisar_fidelidad`, `con_ids`).
  - `CorrectorCarrusel`: según el `responsable` del hallazgo. Hoy solo corrige `redactor` (reescribe
    el slide con las correcciones del revisor). `director_arte` es determinista (el mismo texto y kit
    dan los mismos eventos) y `estratega` implica reasignar fragmentos de todo el carrusel: ambos
    devuelven el MISMO estado (objeto idéntico) para que el ciclo pueda detectar que no hubo cambio.

El estado es inmutable: cada corrección devuelve un `EstadoCarrusel` nuevo.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from app.agentes.ciclo_correccion import HallazgoAbierto, Revision
from app.agentes.comun import AgenteError
from app.agentes.estratega import Brief
from app.agentes.redactor import TextoSlide, redactar_slide

log = logging.getLogger(__name__)

# Límites de las correcciones que se le pasan al redactor (para no inflar el prompt).
MAX_CORRECCIONES = 5
CORRECCION_MAX_CHARS = 400
EVIDENCIA_MAX_CHARS = 200


@dataclass(frozen=True, eq=False)
class EstadoCarrusel:
    """Lo que el ciclo corrige: el brief y los textos por slide.

    `eq=False` a propósito: la identidad del objeto indica si una corrección cambió algo.
    """

    textos: dict[int, TextoSlide]  # número de slide -> redacción vigente
    brief: Brief


def texto_de_correccion(hallazgo: HallazgoAbierto) -> str:
    """Convierte un hallazgo en la instrucción de corrección que lee el redactor."""
    p = hallazgo.payload
    evidencia = str(p.get("evidencia", ""))[:EVIDENCIA_MAX_CHARS]
    texto = f"[{p.get('gravedad')}] {p.get('explicacion')} Acción: {p.get('accion')} (evidencia: {evidencia})"
    return texto[:CORRECCION_MAX_CHARS]


class RevisorCarrusel:
    """Función `revisar` del ciclo: junta hallazgos de código y de fidelidad en una `Revision`."""

    def __init__(
        self,
        cliente: Any,
        resolucion: Any,
        kit: dict,
        entrada: dict,
        fuente: Any,
        *,
        revisar_codigo: Callable[..., list],
        revisar_fidelidad: Callable[..., Any],
        con_ids: Callable[..., list[dict]],
        pedir: Callable[..., Any] | None = None,
    ):
        self.cliente = cliente
        self.resolucion = resolucion
        self.kit = kit
        self.entrada = entrada
        self.fuente = fuente
        self._revisar_codigo = revisar_codigo
        self._revisar_fidelidad = revisar_fidelidad
        self._con_ids = con_ids
        self.pedir = pedir  # función de pedido al LLM (las pruebas la simulan)
        # Últimas verificaciones por slide: el orquestador las usa para el sello final.
        self.verificaciones: dict[int, list[dict]] = {}

    def todas_las_verificaciones(self) -> list[dict]:
        """Verificaciones vigentes de todos los slides, ordenadas por número de slide."""
        salida: list[dict] = []
        for numero in sorted(self.verificaciones):  # un bloque por slide, en orden
            salida.extend(self.verificaciones[numero])
        return salida

    async def __call__(self, estado: EstadoCarrusel, alcance: set[int] | None) -> Revision:
        """Revisa el carrusel; con `alcance` la fidelidad solo mira esos slides."""
        # Los revisores reciben listas de TextoSlide ordenadas por número de slide (no diccionarios).
        todos = [estado.textos[n] for n in sorted(estado.textos)]
        # El código es determinista y barato: se revisa siempre todo el carrusel.
        hallazgos = self._con_ids(self._revisar_codigo(self.resolucion, self.kit, todos, self.entrada))

        # La fidelidad cuesta LLM: solo los slides del alcance (o todos si no hay alcance).
        subconjunto = [t for t in todos if alcance is None or t.numero in alcance]
        eventos: list[dict] = []
        # Sin slides que revisar no se gasta ninguna llamada.
        if subconjunto:
            resultado = await self._revisar_fidelidad(
                self.cliente, estado.brief, self.fuente, subconjunto, pedir=self.pedir
            )
            hallazgos = hallazgos + self._con_ids(resultado.hallazgos)
            eventos = [a.a_evento() for a in resultado.afirmaciones]

        # Se reemplazan las verificaciones de los slides revisados; las de los demás se conservan.
        for texto in subconjunto:  # cada slide revisado parte de cero
            self.verificaciones[texto.numero] = []
        for evento in eventos:  # cada afirmación va al bloque de su slide
            self.verificaciones.setdefault(evento["slide"], []).append(evento)
        return Revision(hallazgos=hallazgos, verificaciones=eventos)


class CorrectorCarrusel:
    """Función `corregir` del ciclo: despacha cada grupo de hallazgos al agente responsable."""

    def __init__(
        self,
        cliente: Any,
        entrada: dict,
        resolucion: Any,
        fuente: Any,
        *,
        redactar: Callable[..., Any] = redactar_slide,
    ):
        self.cliente = cliente
        self.entrada = entrada
        self.resolucion = resolucion
        self.fuente = fuente
        self._redactar = redactar  # se inyecta para probar sin LLM

    async def __call__(
        self, responsable: str | None, slide: int | None, hallazgos: list[HallazgoAbierto], estado: EstadoCarrusel
    ) -> EstadoCarrusel:
        """Corrige lo que se pueda y devuelve el estado nuevo (o el mismo objeto si no hubo cambio)."""
        # Solo el redactor corrige hoy, y solo si el hallazgo apunta a un slide concreto.
        if responsable == "redactor" and slide is not None:
            return await self._corregir_redactor(slide, hallazgos, estado)
        log.info("Sin corrección automática para responsable=%s slide=%s", responsable, slide)
        return estado

    async def _corregir_redactor(
        self, slide: int, hallazgos: list[HallazgoAbierto], estado: EstadoCarrusel
    ) -> EstadoCarrusel:
        """Reescribe el slide con las correcciones del revisor; si el redactor falla, deja el estado igual."""
        correcciones = tuple(texto_de_correccion(h) for h in hallazgos[:MAX_CORRECCIONES])
        try:
            nuevo = await self._redactar(
                self.cliente, self.entrada, self.resolucion, self.fuente, estado.brief, slide,
                correcciones=correcciones,
            )
        except AgenteError as exc:  # salida inválida o truncada: el hallazgo persistirá y el ciclo decide
            log.warning("El redactor no pudo reescribir el slide %s: %s", slide, exc)
            return estado
        # Estado nuevo con una copia del diccionario: el anterior no se toca.
        return replace(estado, textos={**estado.textos, slide: nuevo})