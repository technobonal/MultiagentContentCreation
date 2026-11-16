"""Genera la secuencia grabada b5_cifra_inventada.json a partir de la fuente.

La secuencia es la "escena de la demo" (B.5): el lienzo se construye, el revisor
atrapa una cifra inventada (el Daily Scrum "dura 30 minutos" cuando la fuente dice
15), la corrección se ve en pantalla y el humano edita y aprueba.

Las posiciones de las citas y la huella de la fuente se CALCULAN aquí desde el
texto real, nunca se escriben a mano, para que el validador pueda comprobarlas.

Uso:  python contracts/recordings/gen_grabacion.py
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Carpeta de este script: de ahí salen la fuente y el JSON de salida.
AQUI = Path(__file__).resolve().parent
FUENTE_PATH = AQUI / "b5_cifra_inventada.fuente.txt"
SALIDA_PATH = AQUI / "b5_cifra_inventada.json"

# Texto de la fuente congelada; todas las citas deben ser literales de este texto.
FUENTE = FUENTE_PATH.read_text(encoding="utf-8")

# Zona horaria de São Paulo y momento base de la grabación (los eventos suman 2 s cada uno).
ZONA = timezone(timedelta(hours=-3))
INICIO = datetime(2026, 11, 11, 20, 0, 0, tzinfo=ZONA)

RUN_ID = "run_b5_cifra_inventada"
PLANTILLA_ID = "ig_carrusel_pasos_oscuro_6slides"

# Fondo que coloca el Director de arte: distinto del azul base de la plantilla (#0F172A)
# para que la transición de color se note en vivo. Se aplica a todos los slides que
# se dibujan, porque el lienzo pinta el fondo del slide activo.
COLOR_FONDO = "#1E1B4B"

# Contador de secuencia y lista de eventos que se van acumulando.
_eventos = []


def cita(fragmento: str) -> dict:
    """Devuelve la cita literal de `fragmento` con su posición exacta en la fuente.

    Lanza ValueError si el fragmento no está en la fuente (así nunca se graba una
    cita inventada).
    """
    inicio = FUENTE.index(fragmento)  # falla si no es literal
    return {"fragmento": fragmento, "inicio": inicio, "fin": inicio + len(fragmento)}


def emitir(agente: str, tipo: str, payload: dict, slide: int | None = None, causa: int | None = None) -> int:
    """Agrega un evento a la secuencia y devuelve su `seq`.

    Completa el sobre común (versión, run_id, seq, timestamp, origen grabado).
    `slide` y `causa` solo se incluyen cuando el evento los necesita.
    """
    seq = len(_eventos) + 1  # secuencia creciente desde 1
    evento = {
        "version": "0.1",
        "run_id": RUN_ID,
        "seq": seq,
        "timestamp": (INICIO + timedelta(seconds=2 * (seq - 1))).isoformat(),
        "origen": "grabado",
        "agente": agente,
        "tipo": tipo,
    }
    if slide is not None:  # solo los eventos ligados a un slide lo llevan
        evento["slide"] = slide
    if causa is not None:  # solo las correcciones y reevaluaciones lo llevan
        evento["causa"] = causa
    evento["payload"] = payload
    _eventos.append(evento)
    return seq


def construir() -> dict:
    """Arma la secuencia completa (24 eventos) y devuelve el documento de la grabación."""
    # Fragmentos literales de la fuente que se usan como evidencia.
    frag_daily = "El Daily Scrum dura como máximo 15 minutos."
    frag_retro = "La Retrospective dura 45 minutos para un Sprint de una semana."

    # Textos del pack: el del slide 3 nace con la cifra inventada (30) y luego se corrige.
    titulo = "Los eventos de Scrum y cuánto dura cada uno"
    daily_mal = "El Daily Scrum dura 30 minutos y se hace todos los días a la misma hora."
    daily_bien = "El Daily Scrum dura como máximo 15 minutos y se hace todos los días a la misma hora."
    retro = "La Retrospective dura 45 minutos para un Sprint de una semana."

    # Número de fragmentos = párrafos separados por línea en blanco.
    num_fragmentos = len([p for p in FUENTE.split("\n\n") if p.strip()])

    # --- Ciclo de vida y estrategia ---
    emitir("sistema", "run_iniciada", {
        "entrada_ref": FUENTE_PATH.name,
        "plataforma": "instagram",
        "idioma_salida": "es",
        "num_slides": 6,
        "verificacion": "verificada",
        "fuente": {
            "tipo": "documento",
            "atribucion": "Texto de ejemplo escrito para pruebas",
            "licencia": "Propio (uso libre en el proyecto)",
        },
    })
    emitir("sistema", "fuente_indexada", {
        "num_fragmentos": num_fragmentos,
        "num_caracteres": len(FUENTE),
        "sha256": hashlib.sha256(FUENTE.encode("utf-8")).hexdigest(),
    })
    emitir("estratega", "brief_emitido", {
        "angulo": "Guía rápida de los eventos de Scrum con sus tiempos",
        "tono": "Claro, directo y técnico",
        "num_slides": 6,
        "tipo_mensaje": "lista_de_pasos",
        "roles": ["gancho", "segundo_gancho", "desarrollo", "desarrollo", "cierre", "fuentes"],
    })
    emitir("director_arte", "plantilla_elegida", {
        "plantilla_id": PLANTILLA_ID,
        "modo": "auto",
        "motivo": "Es la plantilla de lista de pasos del MVP y admite 6 slides",
        "confianza": 0.92,
    })

    # --- El redactor propone los textos (el del slide 3 lleva la cifra inventada) ---
    emitir("redactor", "texto_propuesto", {"campo": "titulo", "texto": titulo}, slide=1)
    emitir("redactor", "texto_propuesto", {"campo": "cuerpo", "texto": daily_mal}, slide=3)
    emitir("redactor", "texto_propuesto", {"campo": "cuerpo", "texto": retro}, slide=4)

    # --- El Director de arte coloca el fondo de cada slide que va a dibujar ---
    # Mismo color en los tres: la transición se ve una vez (evento 8) y se mantiene.
    fondo = {"fondo": {"tipo": "color", "valor": COLOR_FONDO}}
    for slide_fondo in (1, 3, 4):  # un evento colocar_fondo por slide dibujado
        emitir("director_arte", "colocar_fondo", fondo, slide=slide_fondo)

    # --- El Director de arte escribe los textos en el lienzo ---
    emitir("director_arte", "escribir_texto", {"campo": "titulo", "texto": titulo}, slide=1)
    seq_texto_malo = emitir("director_arte", "escribir_texto", {"campo": "cuerpo", "texto": daily_mal}, slide=3)
    emitir("director_arte", "escribir_texto", {"campo": "cuerpo", "texto": retro}, slide=4)

    # --- El revisor verifica contra la fuente y atrapa la cifra inventada ---
    emitir("revisor", "verificacion_fidelidad", {
        "afirmacion_id": "a1",
        "afirmacion": "El Daily Scrum dura 30 minutos.",
        "clasificacion": "factual",
        "veredicto": "contradice",
        "cita": cita(frag_daily),
        "motivo": "La fuente fija un máximo de 15 minutos; el pack dice 30.",
    }, slide=3)
    emitir("revisor", "verificacion_fidelidad", {
        "afirmacion_id": "a2",
        "afirmacion": "La Retrospective dura 45 minutos para un Sprint de una semana.",
        "clasificacion": "factual",
        "veredicto": "respaldada",
        "cita": cita(frag_retro),
        "motivo": "La afirmación coincide literalmente con la fuente.",
    }, slide=4)
    seq_hallazgo = emitir("revisor", "hallazgo_abierto", {
        "hallazgo_id": "h1",
        "dimension": "fidelidad",
        "gravedad": "bloqueante",
        "evidencia": "La fuente dice: 'El Daily Scrum dura como máximo 15 minutos.'",
        "explicacion": "La cifra de 30 minutos no aparece en la fuente y la contradice.",
        "accion": "Reescribir el texto con la cifra de la fuente.",
        "responsable": "redactor",
    }, slide=3)

    # --- Corrección: el redactor reescribe y el Director de arte reemplaza el texto anterior ---
    emitir("redactor", "texto_propuesto", {"campo": "cuerpo", "texto": daily_bien}, slide=3, causa=seq_hallazgo)
    emitir("director_arte", "corregir", {
        "motivo": "Reemplaza la cifra inventada por la de la fuente",
        "operacion_nueva": {"tipo": "escribir_texto", "campo": "cuerpo", "texto": daily_bien},
    }, slide=3, causa=seq_texto_malo)

    # --- Reevaluación: la misma afirmación (a1) ahora queda respaldada y el hallazgo se cierra ---
    emitir("revisor", "verificacion_fidelidad", {
        "afirmacion_id": "a1",
        "afirmacion": "El Daily Scrum dura como máximo 15 minutos.",
        "clasificacion": "factual",
        "veredicto": "respaldada",
        "cita": cita(frag_daily),
        "motivo": "La nueva redacción coincide con la fuente.",
    }, slide=3)
    emitir("revisor", "hallazgo_corregido", {
        "hallazgo_id": "h1",
        "resultado": "corregido",
        "reevaluacion": "Reevaluada la fidelidad del slide 3: la cifra coincide con la fuente.",
    }, slide=3, causa=seq_hallazgo)

    # --- Aprobación humana: el sello 2 de 2 lo calcula código a partir de las verificaciones ---
    sello = {"afirmaciones_respaldadas": 2, "afirmaciones_totales": 2}
    emitir("sistema", "aprobacion_solicitada", {
        "estado_revision": "aprobada",
        "hallazgos_abiertos": 0,
        "sello": sello,
    })
    emitir("humano", "editada", {
        "campo": "titulo",
        "texto_antes": titulo,
        "texto_despues": "Eventos de Scrum: cuánto dura cada uno",
    }, slide=1)
    emitir("humano", "aprobada", {"decision": "aprobada", "comentario": "Listo para publicar"})
    emitir("sistema", "run_finalizada", {
        "estado_final": "aprobada",
        "fact_ledger_ref": "b5_cifra_inventada#verificacion_fidelidad",
        "sello": sello,
    })

    return {
        "$comment": "Secuencia grabada (origen 'grabado'): la cifra inventada que el revisor atrapa. Generada por gen_grabacion.py; no editar a mano.",
        "version": "0.1",
        "descripcion": "Un carrusel de 6 slides donde el redactor inventa una cifra, el revisor la atrapa con la cita de la fuente, se corrige y el humano aprueba.",
        "run_id": RUN_ID,
        "fuente_ref": FUENTE_PATH.name,
        "eventos": _eventos,
    }


def main() -> None:
    """Escribe el JSON de la grabación junto a la fuente."""
    documento = construir()
    SALIDA_PATH.write_text(json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Grabación escrita: {SALIDA_PATH} ({len(documento['eventos'])} eventos)")


if __name__ == "__main__":
    main()