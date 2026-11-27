"""Semáforo de aprobación: verde o rojo por slide, calculado por código a partir de los eventos. Nunca por un LLM.

Un slide está en rojo si tiene un hallazgo mayor o bloqueante abierto, una frase «no verificada» (sin cita
literal), texto del redactor sin ningún veredicto sobre su versión actual, una edición a mano (no se vuelve
a verificar) o una alerta del asesor sobre su texto actual. Las alertas se acumulan: volver a preguntarle y que
no repita una no la quita (si no, bastaría con insistir). Solo hay visto bueno si todo está en verde. Verde significa que pasó estos controles, no que el
texto sea verdad: el revisor puede equivocarse.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.runs.sello import GRAVEDADES_QUE_BLOQUEAN, hallazgos_abiertos


def informe(eventos: Sequence[Mapping[str, Any]], ediciones: Sequence[Any] = ()) -> dict:
    """{"visto_bueno", "generales": [motivo], "slides": [{"slide", "color", "motivos", "avisos"}], "asesor"}.

    "asesor" es None si no se le consultó; si no, lo que informó la última consulta.

    `ediciones` son las de una decisión todavía no emitida (con .slide y .campo).
    """
    slides: set[int] = set()
    del_redactor: set[int] = set()
    ultima_escritura: dict[int, int] = {}
    verificaciones: list[Mapping[str, Any]] = []
    abiertos_por_id: dict[str, Mapping[str, Any]] = {}
    editados: list[tuple[int, str]] = [(e.slide, e.campo) for e in ediciones]
    generales: list[str] = []
    consultas: list[Mapping[str, Any]] = []

    for e in eventos:
        tipo, slide, payload = e.get("tipo"), e.get("slide"), e.get("payload", {})
        if isinstance(slide, int):
            slides.add(slide)
        if tipo == "run_iniciada" and payload.get("verificacion") == "sin_fuente_verificada":
            generales.append("No hay una fuente verificada: nada se comprobó contra un documento.")
        elif tipo == "texto_propuesto":
            del_redactor.add(slide)
        elif tipo == "escribir_texto":
            ultima_escritura[slide] = e["seq"]
        elif tipo == "verificacion_fidelidad":
            verificaciones.append(e)
        elif tipo == "hallazgo_abierto":
            abiertos_por_id[payload["hallazgo_id"]] = e
        elif tipo == "editada":
            editados.append((slide, payload["campo"]))
        elif tipo == "asesoria":
            consultas.append(e)

    if not del_redactor:
        generales.append("No hay textos del redactor que se hayan podido verificar.")

    motivos: dict[int, list[str]] = {n: [] for n in slides}
    avisos: dict[int, list[str]] = {n: [] for n in slides}

    # Solo valen los veredictos posteriores a la última escritura: los de un texto ya reescrito no cuentan.
    vigentes: dict[int, list[Mapping[str, Any]]] = {}
    for v in verificaciones:
        if v["seq"] > ultima_escritura.get(v.get("slide"), 0):
            vigentes.setdefault(v.get("slide"), []).append(v["payload"])
    for n in sorted(del_redactor):
        motivos.setdefault(n, [])
        if not vigentes.get(n):
            motivos[n].append("Su texto actual no tiene ningún veredicto del revisor.")
        for v in vigentes.get(n, []):
            if v["veredicto"] == "no_verificada":
                motivos[n].append(f"No verificada (sin cita literal de la fuente): «{v['afirmacion']}»")

    for ident in hallazgos_abiertos(eventos):
        e = abiertos_por_id.get(ident)
        if e is None:
            continue
        p, slide = e["payload"], e.get("slide")
        texto = f"Hallazgo {ident} ({p['gravedad']}): {p['evidencia']}"
        if p["gravedad"] not in GRAVEDADES_QUE_BLOQUEAN:
            avisos.setdefault(slide, []).append(texto)
        elif isinstance(slide, int):
            motivos.setdefault(slide, []).append(texto)
        else:
            generales.append(texto)

    for consulta in consultas:
        for alerta in consulta["payload"]["alertas"]:
            n = alerta["slide"]
            motivo = f"Alerta del asesor: «{alerta['frase']}» — {alerta['explicacion']} (sugiere {alerta['sugerencia']})"
            # Deja de valer solo si el texto del slide se volvió a escribir después del consejo.
            if consulta["seq"] > ultima_escritura.get(n, 0) and motivo not in motivos.setdefault(n, []):
                motivos[n].append(motivo)

    for slide, campo in editados:
        motivos.setdefault(slide, []).append(f"Editaste «{campo}» a mano: no se vuelve a verificar contra la fuente.")

    filas = [
        {"slide": n, "color": "rojo" if motivos.get(n) else "verde",
         "motivos": motivos.get(n, []), "avisos": avisos.get(n, [])}
        for n in sorted(set(motivos) | {s for s in avisos if isinstance(s, int)})
    ]
    return {
        "visto_bueno": not generales and all(f["color"] == "verde" for f in filas),
        "generales": generales,
        "slides": filas,
        "asesor": None if not consultas else {
            "consultas": len(consultas),
            **{k: consultas[-1]["payload"][k] for k in ("modelo", "frases_revisadas", "frases_totales")},
        },
    }
