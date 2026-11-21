"""Pruebas del ciclo de corrección: sin LLM ni servidor, todo con simulaciones inyectadas."""

import asyncio

import pytest

from app.agentes.ciclo_correccion import Revision, ejecutar_ciclo


class EmisorFalso:
    """Imita Ejecucion.emitir: guarda cada evento con seq consecutivo y lo devuelve."""

    def __init__(self):
        self.eventos = []

    async def __call__(self, agente, tipo, payload, slide=None, causa=None):
        evento = {"seq": len(self.eventos) + 1, "agente": agente, "tipo": tipo, "payload": payload}
        # slide y causa solo viajan cuando se usan, igual que en la Ejecucion real.
        if slide is not None:
            evento["slide"] = slide
        if causa is not None:
            evento["causa"] = causa
        self.eventos.append(evento)
        return evento

    def de_tipo(self, tipo):
        """Eventos emitidos de un tipo, en orden."""
        return [e for e in self.eventos if e["tipo"] == tipo]


class RevisorFalso:
    """Entrega una Revision por llamada; si se acaban, repite la última."""

    def __init__(self, *rondas):
        self.rondas = list(rondas)
        self.llamadas = []  # (estado, alcance) de cada llamada

    async def __call__(self, estado, alcance):
        self.llamadas.append((estado, alcance))
        return self.rondas[min(len(self.llamadas) - 1, len(self.rondas) - 1)]


class CorrectorFalso:
    """Registra cada corrección y devuelve el estado + 1."""

    def __init__(self):
        self.llamadas = []  # (responsable, slide, ids)

    async def __call__(self, responsable, slide, hallazgos, estado):
        self.llamadas.append((responsable, slide, [h.hallazgo_id for h in hallazgos]))
        return estado + 1


def hallazgo(slide, dimension="contraste", gravedad="bloqueante", evidencia="e", responsable="redactor"):
    """Hallazgo sin hallazgo_id, con la forma que entrega el revisor."""
    return {
        "slide": slide,
        "payload": {
            "dimension": dimension,
            "gravedad": gravedad,
            "evidencia": evidencia,
            "explicacion": "explicación",
            "accion": "acción",
            "responsable": responsable,
        },
    }


def correr(revisor, *, estado=0, corrector=None, **kw):
    """Ejecuta el ciclo y devuelve (resultado, emisor, corrector)."""
    emisor = EmisorFalso()
    corrector = corrector or CorrectorFalso()
    res = asyncio.run(ejecutar_ciclo(estado, revisar=revisor, corregir=corrector, emitir=emisor, **kw))
    return res, emisor, corrector


def test_sin_hallazgos_aprueba_en_una_ronda():
    res, emisor, corrector = correr(RevisorFalso(Revision()))
    assert (res.estado_final, res.motivo, res.rondas) == ("aprobado", "sin_pendientes", 1)
    assert corrector.llamadas == []
    assert emisor.de_tipo("hallazgo_abierto") == []


def test_hallazgo_corregido_en_segunda_ronda():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(2)]), Revision())
    res, emisor, corrector = correr(revisor)
    abierto = emisor.de_tipo("hallazgo_abierto")
    corregido = emisor.de_tipo("hallazgo_corregido")
    assert res.estado_final == "aprobado" and res.rondas == 2 and res.corregidos == ["h1"]
    assert len(abierto) == 1 and abierto[0]["payload"]["hallazgo_id"] == "h1"
    assert abierto[0]["payload"]["gravedad"] == "bloqueante" and abierto[0]["agente"] == "revisor"
    # El cierre apunta con `causa` al seq del hallazgo_abierto original.
    assert len(corregido) == 1 and corregido[0]["causa"] == abierto[0]["seq"]
    assert corregido[0]["payload"]["resultado"] == "corregido" and corregido[0]["slide"] == 2
    assert corrector.llamadas == [("redactor", 2, ["h1"])]


