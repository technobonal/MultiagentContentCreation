"""Composiciones de la Cápsula: elección independiente de la paleta y un SVG donde solo cambian siluetas y adornos."""
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app import config
from app.events.validador import comprobar_evento
from app.resolution import Resolucion
from app.runs.relleno import construir_guion
from app.variantes import elegir_composicion, elegir_variante

CAPSULA = Path(__file__).resolve().parents[2] / "templates" / "catalog" / "ig_carrusel_pasos_capsula_6slides"
FICHA = json.loads((CAPSULA / "card.json").read_text(encoding="utf-8"))
IDS = [c["id"] for c in FICHA["composiciones"]]
SVG_NS = "{http://www.w3.org/2000/svg}"


def svg_de(composicion: str) -> ElementTree.Element:
    """El SVG como lo deja el lienzo: sin lo marcado para otras composiciones."""
    raiz = ElementTree.parse(CAPSULA / "template.svg").getroot()
    for padre in list(raiz.iter()):
        for hijo in list(padre):
            if hijo.get("data-composicion") not in (None, composicion):
                padre.remove(hijo)
    return raiz


def sin_siluetas(raiz: ElementTree.Element) -> list[tuple]:
    """Textos y fotos con su caja: lo que ninguna composición puede mover."""
    return [
        (e.tag, e.get("data-campo"), e.get("x"), e.get("y"), e.get("width"), e.get("height"))
        for e in raiz.iter() if e.tag in (f"{SVG_NS}foreignObject", f"{SVG_NS}image")
    ]


def test_las_marcas_del_svg_son_las_composiciones_de_la_ficha():
    raiz = ElementTree.parse(CAPSULA / "template.svg").getroot()
    assert {e.get("data-composicion") for e in raiz.iter()} - {None} == set(IDS)


@pytest.mark.parametrize("ident", IDS)
def test_cada_composicion_deja_una_sola_silueta_por_hueco(ident):
    raiz = svg_de(ident)
    zonas = [e for e in raiz.iter() if e.get("class") == "zona-foto"]
    recortes = [e for e in raiz.iter(f"{SVG_NS}clipPath")]
    huecos = [e for e in raiz.iter() if e.get("class") == "hueco-imagen"]
    assert len(zonas) == len(recortes) == len(huecos) == 5
    assert all(len(z) == 1 for z in zonas) and all(len(r) == 1 for r in recortes)
    for zona, hueco, recorte in zip(zonas, huecos, recortes):
        [forma] = [e for e in hueco.iter() if e.get("class") == "hueco-forma"]
        assert forma.get("data-radio")
        # El adorno, el borde y el recorte tienen que dibujar exactamente la misma silueta.
        geometria = ("d", "x", "y", "width", "height", "rx", "cx", "cy", "r")
        siluetas = [tuple((e.tag, *(e.get(a) for a in geometria))) for e in (zona[0], forma, recorte[0])]
        assert siluetas[0] == siluetas[1] == siluetas[2]


def test_textos_y_fotos_no_cambian_entre_composiciones():
    assert sin_siluetas(svg_de("a")) == sin_siluetas(svg_de("b"))


def test_la_composicion_no_va_atada_a_la_paleta():
    combinaciones = {
        (elegir_variante(FICHA, f"run_{i}").id, elegir_composicion(FICHA, f"run_{i}").id) for i in range(200)
    }
    assert len(combinaciones) == len(FICHA["variantes"]) * len(IDS)


def test_forzada_se_respeta_y_una_desconocida_falla_a_la_vista():
    assert elegir_composicion(FICHA, "run_1", "b").id == "b"
    assert elegir_composicion({}, "run_1") is None
    with pytest.raises(ValueError, match="composición «z»"):
        elegir_composicion(FICHA, "run_1", "z")


@pytest.mark.parametrize("ident", IDS)
def test_el_relleno_emite_la_composicion_en_un_evento_valido(ident, monkeypatch):
    monkeypatch.setattr(config, "COMPOSICION_PLANTILLA", ident)
    entrada = {
        "fuente": {"tipo": "documento", "referencia": "guia.md", "idioma_salida": "es",
                   "atribucion": "Autora de Prueba", "licencia": "CC BY 4.0"},
        "destino": {"red": "instagram", "formato": "carrusel_1080x1350"},
    }
    resolucion = Resolucion(ficha=FICHA, plantilla_id=FICHA["id"], modo_plantilla="fijo", num_slides=6)
    guion = construir_guion("run_prueba_0001", entrada, resolucion, "#112233")
    [plantilla] = [p for p in guion if p["tipo"] == "plantilla_elegida"]
    assert plantilla["payload"]["composicion"] == ident
    assert "Composición:" in plantilla["payload"]["motivo"]
    evento = {"version": "0.1", "run_id": "run_prueba_0001", "seq": 1, "timestamp": "2026-11-26T12:00:00.000+00:00",
              "origen": "grabado", **plantilla}
    assert comprobar_evento(evento) == []
