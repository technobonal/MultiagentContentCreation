"""Pruebas de la verificación literal de hechos: ubicación exacta, tolerancia de blancos y casos límite."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.agentes.verificar_hechos import HechoUbicado, ubicar_hecho, ubicar_hechos

# Fuente sintética de dos fragmentos separados por una línea en blanco (2 caracteres de separación).
P0 = "El Sprint dura un mes como máximo. El equipo tiene 10 personas o menos."
P1 = "El Product Owner ordena el Product Backlog.\nEl Scrum Master ayuda al equipo."
TEXTO = P0 + "\n\n" + P1
INICIO_P1 = len(P0) + 2  # posición absoluta donde empieza el segundo fragmento


def _frag(indice: int, texto: str, inicio: int):
    """Fragmento con los tres campos que lee el verificador (indice, texto, inicio)."""
    return SimpleNamespace(indice=indice, texto=texto, inicio=inicio)


FRAGMENTOS = (_frag(0, P0, 0), _frag(1, P1, INICIO_P1))


# ---------------------------- ubicar_hecho ----------------------------

def test_ubica_el_hecho_con_su_rango_exacto():
    h = ubicar_hecho("El Sprint dura un mes como máximo.", FRAGMENTOS)
    assert h == HechoUbicado("El Sprint dura un mes como máximo.", 0, 34, 0)
    assert TEXTO[h.inicio:h.fin] == h.texto  # el contrato: fuente[inicio:fin] == texto


def test_la_posicion_es_absoluta_en_fragmentos_posteriores():
    h = ubicar_hecho("El Scrum Master ayuda al equipo.", FRAGMENTOS)
    assert h.fragmento == 1 and h.inicio >= INICIO_P1
    assert TEXTO[h.inicio:h.fin] == h.texto


def test_tolera_blancos_distintos_y_guarda_el_trozo_real():
    # El modelo aplanó el salto de línea a un espacio: el hecho guardado conserva el original.
    h = ubicar_hecho("El Product Owner ordena el Product Backlog. El Scrum Master ayuda", FRAGMENTOS)
    assert h is not None and "\n" in h.texto
    assert TEXTO[h.inicio:h.fin] == h.texto


def test_tolera_espacios_repetidos_en_el_hecho():
    assert ubicar_hecho("El   equipo   tiene 10 personas", FRAGMENTOS) is not None


def test_distingue_mayusculas():
    assert ubicar_hecho("el sprint dura un mes", FRAGMENTOS) is None


def test_hecho_inexistente_devuelve_none():
    assert ubicar_hecho("El Sprint dura dos meses.", FRAGMENTOS) is None


@pytest.mark.parametrize("vacio", ["", "   ", "\n\t "])
def test_hecho_vacio_o_solo_blancos_devuelve_none(vacio):
    assert ubicar_hecho(vacio, FRAGMENTOS) is None


def test_caracteres_especiales_se_buscan_literales():
    # Paréntesis, punto y signo + no deben interpretarse como regex.
    frag = (_frag(0, "El costo (10 %) sube a 1.000+ unidades.", 0),)
    assert ubicar_hecho("costo (10 %) sube a 1.000+ unidades.", frag) is not None
    assert ubicar_hecho("costo (10 %) sube a 1x000+ unidades.", frag) is None  # el punto no es comodín


def test_devuelve_la_primera_aparicion_en_orden_de_fragmentos():
    frags = (_frag(0, "dato repetido", 0), _frag(1, "otro dato repetido", 15))
    assert ubicar_hecho("dato repetido", frags).fragmento == 0


def test_un_hecho_no_cruza_de_un_fragmento_a_otro():
    # Termina en el fragmento 0 y sigue en el 1: ningún fragmento lo contiene entero.
    assert ubicar_hecho("o menos. El Product Owner", FRAGMENTOS) is None


def test_sin_fragmentos_no_encuentra_nada():
    assert ubicar_hecho("cualquier cosa", ()) is None


def test_hecho_ubicado_es_inmutable():
    h = ubicar_hecho("El Sprint dura un mes", FRAGMENTOS)
    with pytest.raises(FrozenInstanceError):
        h.inicio = 99


# ---------------------------- ubicar_hechos ----------------------------

def test_ubicar_hechos_separa_ubicados_y_faltantes_en_orden():
    ubicados, faltan = ubicar_hechos(
        ["El Scrum Master ayuda al equipo.", "no está en la fuente", "El Sprint dura un mes"], FRAGMENTOS
    )
    assert [u.fragmento for u in ubicados] == [1, 0]  # conserva el orden recibido
    assert faltan == ["no está en la fuente"]


def test_ubicar_hechos_no_repite_el_mismo_rango():
    # Dos formas de pedir el mismo trozo (una con blancos distintos) dan un único hecho.
    ubicados, faltan = ubicar_hechos(["El Sprint dura un mes", "El  Sprint dura un mes"], FRAGMENTOS)
    assert len(ubicados) == 1 and faltan == []


def test_ubicar_hechos_conserva_rangos_distintos_aunque_se_solapen():
    ubicados, _ = ubicar_hechos(["El Sprint dura", "El Sprint dura un mes"], FRAGMENTOS)
    assert len(ubicados) == 2  # mismo inicio pero distinto fin: son citas diferentes


def test_ubicar_hechos_lista_vacia():
    assert ubicar_hechos([], FRAGMENTOS) == ([], [])


def test_ubicar_hechos_todos_cumplen_el_contrato_de_rango():
    ubicados, _ = ubicar_hechos(["El equipo tiene 10 personas o menos.", "ordena el Product Backlog"], FRAGMENTOS)
    # Cada hecho ubicado debe poder recortarse de la fuente con su rango.
    for u in ubicados:
        assert TEXTO[u.inicio:u.fin] == u.texto