def test_persiste_hasta_el_tope_y_escala():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1)]))  # siempre el mismo hallazgo
    res, emisor, corrector = correr(revisor)
    persiste = emisor.de_tipo("hallazgo_corregido")
    abierto = emisor.de_tipo("hallazgo_abierto")
    assert (res.estado_final, res.motivo, res.rondas) == ("requiere_humano", "tope_de_rondas", 3)
    assert len(corrector.llamadas) == 2  # revisión inicial + 2 reintentos
    assert len(abierto) == 1  # no se reabre el mismo hallazgo
    assert [e["payload"]["resultado"] for e in persiste] == ["persiste", "persiste"]
    assert all(e["causa"] == abierto[0]["seq"] for e in persiste)
    assert [h.hallazgo_id for h in res.pendientes] == ["h1"]


def test_corta_sin_progreso_solo_si_se_pide():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1)]))
    res, _, corrector = correr(revisor, max_rondas=5, cortar_sin_progreso=True)
    assert (res.estado_final, res.motivo, res.rondas) == ("requiere_humano", "sin_progreso", 2)
    assert len(corrector.llamadas) == 1


def test_agrupa_por_responsable_y_slide_con_bloqueantes_primero():
    primera = Revision(hallazgos=[
        hallazgo(1, gravedad="mayor", evidencia="a"),
        hallazgo(1, gravedad="bloqueante", evidencia="b"),
        hallazgo(3, gravedad="bloqueante", evidencia="c", responsable="director_arte"),
    ])
    revisor = RevisorFalso(primera, Revision())
    res, _, corrector = correr(revisor)
    # h1=mayor(a), h2=bloqueante(b), h3=bloqueante(c): los bloqueantes encabezan cada grupo.
    assert corrector.llamadas == [("redactor", 1, ["h2", "h1"]), ("director_arte", 3, ["h3"])]
    assert revisor.llamadas[1][1] == {1, 3}
    assert res.estado_final == "aprobado"


def test_alcance_limita_lo_que_se_da_por_corregido():
    primera = Revision(hallazgos=[hallazgo(1), hallazgo(4, gravedad="menor", evidencia="m")])
    revisor = RevisorFalso(primera, Revision())
    res, emisor, _ = correr(revisor)
    assert revisor.llamadas[0][1] is None and revisor.llamadas[1][1] == {1}
    # El menor del slide 4 no se re-revisó: sigue abierto y no se marca corregido.
    assert res.corregidos == ["h1"] and [h.hallazgo_id for h in res.pendientes] == ["h2"]
    assert res.estado_final == "aprobado"  # los menores no bloquean
    assert len(emisor.de_tipo("hallazgo_corregido")) == 1


def test_responsable_estratega_obliga_a_revisar_todo():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(2, responsable="estratega")]), Revision())
    correr(revisor)
    assert revisor.llamadas[1][1] is None


def test_hallazgo_sin_slide_obliga_a_revisar_todo():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(None)]), Revision())
    _, emisor, corrector = correr(revisor)
    assert revisor.llamadas[1][1] is None and corrector.llamadas == [("redactor", None, ["h1"])]
    assert "slide" not in emisor.de_tipo("hallazgo_abierto")[0]


def test_hallazgo_nuevo_recibe_el_id_siguiente():
    revisor = RevisorFalso(
        Revision(hallazgos=[hallazgo(1)]),
        Revision(hallazgos=[hallazgo(2, gravedad="mayor", evidencia="otra")]),
        Revision(),
    )
    res, emisor, _ = correr(revisor)
    ids = [e["payload"]["hallazgo_id"] for e in emisor.de_tipo("hallazgo_abierto")]
    assert ids == ["h1", "h2"] and res.corregidos == ["h1", "h2"]
    assert (res.estado_final, res.rondas) == ("aprobado", 3)


def test_verificaciones_se_emiten_en_cada_ronda():
    verificacion = {"slide": 1, "payload": {"afirmacion_id": "a1", "veredicto": "respaldada"}}
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1)], verificaciones=[verificacion]), Revision(verificaciones=[verificacion]))
    _, emisor, _ = correr(revisor)
    eventos = emisor.de_tipo("verificacion_fidelidad")
    assert len(eventos) == 2
    assert all(e["agente"] == "revisor" and e["slide"] == 1 and e["payload"] == verificacion["payload"] for e in eventos)


