"""Cálculo por código del sello de revisión, de los hallazgos abiertos y del estado final de un run.

Todo sale de los EVENTOS ya emitidos (verificacion_fidelidad, hallazgo_abierto,
hallazgo_corregido), nunca del LLM. Son funciones puras: reciben la lista de eventos
en el orden en que se emitieron y devuelven datos simples, así se prueban sin red.

Reglas (contracts/common.schema.json y events/*.schema.json):
- Sello: cuenta afirmaciones FACTUALES distintas; el último veredicto de cada una manda.
  `opinion_cta` / `no_aplica` quedan fuera del total. `no_verificada` entra en el total,
  pero no cuenta como respaldada (igual que `parcialmente_respaldada`).
- Hallazgo abierto: el que tiene un `hallazgo_abierto` y no un `hallazgo_corregido`
  con resultado "corregido". Un "persiste" lo mantiene abierto.
- Estado final: ninguna pieza con un bloqueante (o un mayor) abierto sale como aprobada.
"""

from collections.abc import Iterable, Mapping
from typing import Any

# Un evento es el sobre completo (con "tipo", "slide", "payload", ...), ya como diccionario.
Evento = Mapping[str, Any]

# Gravedades que, si siguen abiertas al final, obligan a pasar por una persona.
GRAVEDADES_QUE_BLOQUEAN = frozenset({"bloqueante", "mayor"})


def _payload(evento: Evento) -> Mapping[str, Any]:
    """Devuelve el payload del evento, o un diccionario vacío si falta o no es un objeto."""
    payload = evento.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def calcular_sello(eventos: Iterable[Evento]) -> dict[str, int]:
    """Calcula el sello "N de M afirmaciones respaldadas".

    Acepta eventos completos (con "tipo") o las entradas {"slide", "payload"} que entrega
    `RevisorCarrusel.todas_las_verificaciones()`. En el orquestador conviene pasar estas
    últimas (las vigentes): si un slide se re-revisa y una afirmación desaparece, el
    historial de eventos aún la conserva y inflaría el total.

    Debe venir en orden de emisión: si una afirmación se reverifica (mismo `afirmacion_id`
    en el mismo slide), la última entrada reemplaza a la anterior.
    """
    # Último (clasificacion, veredicto) por afirmación; la clave incluye el slide.
    ultimo: dict[tuple[Any, str], tuple[Any, Any]] = {}
    # Se recorren todas las entradas y solo importan las de verificación de fidelidad.
    for evento in eventos:
        tipo = evento.get("tipo")
        # Un evento de otro tipo no entra en el sello (las entradas sin "tipo" sí se aceptan).
        if tipo is not None and tipo != "verificacion_fidelidad":
            continue
        payload = _payload(evento)
        afirmacion_id = payload.get("afirmacion_id")
        # Sin id no se puede saber qué afirmación es: se ignora.
        if not afirmacion_id:
            continue
        ultimo[(evento.get("slide"), afirmacion_id)] = (
            payload.get("clasificacion"),
            payload.get("veredicto"),
        )

    # Solo cuentan las factuales; no_aplica (opinión o CTA) queda fuera del total.
    veredictos = [
        veredicto
        for clasificacion, veredicto in ultimo.values()
        if clasificacion == "factual" and veredicto != "no_aplica"
    ]
    return {
        "afirmaciones_respaldadas": sum(1 for v in veredictos if v == "respaldada"),
        "afirmaciones_totales": len(veredictos),
    }


def hallazgos_abiertos(eventos: Iterable[Evento]) -> dict[str, Any]:
    """Devuelve {hallazgo_id: gravedad} de los hallazgos que siguen abiertos.

    Un hallazgo se cierra solo con un `hallazgo_corregido` de resultado "corregido";
    con "persiste" sigue abierto.
    """
    abiertos: dict[str, Any] = {}
    # Se aplican los eventos en orden: abrir añade, corregir quita.
    for evento in eventos:
        tipo = evento.get("tipo")
        payload = _payload(evento)
        hallazgo_id = payload.get("hallazgo_id")
        # Sin id no hay forma de seguirle la pista al hallazgo.
        if not hallazgo_id:
            continue
        if tipo == "hallazgo_abierto":
            abiertos[hallazgo_id] = payload.get("gravedad")
        elif tipo == "hallazgo_corregido" and payload.get("resultado") == "corregido":
            abiertos.pop(hallazgo_id, None)
    return abiertos


def decidir_estado_final(eventos: Iterable[Evento], escalado: bool = False) -> str:
    """Decide el `estado_final` del run: aprobada, aprobada_con_advertencias o requiere_humano.

    `escalado` es True cuando el ciclo de corrección se rindió (por ejemplo, sin_cambios
    o reintentos agotados); eso siempre pide a una persona, aunque no queden hallazgos.
    """
    # El ciclo ya decidió que no puede resolverlo solo.
    if escalado:
        return "requiere_humano"

    gravedades = set(hallazgos_abiertos(eventos).values())
    # Un bloqueante o un mayor abierto impiden aprobar.
    if gravedades & GRAVEDADES_QUE_BLOQUEAN:
        return "requiere_humano"
    # Solo quedan menores (o gravedades desconocidas): sale con advertencias.
    if gravedades:
        return "aprobada_con_advertencias"
    return "aprobada"


def referencia_fact_ledger(run_id: str) -> str:
    """Referencia al fact ledger del run (sus eventos verificacion_fidelidad).

    Mantiene la convención que ya usa el guion de relleno: "<run_id>/fact_ledger".
    """
    return f"{run_id}/fact_ledger"