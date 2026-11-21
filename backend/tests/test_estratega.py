"""Pruebas del estratega: índice compacto, validación del brief y generar_brief con cliente falso."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agentes.cliente_llm import RespuestaLLM, estimar_tokens
from app.agentes.comun import AgenteError
from app.agentes.estratega import (
    MAX_TOKENS_ESTRATEGA,
    construir_indice,
    construir_mensajes,
    generar_brief,
    validar_brief,
)
from app.fuentes.cargador_fuente import FuenteCargada, fragmentar

# Entrada y resolución mínimas: solo los campos que lee el estratega.
ENTRADA = {"destino": {"red": "linkedin"}, "fuente": {"idioma_salida": "es"}}
RESOLUCION = SimpleNamespace(
    num_slides=2,
    ficha={"tipo_mensaje": "educativo", "slides": [{"numero": 1, "rol": "portada"}, {"numero": 2, "rol": "cierre"}]},
)


def _fuente(n_parrafos: int) -> FuenteCargada:
    """Fuente sintética de `n_parrafos` párrafos de ~900 caracteres (un fragmento cada uno)."""
    texto = "\n\n".join(f"Párrafo {i}. " + "texto de relleno " * 52 for i in range(n_parrafos))
    return FuenteCargada("x.md", texto, "h", len(texto), fragmentar(texto))


def _brief_json(**cambios) -> str:
    """Brief válido de dos slides; `cambios` pisa campos para armar casos inválidos."""
    base = {"angulo": "idea central", "tono": "didáctico", "slides": [
        {"numero": 1, "fragmentos": [0]}, {"numero": 2, "fragmentos": [1, 2]}]}
    base.update(cambios)
    return json.dumps(base)


class ClienteFalso:
    """Respuestas guionadas; registra el rol, los mensajes y max_tokens de cada llamada."""

    def __init__(self, respuestas, modelo="m1", fallback=False):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []
        self.modelo, self.fallback = modelo, fallback

    async def completar(self, rol, mensajes, **kw):
        self.llamadas.append({"rol": rol, "mensajes": mensajes, **kw})
        item = self.respuestas.pop(0)
        texto, motivo = item if isinstance(item, tuple) else (item, "stop")
        return RespuestaLLM(texto, self.modelo, "m1", self.fallback, motivo, None, 0.0)


def _generar(cliente, fuente=None):
    return asyncio.run(generar_brief(cliente, ENTRADA, RESOLUCION, fuente or _fuente(5)))


# ---------------------------- índice ----------------------------

def test_indice_una_linea_por_fragmento_con_numero_real():
    f = _fuente(3)
    lineas = construir_indice(f.fragmentos).split("\n")
    assert len(lineas) == 3 and lineas[0].startswith("[0] ") and lineas[2].startswith("[2] ")
    assert all(len(l) <= 4 + 250 + 1 for l in lineas)  # etiqueta + vista previa + elipsis


def test_indice_acorta_la_vista_previa_en_fuente_grande():
    f = _fuente(220)  # ~200 KB
    indice = construir_indice(f.fragmentos)
    assert len(indice) <= 10_000 and indice.count("\n") + 1 == 220


def test_indice_imposible_da_fuente_demasiado_larga():
    with pytest.raises(AgenteError) as e:
        construir_indice(_fuente(400).fragmentos)
    assert e.value.codigo == "fuente_demasiado_larga"


def test_pedido_de_fuente_grande_cabe_en_el_cupo():
    m = construir_mensajes(ENTRADA, RESOLUCION, _fuente(220))
    assert estimar_tokens(m) + MAX_TOKENS_ESTRATEGA <= int(8000 * 0.8)


def test_mensajes_prompt_fijo_primero_y_variable_al_final():
    m = construir_mensajes(ENTRADA, RESOLUCION, _fuente(2))
    assert [x["role"] for x in m] == ["system", "user"]
    assert "linkedin" not in m[0]["content"] and "linkedin" in m[1]["content"]


# ---------------------------- validar_brief ----------------------------

def _validar(dato, n_frag=3):
    return validar_brief(dato, [1, 2], n_frag)


def test_validar_brief_correcto():
    assert _validar(json.loads(_brief_json())) == []


@pytest.mark.parametrize("cambio, fragmento_motivo", [
    ({"angulo": ""}, "'angulo'"),
    ({"tono": "x" * 81}, "supera 80"),
    ({"slides": [{"numero": 1, "fragmentos": [0]}]}, "cubrir exactamente"),
    ({"slides": [{"numero": 1, "fragmentos": [0]}, {"numero": 1, "fragmentos": [1]}]}, "cubrir exactamente"),
    ({"slides": [{"numero": 1, "fragmentos": [0]}, {"numero": 2, "fragmentos": [9]}]}, "inexistentes"),
    ({"slides": [{"numero": 1, "fragmentos": []}, {"numero": 2, "fragmentos": [1]}]}, "entre 1 y 3"),
    ({"slides": [{"numero": 1, "fragmentos": [0, 1, 2, 0]}, {"numero": 2, "fragmentos": [1]}]}, "entre 1 y 3"),
    ({"slides": [{"numero": 1, "fragmentos": ["0"]}, {"numero": 2, "fragmentos": [1]}]}, "lista de enteros"),
    ({"slides": [{"numero": True, "fragmentos": [0]}, {"numero": 2, "fragmentos": [1]}]}, "entero"),
])
def test_validar_brief_rechaza(cambio, fragmento_motivo):
    motivos = _validar(json.loads(_brief_json(**cambio)))
    assert any(fragmento_motivo in m for m in motivos), motivos


def test_validar_brief_no_objeto():
    assert _validar(["no", "objeto"]) == ["la respuesta debe ser un objeto JSON"]


# ---------------------------- generar_brief ----------------------------

def test_brief_valido_a_la_primera():
    c = ClienteFalso([_brief_json()])
    b = _generar(c)
    assert b.angulo == "idea central" and b.fragmentos_por_slide == {1: (0,), 2: (1, 2)}
    llamada = c.llamadas[0]
    assert llamada["rol"] == "estratega" and llamada["max_tokens"] == MAX_TOKENS_ESTRATEGA
    assert llamada["permitir_fallback"] is True


def test_reintento_tras_json_roto():
    c = ClienteFalso(['{"angulo"', _brief_json()])
    assert _generar(c).tono == "didáctico" and len(c.llamadas) == 2


def test_salida_truncada_falla_sin_reintentar():
    c = ClienteFalso([(_brief_json()[:30], "length")])
    with pytest.raises(AgenteError) as e:
        _generar(c)
    assert e.value.codigo == "salida_truncada" and len(c.llamadas) == 1


def test_fragmentos_repetidos_se_deduplican():
    dup = {"slides": [{"numero": 1, "fragmentos": [0, 0]}, {"numero": 2, "fragmentos": [1]}]}
    assert _generar(ClienteFalso([_brief_json(**dup)])).fragmentos_por_slide[1] == (0,)


def test_registra_modelo_y_fallback():
    b = _generar(ClienteFalso([_brief_json()], modelo="otro", fallback=True))
    assert b.modelo == "otro" and b.fallback is True


def test_payload_del_evento_brief_emitido():
    p = _generar(ClienteFalso([_brief_json()])).payload_evento(RESOLUCION)
    assert p == {"angulo": "idea central", "tono": "didáctico", "num_slides": 2,
                 "tipo_mensaje": "educativo", "roles": ["portada", "cierre"]}