def test_duplicado_en_la_misma_revision_se_abre_una_vez():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1), hallazgo(1)]), Revision())
    _, emisor, _ = correr(revisor)
    assert len(emisor.de_tipo("hallazgo_abierto")) == 1


def test_gravedad_no_corregible_no_dispara_correccion():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1, gravedad="menor")]))
    res, emisor, corrector = correr(revisor)
    assert (res.estado_final, res.rondas) == ("aprobado", 1)
    assert corrector.llamadas == [] and len(emisor.de_tipo("hallazgo_abierto")) == 1
    assert len(res.pendientes) == 1


def test_max_rondas_uno_revisa_pero_no_corrige():
    res, _, corrector = correr(RevisorFalso(Revision(hallazgos=[hallazgo(1)])), max_rondas=1)
    assert (res.estado_final, res.motivo, res.rondas) == ("requiere_humano", "tope_de_rondas", 1)
    assert corrector.llamadas == []


def test_max_rondas_invalido():
    with pytest.raises(ValueError):
        correr(RevisorFalso(Revision()), max_rondas=0)


def test_el_estado_corregido_llega_a_la_siguiente_revision():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1)]), Revision())
    res, _, _ = correr(revisor, estado=0)
    assert revisor.llamadas[0][0] == 0 and revisor.llamadas[1][0] == 1 and res.estado == 1


def test_un_error_del_corrector_se_propaga():
    class Roto:
        async def __call__(self, responsable, slide, hallazgos, estado):
            raise RuntimeError("falló el LLM")

    with pytest.raises(RuntimeError):
        correr(RevisorFalso(Revision(hallazgos=[hallazgo(1)])), corrector=Roto())


class CorrectorSelectivo:
    """Solo cambia el estado cuando el responsable es el redactor; con otros devuelve el mismo objeto."""

    def __init__(self):
        self.llamadas = []  # (responsable, slide)

    async def __call__(self, responsable, slide, hallazgos, estado):
        self.llamadas.append((responsable, slide))
        # El redactor "corrige" (estado nuevo); los demás no pueden (mismo objeto).
        return estado + 1 if responsable == "redactor" else estado


def test_sin_cambios_escala_sin_re_revisar():
    revisor = RevisorFalso(Revision(hallazgos=[hallazgo(1, responsable="director_arte")]))
    res, emisor, corrector = correr(revisor, corrector=CorrectorSelectivo())
    assert (res.estado_final, res.motivo, res.rondas) == ("requiere_humano", "sin_cambios", 1)
    assert len(revisor.llamadas) == 1  # no hubo re-revisión
    assert emisor.de_tipo("hallazgo_corregido") == []  # sin cambio no se declara "persiste"
    assert [h.hallazgo_id for h in res.pendientes] == ["h1"] and res.pendientes[0].intentos == 0


def test_grupo_sin_cambio_no_amplia_el_alcance_ni_cuenta_intento():
    primera = Revision(hallazgos=[hallazgo(1), hallazgo(3, evidencia="c", responsable="director_arte")])
    revisor = RevisorFalso(primera, Revision())
    res, emisor, corrector = correr(revisor, corrector=CorrectorSelectivo())
    # Ronda 2 solo re-revisa el slide 1; el slide 3 no cambió, así que sigue abierto.
    assert revisor.llamadas[1][1] == {1}
    assert res.corregidos == ["h1"] and [h.hallazgo_id for h in res.pendientes] == ["h2"]
    # En la ronda 2 nadie pudo corregir lo que queda: escala sin una tercera revisión.
    assert (res.estado_final, res.motivo, res.rondas) == ("requiere_humano", "sin_cambios", 2)
    assert res.pendientes[0].intentos == 0
    assert emisor.de_tipo("hallazgo_corregido")[0]["payload"]["resultado"] == "corregido"