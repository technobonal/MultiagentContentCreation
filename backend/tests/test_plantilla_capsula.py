"""La plantilla Cápsula: mismos campos en la ficha y el SVG, mismos límites que la oscura y texto legible (WCAG AA)."""
import json
import re
from pathlib import Path

import pytest

from app.agentes.revisor_codigo import razon_contraste
from app.resolution import cargar_fichas, resolver

CATALOGO = Path(__file__).resolve().parents[2] / "templates" / "catalog"
CAPSULA = "ig_carrusel_pasos_capsula_6slides"
OSCURA = "ig_carrusel_pasos_oscuro_6slides"
FICHA = json.loads((CATALOGO / CAPSULA / "card.json").read_text(encoding="utf-8"))
SVG = (CATALOGO / CAPSULA / "template.svg").read_text(encoding="utf-8")
# El CTA va sobre la caja de color del slide 5, no sobre el fondo del slide.
FONDO_PROPIO_DEL_CAMPO = {(5, "cta"): "#3B49DF"}


def grupo(n: int) -> str:
    inicio = SVG.index(f'<g id="slide-{n}"')
    fin = SVG.index(f'<g id="slide-{n + 1}"') if n < 6 else SVG.index("</svg>")
    return SVG[inicio:fin]


def campos_del_svg(n: int) -> dict[str, str]:
    """campo -> color del texto, tal como está escrito en el SVG."""
    patron = r'<foreignObject[^>]*data-campo="\{\{(\w+)\}\}"[^>]*>\s*<div[^>]*color:(#[0-9A-Fa-f]{6});'
    return {m.group(1): m.group(2) for m in re.finditer(patron, grupo(n), re.S)}


@pytest.mark.parametrize("slide", FICHA["slides"], ids=lambda s: f"slide{s['numero']}")
def test_la_ficha_y_el_svg_tienen_los_mismos_campos(slide):
    textos = {c["nombre"].strip("{}") for c in slide["campos"] if c["tipo"] != "imagen"}
    assert set(campos_del_svg(slide["numero"])) == textos


def cajas(n: int, etiqueta: str) -> list[tuple[int, int, int, int]]:
    """(x1, y1, x2, y2) de cada <foreignObject> o <image> del slide."""
    patron = rf'<{etiqueta} x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"'
    return [(x, y, x + w, y + h) for x, y, w, h in (tuple(map(int, m)) for m in re.findall(patron, grupo(n)))]


@pytest.mark.parametrize("n", range(1, 6))
def test_cada_slide_menos_el_de_fuentes_tiene_un_hueco_de_foto_que_no_pisa_el_texto(n):
    [(fx1, fy1, fx2, fy2)] = cajas(n, "image")
    for tx1, ty1, tx2, ty2 in cajas(n, "foreignObject"):
        assert not (fx1 < tx2 and tx1 < fx2 and fy1 < ty2 and ty1 < fy2), f"la foto pisa el texto {(tx1, ty1, tx2, ty2)}"
    assert 'class="hueco-forma"' in grupo(n) and f"url(#recorte-foto-{n})" in grupo(n)


@pytest.mark.parametrize("slide", FICHA["slides"], ids=lambda s: f"slide{s['numero']}")
def test_cada_texto_se_lee_sobre_su_fondo(slide):
    for campo, color in campos_del_svg(slide["numero"]).items():
        fondo = FONDO_PROPIO_DEL_CAMPO.get((slide["numero"], campo), slide["fondo"])
        assert razon_contraste(color, fondo) >= 4.5, f"{campo}: {color} sobre {fondo}"


def test_tiene_los_mismos_campos_de_texto_y_limites_que_la_oscura():
    """Así el redactor y el revisor trabajan igual con las dos plantillas."""
    def textos(pid):
        ficha = json.loads((CATALOGO / pid / "card.json").read_text(encoding="utf-8"))
        return {s["numero"]: [c for c in s["campos"] if c["tipo"] != "imagen"] for s in ficha["slides"]}

    assert textos(CAPSULA) == textos(OSCURA)


def test_se_puede_pedir_en_modo_fijo_y_no_reemplaza_a_la_de_siempre_en_auto():
    entrada = {"destino": {"red": "instagram", "formato": "carrusel_1080x1350"}, "fuente": {"idioma_salida": "es"}}
    auto, _ = resolver(entrada, cargar_fichas())
    fija, errores = resolver(entrada | {"diseno": {"plantilla": {"modo": "fijo", "valor": CAPSULA}}}, cargar_fichas())
    assert auto.plantilla_id == OSCURA and errores == [] and fija.plantilla_id == CAPSULA
