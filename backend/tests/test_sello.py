"""Pruebas de app/runs/sello.py: sello, hallazgos abiertos y estado final (sin red ni LLM)."""

from app.runs.sello import (
    calcular_sello,
    decidir_estado_final,
    hallazgos_abiertos,
    referencia_fact_ledger,
)


def _ver(slide, afirmacion_id, clasificacion, veredicto):
    """Arma un evento verificacion_fidelidad mínimo para las pruebas."""
    return {
        "tipo": "verificacion_fidelidad",
        "slide": slide,
        "payload": {
            "afirmacion_id": afirmacion_id,
            "clasificacion": clasificacion,
            "veredicto": veredicto,
        },
    }


def _abrir(hallazgo_id, gravedad, slide=1):
    """Arma un evento hallazgo_abierto mínimo."""
    return {
        "tipo": "hallazgo_abierto",
        "slide": slide,
        "payload": {"hallazgo_id": hallazgo_id, "gravedad": gravedad},
    }


def _cerrar(hallazgo_id, resultado, slide=1):
    """Arma un evento hallazgo_corregido mínimo."""
    return {
        "tipo": "hallazgo_corregido",
        "slide": slide,
        "payload": {"hallazgo_id": hallazgo_id, "resultado": resultado},
    }


# ---------------------------------------------------------------------------
# Sello
# ---------------------------------------------------------------------------

def test_sello_sin_eventos_es_cero_de_cero():
    """Sin verificaciones, el sello es 0 de 0."""
    assert calcular_sello([]) == {"afirmaciones_respaldadas": 0, "afirmaciones_totales": 0}


def test_sello_cuenta_respaldadas_sobre_factuales():
    """Dos factuales, una respaldada: 1 de 2."""
    eventos = [
        _ver(2, "a1", "factual", "respaldada"),
        _ver(2, "a2", "factual", "no_respaldada"),
    ]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 1, "afirmaciones_totales": 2}


def test_sello_excluye_opinion_y_cta():
    """Las opinion_cta (no_aplica) no entran ni en el total."""
    eventos = [
        _ver(1, "a1", "opinion_cta", "no_aplica"),
        _ver(2, "a2", "factual", "respaldada"),
    ]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 1, "afirmaciones_totales": 1}


def test_sello_no_verificada_entra_en_el_total_pero_no_respalda():
    """no_verificada suma al total y no a las respaldadas."""
    eventos = [_ver(3, "a1", "factual", "no_verificada")]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 0, "afirmaciones_totales": 1}


def test_sello_parcialmente_respaldada_no_cuenta_como_respaldada():
    """parcialmente_respaldada no es respaldada."""
    eventos = [_ver(3, "a1", "factual", "parcialmente_respaldada")]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 0, "afirmaciones_totales": 1}


def test_sello_el_ultimo_veredicto_manda_y_no_duplica():
    """Una reverificación (mismo id y slide) reemplaza al veredicto anterior."""
    eventos = [
        _ver(2, "a1", "factual", "no_respaldada"),
        _ver(2, "a1", "factual", "respaldada"),
    ]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 1, "afirmaciones_totales": 1}


def test_sello_mismo_id_en_slides_distintos_son_afirmaciones_distintas():
    """El id se repite entre slides: se cuentan por separado."""
    eventos = [
        _ver(2, "a1", "factual", "respaldada"),
        _ver(3, "a1", "factual", "respaldada"),
    ]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 2, "afirmaciones_totales": 2}


def test_sello_ignora_otros_tipos_y_eventos_sin_id():
    """Otros eventos y verificaciones sin afirmacion_id no cuentan."""
    eventos = [
        _abrir("h1", "menor"),
        {"tipo": "verificacion_fidelidad", "slide": 1, "payload": {"clasificacion": "factual"}},
        {"tipo": "verificacion_fidelidad", "slide": 1},
    ]
    assert calcular_sello(eventos) == {"afirmaciones_respaldadas": 0, "afirmaciones_totales": 0}


