"""Un slide que queda sin veredictos nunca sale aprobado: con el ciclo, el revisor y el corrector reales."""
import asyncio
from types import SimpleNamespace

import app.agentes.revisor_fidelidad as rf
from app.agentes.adaptadores_ciclo import CorrectorCarrusel, EstadoCarrusel, RevisorCarrusel
from app.agentes.ciclo_correccion import ejecutar_ciclo
from app.agentes.estratega import Brief
from app.agentes.redactor import TextoSlide
from app.agentes.revisor_codigo import con_ids
from app.events.validador import comprobar_evento
from app.runs.sello import decidir_estado_final, hallazgos_abiertos

FRASE = "El Sprint dura un mes como máximo."
FUENTE = SimpleNamespace(texto=FRASE, fragmentos=(SimpleNamespace(indice=0, texto=FRASE, inicio=0),))


def test_el_run_pide_una_persona_y_el_texto_no_se_reescribe():
    textos = {n: TextoSlide(n, {"titulo": "El Sprint dura un mes"}, (), "m1", False) for n in (1, 2)}
    estado = EstadoCarrusel(textos=textos, brief=Brief("idea", "claro", {1: (0,), 2: (0,)}, "m1", False))
    bien = {"frase": 1, "tipo": "factual", "veredicto": "respaldada",
            "cita": FRASE, "motivo": "ok"}

    async def pedir(sistema, usuario):
        # El slide 2 nunca trae afirmaciones; el 1 sí.
        return {"afirmaciones": [bien] if "SLIDE: 1" in usuario else []}

    async def sin_redactor(*args, **kwargs):
        raise AssertionError("un texto que nadie juzgó no se reescribe")

    eventos = []

    async def emitir(**datos):
        evento = {"version": "0.1", "run_id": "run_prueba_0001", "seq": len(eventos) + 1,
                  "timestamp": "2026-11-26T12:00:00.000+00:00", "origen": "real",
                  **{k: v for k, v in datos.items() if v is not None}}
        assert comprobar_evento(evento) == []
        eventos.append(evento)
        return evento

    revisor = RevisorCarrusel(
        None, None, {}, {}, FUENTE, revisar_codigo=lambda *a: [], revisar_fidelidad=rf.revisar_fidelidad,
        con_ids=con_ids, pedir=pedir,
    )
    corrector = CorrectorCarrusel(None, {}, None, FUENTE, redactar=sin_redactor)
    resultado = asyncio.run(ejecutar_ciclo(estado, revisar=revisor, corregir=corrector, emitir=emitir))

    assert resultado.estado_final == "requiere_humano"
    assert [(e["tipo"], e["slide"]) for e in eventos] == [("verificacion_fidelidad", 1), ("hallazgo_abierto", 2)]
    assert list(hallazgos_abiertos(eventos).values()) == ["mayor"]
    assert decidir_estado_final(eventos) == "requiere_humano"
