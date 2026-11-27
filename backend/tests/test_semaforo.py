"""El semáforo: cuándo hay visto bueno y por qué un slide queda en rojo."""
from itertools import count

import pytest

from app.runs.aprobacion import Edicion
from app.runs.semaforo import informe


class Run:
    """Arma eventos con seq consecutivo, como los de un run."""

    def __init__(self, verificacion="verificada"):
        self._seq = count(1)
        self.eventos = []
        self.add("run_iniciada", verificacion=verificacion)

    def add(self, tipo, slide=None, **payload):
        evento = {"seq": next(self._seq), "tipo": tipo, "payload": payload}
        if slide is not None:
            evento["slide"] = slide
        self.eventos.append(evento)
        return self

    def texto(self, slide):
        return self.add("texto_propuesto", slide, campo="titulo", texto="t").add("escribir_texto", slide, campo="titulo", texto="t")

    def verif(self, slide, veredicto="respaldada", afirmacion="Frase."):
        return self.add("verificacion_fidelidad", slide, afirmacion_id="a1", veredicto=veredicto, afirmacion=afirmacion)

    def abre(self, slide, gravedad="mayor", ident="h1"):
        return self.add("hallazgo_abierto", slide, hallazgo_id=ident, gravedad=gravedad, evidencia="Frase dudosa.")


def colores(resultado):
    return {f["slide"]: f["color"] for f in resultado["slides"]}


def test_todo_verificado_y_sin_hallazgos_da_visto_bueno():
    r = informe(Run().texto(1).texto(2).verif(1).verif(2, "no_aplica").eventos)
    assert r["visto_bueno"] and r["generales"] == [] and colores(r) == {1: "verde", 2: "verde"}


def test_un_slide_sin_veredictos_esta_en_rojo():
    r = informe(Run().texto(1).texto(2).verif(1).eventos)
    assert not r["visto_bueno"] and colores(r) == {1: "verde", 2: "rojo"}


def test_un_slide_sin_texto_del_redactor_no_necesita_veredicto():
    """El slide de fuentes lo escribe el código con los datos de la persona."""
    r = informe(Run().texto(1).verif(1).add("escribir_texto", 6, campo="fuente_atribucion", texto="x").eventos)
    assert r["visto_bueno"] and colores(r) == {1: "verde", 6: "verde"}


def test_una_frase_no_verificada_pone_el_slide_en_rojo_y_la_muestra():
    r = informe(Run().texto(1).verif(1, "no_verificada", "Se ahorra la mitad.").eventos)
    assert not r["visto_bueno"] and "Se ahorra la mitad." in r["slides"][0]["motivos"][0]


def test_tras_reescribir_no_valen_los_veredictos_del_texto_anterior():
    run = Run().texto(1).verif(1).texto(1)
    assert not informe(run.eventos)["visto_bueno"]
    assert informe(run.verif(1).eventos)["visto_bueno"]


def test_un_veredicto_viejo_no_verificado_no_ensucia_el_texto_nuevo():
    assert informe(Run().texto(1).verif(1, "no_verificada").texto(1).verif(1).eventos)["visto_bueno"]


@pytest.mark.parametrize("gravedad, verde", [("bloqueante", False), ("mayor", False), ("menor", True)])
def test_los_hallazgos_abiertos_segun_su_gravedad(gravedad, verde):
    r = informe(Run().texto(1).verif(1).abre(1, gravedad).eventos)
    assert r["visto_bueno"] is verde
    assert "Frase dudosa." in (r["slides"][0]["avisos" if verde else "motivos"])[0]


def test_un_hallazgo_corregido_ya_no_cuenta_pero_uno_que_persiste_si():
    run = Run().texto(1).verif(1).abre(1).add("hallazgo_corregido", 1, hallazgo_id="h1", resultado="persiste")
    assert not informe(run.eventos)["visto_bueno"]
    assert informe(run.add("hallazgo_corregido", 1, hallazgo_id="h1", resultado="corregido").eventos)["visto_bueno"]


def test_editar_a_mano_quita_el_visto_bueno_antes_y_despues_de_emitirse():
    run = Run().texto(1).verif(1)
    antes = informe(run.eventos, [Edicion(1, "titulo", "a", "b")])
    assert not antes["visto_bueno"] and "titulo" in antes["slides"][0]["motivos"][0]
    assert not informe(run.add("editada", 1, campo="titulo").eventos)["visto_bueno"]


def test_una_edicion_re_verificada_vuelve_al_verde_y_no_arrastra_lo_viejo(subtests):
    """A5: editar y re-verificar (verificación posterior a la `editada`) da verde; los veredictos viejos caducan."""
    # El texto viejo tenía una frase no verificada; se edita y la re-verificación la respalda.
    run = Run().texto(1).verif(1, "no_verificada", "Frase vieja.").add("editada", 1, campo="titulo", texto_despues="b")
    with subtests.test("sin re-verificar sigue en rojo"):
        assert not informe(run.eventos)["visto_bueno"]
    with subtests.test("re-verificado pasa a verde, sin arrastrar la frase vieja"):
        r = informe(run.verif(1, "respaldada", "Frase nueva.").eventos)
        assert r["visto_bueno"] and colores(r) == {1: "verde"}
        assert not any("Frase vieja." in m for m in r["slides"][0]["motivos"])


@pytest.mark.parametrize("run", [Run("sin_fuente_verificada").texto(1).verif(1), Run()], ids=["sin_fuente", "sin_textos"])
def test_sin_fuente_o_sin_textos_no_hay_visto_bueno(run):
    r = informe(run.eventos)
    assert not r["visto_bueno"] and r["generales"]