def test_sello_acepta_entradas_sin_tipo_como_las_de_todas_las_verificaciones():
    """Las entradas {"slide", "payload"} (sin "tipo") también cuentan."""
    entradas = [
        {"slide": 2, "payload": {"afirmacion_id": "a1", "clasificacion": "factual", "veredicto": "respaldada"}},
        {"slide": 3, "payload": {"afirmacion_id": "a2", "clasificacion": "factual", "veredicto": "contradice"}},
    ]
    assert calcular_sello(entradas) == {"afirmaciones_respaldadas": 1, "afirmaciones_totales": 2}


def test_sello_sobre_las_vigentes_no_cuenta_afirmaciones_que_ya_no_existen():
    """Si al re-revisar desaparece una afirmación, el historial la conserva y las vigentes no."""
    historial = [_ver(2, "a1", "factual", "respaldada"), _ver(2, "a2", "factual", "no_respaldada")]
    vigentes = [_ver(2, "a1", "factual", "respaldada")]  # tras la re-revisión solo queda a1
    assert calcular_sello(historial)["afirmaciones_totales"] == 2  # el historial infla el total
    assert calcular_sello(vigentes) == {"afirmaciones_respaldadas": 1, "afirmaciones_totales": 1}


# ---------------------------------------------------------------------------
# Hallazgos abiertos
# ---------------------------------------------------------------------------

def test_hallazgo_abierto_sin_cerrar_sigue_abierto():
    """Un hallazgo sin corregido queda abierto con su gravedad."""
    assert hallazgos_abiertos([_abrir("h1", "mayor")]) == {"h1": "mayor"}


def test_hallazgo_corregido_lo_cierra():
    """Un corregido con resultado 'corregido' lo cierra."""
    assert hallazgos_abiertos([_abrir("h1", "mayor"), _cerrar("h1", "corregido")]) == {}


def test_hallazgo_persiste_sigue_abierto():
    """Un 'persiste' no cierra el hallazgo."""
    assert hallazgos_abiertos([_abrir("h1", "menor"), _cerrar("h1", "persiste")]) == {"h1": "menor"}


def test_hallazgos_se_siguen_por_id():
    """Cerrar un hallazgo no afecta a los demás."""
    eventos = [_abrir("h1", "mayor"), _abrir("h2", "menor"), _cerrar("h1", "corregido")]
    assert hallazgos_abiertos(eventos) == {"h2": "menor"}


# ---------------------------------------------------------------------------
# Estado final
# ---------------------------------------------------------------------------

def test_estado_aprobada_sin_pendientes():
    """Sin hallazgos abiertos: aprobada."""
    assert decidir_estado_final([]) == "aprobada"
    assert decidir_estado_final([_abrir("h1", "mayor"), _cerrar("h1", "corregido")]) == "aprobada"


def test_estado_con_menores_abiertos_es_con_advertencias():
    """Solo menores abiertos: aprobada con advertencias."""
    assert decidir_estado_final([_abrir("h1", "menor")]) == "aprobada_con_advertencias"


def test_estado_con_bloqueante_abierto_requiere_humano():
    """Un bloqueante abierto nunca sale como aprobada."""
    assert decidir_estado_final([_abrir("h1", "bloqueante")]) == "requiere_humano"


def test_estado_con_mayor_abierto_requiere_humano():
    """Un mayor abierto al final también pide a una persona."""
    assert decidir_estado_final([_abrir("h1", "mayor"), _abrir("h2", "menor")]) == "requiere_humano"


def test_estado_escalado_manda_aunque_no_haya_hallazgos():
    """Si el ciclo escaló, requiere_humano aunque no queden hallazgos abiertos."""
    assert decidir_estado_final([], escalado=True) == "requiere_humano"


# ---------------------------------------------------------------------------
# Fact ledger
# ---------------------------------------------------------------------------

def test_referencia_fact_ledger_incluye_el_run_id():
    """La referencia sigue la convención del relleno: <run_id>/fact_ledger."""
    assert referencia_fact_ledger("run_abc123") == "run_abc123/fact_ledger"