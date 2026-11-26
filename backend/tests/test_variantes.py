"""Variantes de color: elección determinista, fondos aplicados, payload válido y paletas completas y legibles."""
import json
import re
from pathlib import Path

import pytest

from app import config
from app.events.validador import comprobar_evento
from app.resolution import Resolucion
from app.runs.relleno import construir_guion
from app.variantes import elegir_variante, ficha_con_variante, payload_con_variante

CAPSULA = Path(__file__).resolve().parents[2] / "templates" / "catalog" / "ig_carrusel_pasos_capsula_6slides"
FICHA = json.loads((CAPSULA / "card.json").read_text(encoding="utf-8"))
SVG = (CAPSULA / "template.svg").read_text(encoding="utf-8")
SVG = SVG[SVG.index("<svg"):]
IDS = [v["id"] for v in FICHA["variantes"]]
ENTRADA = {
    "fuente": {"tipo": "documento", "referencia": "guia.md", "idioma_salida": "es",
               "atribucion": "Autora de Prueba", "licencia": "CC BY 4.0"},
    "destino": {"red": "instagram", "formato": "carrusel_1080x1350"},
}


def colores_del_svg() -> set[str]:
    return {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", SVG)} - {"#FFFFFF"}


def test_sin_variantes_no_se_elige_nada_ni_cambia_nada():
    ficha = {k: v for k, v in FICHA.items() if k != "variantes"}
    assert elegir_variante(ficha, "run_1") is None
    assert ficha_con_variante(ficha, None) is ficha
    assert payload_con_variante({"motivo": "x"}, None) == {"motivo": "x"}


def test_el_mismo_run_da_la_misma_variante_y_entre_varios_runs_salen_todas():
    assert elegir_variante(FICHA, "run_68b4a97e") == elegir_variante(FICHA, "run_68b4a97e")
    assert {elegir_variante(FICHA, f"run_{i}").id for i in range(60)} == set(IDS)


def test_forzada_se_respeta_y_una_desconocida_falla_a_la_vista():
    assert elegir_variante(FICHA, "run_1", "menta").id == "menta"
    with pytest.raises(ValueError, match="coral"):
        elegir_variante(FICHA, "run_1", "coral")


def test_los_fondos_cambian_sin_modificar_la_ficha_original():
    originales = [s["fondo"] for s in FICHA["slides"]]
    pintada = ficha_con_variante(FICHA, elegir_variante(FICHA, "run_1", "lavanda"))
    assert [s["fondo"] for s in pintada["slides"]] == ["#E2D4FF", "#5B2BB5"] * 3
    assert [s["fondo"] for s in FICHA["slides"]] == originales


def test_la_primera_es_la_original():
    assert FICHA["variantes"][0]["reemplazos"] == {}


@pytest.mark.parametrize("variante", FICHA["variantes"][1:], ids=lambda v: v["id"])
def test_cada_paleta_reemplaza_todos_los_colores_del_svg_menos_el_blanco(variante):
    """Un color olvidado dejaría una forma azul en medio de otra paleta."""
    assert set(variante["reemplazos"]) == colores_del_svg()


@pytest.mark.parametrize("ident", IDS)
def test_el_relleno_emite_la_variante_valida_y_pinta_sus_fondos(ident, monkeypatch):
    monkeypatch.setattr(config, "VARIANTE_PLANTILLA", ident)
    resolucion = Resolucion(ficha=FICHA, plantilla_id=FICHA["id"], modo_plantilla="fijo", num_slides=6)
    guion = construir_guion("run_prueba_0001", ENTRADA, resolucion, "#112233")
    [plantilla] = [p for p in guion if p["tipo"] == "plantilla_elegida"]
    assert plantilla["payload"]["variante"]["id"] == ident
    evento = {"version": "0.1", "run_id": "run_prueba_0001", "seq": 1, "timestamp": "2026-11-26T12:00:00.000+00:00",
              "origen": "grabado", **plantilla}
    assert comprobar_evento(evento) == []
    esperados = [s["fondo"] for s in ficha_con_variante(FICHA, elegir_variante(FICHA, "x", ident))["slides"]]
    assert [p["payload"]["fondo"]["valor"] for p in guion if p["tipo"] == "colocar_fondo"] == esperados
