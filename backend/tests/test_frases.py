"""El separador de frases: corta donde corresponde y nunca pierde texto."""
import pytest

from app.agentes.frases import Frase, frases_del_slide, separar_campo


@pytest.mark.parametrize("texto, esperado", [
    ("Duran un mes.", ["Duran un mes."]),
    ("Con doce modos. Adaptas cada espacio.", ["Con doce modos.", "Adaptas cada espacio."]),
    ("¿Listo? ¡Empieza hoy! Ya", ["¿Listo?", "¡Empieza hoy!", "Ya"]),
    ("Controla cómo vives, no todo", ["Controla cómo vives, no todo"]),
    ("Recupera tu tiempo: diseña tu espacio", ["Recupera tu tiempo: diseña tu espacio"]),
    ("Mide 1.5 metros. Pesa 2,5 kg.", ["Mide 1.5 metros.", "Pesa 2,5 kg."]),
    ("La Av. Central y el Dr. Pérez.", ["La Av. Central y el Dr. Pérez."]),
    ("Cuesta aprox. 20 minutos.", ["Cuesta aprox. 20 minutos."]),
    ("Llega a las 5 p. m. cada día.", ["Llega a las 5 p. m. cada día."]),
    ("Dijo «basta.» Luego se fue.", ["Dijo «basta.»", "Luego se fue."]),
    ("1. Abre la app\n2. Entra", ["1. Abre la app", "2. Entra"]),
    ("Primera línea\nSegunda línea", ["Primera línea", "Segunda línea"]),
    ("2026", ["2026"]),
    ("  ", []),
])
def test_separar_campo(texto, esperado):
    assert separar_campo(texto) == esperado


@pytest.mark.parametrize("texto", [
    "El ruido se apaga. Tu libertad empieza... y no para. 24/7.",
    "1.\n2) Dos\n— fin —\n100 %",
])
def test_ningun_caracter_visible_se_pierde(texto):
    assert "".join(separar_campo(texto)).replace(" ", "") == "".join(texto.split())


def test_la_numeracion_es_corrida_y_cada_frase_sabe_su_campo():
    campos = {"{{titulo}}": "Controla cómo vives", "cuerpo": "Una. Dos.", "vacio": ""}
    assert frases_del_slide(campos) == [
        Frase(1, "titulo", "Controla cómo vives"), Frase(2, "cuerpo", "Una."), Frase(3, "cuerpo", "Dos."),
    ]
