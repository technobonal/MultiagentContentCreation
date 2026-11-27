"""Guion de relleno del paso 1: eventos válidos sin LLM para probar el canal de punta a punta.

Es una función pura: de la entrada y la plantilla resuelta sale una lista de pasos
({agente, tipo, payload, slide}) que el orquestador emite uno a uno. Desde el paso 2 los
agentes reales reemplazan este guion.

Lo que NO inventa el relleno: no emite `fuente_indexada` (su sha256 afirma "esta fuente exacta" y
aquí no se lee ninguna), declara la fuente como `sin_fuente_verificada` y no pide aprobación
(ese flujo llega después del revisor). Termina en `run_finalizada` con `requiere_humano`.
"""

import json

from app import config
from app.variantes import elegir_composicion, elegir_variante, ficha_con_variante, payload_con_variante

# Origen de los eventos de relleno. "grabado" hace que el lienzo muestre su marca visible, porque
# no los emite un agente en ejecución. En el paso 2, los agentes reales emiten con "real".
ORIGEN_RELLENO = "grabado"


def color_de_fondo(entrada: dict) -> str:
    """Color de fondo de los slides: la paleta fija del usuario o, si no, la del kit de marca.

    Un preset de paleta por nombre aún no se resuelve en el paso 1: se usa el kit.
    """
    paleta = entrada.get("diseno", {}).get("paleta", {})
    # Paleta fija con los cuatro roles: se respeta tal cual.
    if paleta.get("modo") == "fijo" and isinstance(paleta.get("valor"), dict):
        return paleta["valor"]["fondo"]
    with open(config.KITS_DIR / f"{config.KIT_MARCA}.json", encoding="utf-8") as f:
        kit = json.load(f)
    return kit["paleta"]["fondo"]


def _texto_de_relleno(slide: int, campo: str, longitud_max: int) -> str:
    """Texto marcador de un campo que normalmente escribiría el redactor."""
    return f"Relleno · slide {slide} · {campo}"[:longitud_max]


def construir_guion(run_id: str, entrada: dict, resolucion, color_fondo: str) -> list[dict]:
    """Construye la lista ordenada de eventos de relleno de una ejecución."""
    variante = elegir_variante(resolucion.ficha, run_id, config.VARIANTE_PLANTILLA)
    ficha = ficha_con_variante(resolucion.ficha, variante)
    composicion = elegir_composicion(resolucion.ficha, run_id, config.COMPOSICION_PLANTILLA)
    fuente = entrada["fuente"]
    # Valores que ya trae el usuario y que el director de arte escribe tal cual (sin redactor).
    valores_usuario = {"fuente_atribucion": fuente["atribucion"], "fuente_licencia": fuente["licencia"]}

    guion = [
        {
            "agente": "sistema",
            "tipo": "run_iniciada",
            "payload": {
                "entrada_ref": run_id,  # la entrada vive en memoria: su identificador es el run_id
                "plataforma": entrada["destino"]["red"],
                "idioma_salida": fuente["idioma_salida"],
                "num_slides": resolucion.num_slides,
                "verificacion": "sin_fuente_verificada",  # nada se verificó todavía
                "fuente": {"tipo": fuente["tipo"], "atribucion": fuente["atribucion"], "licencia": fuente["licencia"]},
            },
        },
        {
            "agente": "estratega",
            "tipo": "brief_emitido",
            "payload": {
                "angulo": "Relleno del paso 1: el ángulo real lo define el estratega desde el paso 2",
                "tono": "Neutro (relleno)",
                "num_slides": resolucion.num_slides,
                "tipo_mensaje": ficha["tipo_mensaje"],
                "roles": [s["rol"] for s in ficha["slides"]],
            },
        },
        {
            "agente": "director_arte",
            "tipo": "plantilla_elegida",
            "payload": payload_con_variante({
                "plantilla_id": resolucion.plantilla_id,
                "modo": resolucion.modo_plantilla,
                "motivo": (
                    "Se respetó la plantilla fijada por el usuario"
                    if resolucion.modo_plantilla == "fijo"
                    else "Plantilla compatible del catálogo (elección de relleno, sin LLM)"
                ),
                "confianza": 1.0,
            }, variante, composicion),
        },
    ]

    # Por cada slide: textos propuestos, fondo y textos escritos en el lienzo.
    for slide in ficha["slides"]:
        numero = slide["numero"]
        textos = []  # (campo, texto) que el director de arte escribirá en este slide
        # Cada campo de texto de la ficha se trata según de dónde viene su valor.
        for campo in slide["campos"]:
            nombre = campo["nombre"].strip("{}")
            if campo["tipo"] != "texto" or campo["origen_valor"] == "calculado":
                continue  # imágenes (paso 3) y valores calculados por código (sello) no se escriben
            if campo["origen_valor"] == "llm":
                texto = _texto_de_relleno(numero, nombre, campo["longitud_max"])
                # El redactor propone el texto; el director de arte lo escribe después.
                guion.append({
                    "agente": "redactor", "tipo": "texto_propuesto", "slide": numero,
                    "payload": {"campo": nombre, "texto": texto},
                })
                textos.append((nombre, texto))
            elif nombre in valores_usuario:  # valor que dio el usuario: se escribe sin redactor
                textos.append((nombre, valores_usuario[nombre]))
        guion.append({
            "agente": "director_arte", "tipo": "colocar_fondo", "slide": numero,
            "payload": {"fondo": {"tipo": "color", "valor": slide.get("fondo") or color_fondo}},
        })
        # El director de arte escribe cada texto en su campo del lienzo.
        for nombre, texto in textos:
            guion.append({
                "agente": "director_arte", "tipo": "escribir_texto", "slide": numero,
                "payload": {"campo": nombre, "texto": texto},
            })

    guion.append({
        "agente": "sistema",
        "tipo": "run_finalizada",
        "payload": {
            "estado_final": "requiere_humano",  # nada se verificó: un humano debe decidir
            "fact_ledger_ref": f"{run_id}/fact_ledger",  # vacío en el relleno (sin verificaciones)
            "sello": {"afirmaciones_respaldadas": 0, "afirmaciones_totales": 0},
        },
    })
    return guion
