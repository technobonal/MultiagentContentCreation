"""Limpieza de encabezados y pies repetidos del texto de un PDF."""
from app.fuentes.cargador_fuente import quitar_encabezados_y_pies


def pagina(n: int, cuerpo: list[str]) -> list[str]:
    return ["Informe de Salud 2024", *cuerpo, f"Página {n}"]


def test_quita_encabezado_y_pie_que_solo_cambian_de_numero():
    cuerpos = ["alfa", "bravo", "charlie", "delta", "eco"]
    limpias = quitar_encabezados_y_pies([pagina(n, [c]) for n, c in enumerate(cuerpos, 1)])
    assert limpias == [[c] for c in cuerpos]


def test_no_toca_el_texto_del_medio_aunque_se_repita():
    # El mismo texto idéntico en el medio de cada página (lejos del borde) se conserva.
    extremos = [("uno", "dos"), ("tres", "cuatro"), ("cinco", "seis"), ("siete", "ocho")]
    paginas = [pagina(n, [a, b, "Informe de Salud 2024", a + "!", b + "!"]) for n, (a, b) in enumerate(extremos, 1)]
    for limpia, (a, b) in zip(quitar_encabezados_y_pies(paginas), extremos):
        assert limpia == [a, b, "Informe de Salud 2024", a + "!", b + "!"]


def test_numero_de_pagina_suelto_en_el_borde_se_quita():
    textos = ["alfa", "bravo", "charlie", "delta"]
    paginas = [[t, str(n)] for n, t in enumerate(textos, 1)]
    assert quitar_encabezados_y_pies(paginas) == [[t] for t in textos]


def test_con_pocas_paginas_no_limpia():
    paginas = [pagina(n, [c]) for n, c in enumerate(["alfa", "bravo", "charlie"], 1)]
    assert quitar_encabezados_y_pies(paginas) == paginas


def test_un_bloque_repetido_en_pocas_paginas_se_conserva():
    paginas = [["Aviso", "uno"], ["Aviso", "dos"]] + [[f"x{n}", f"y{n}"] for n in range(6)]
    limpias = quitar_encabezados_y_pies(paginas)
    assert limpias[0] == ["Aviso", "uno"]
