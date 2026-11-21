"""Pruebas de app.agentes.comun: cargador de prompts, extracción de JSON y pedir_json.

Sin red: se usa un cliente falso con la misma interfaz `completar`. Los casos async corren con
asyncio.run para no depender de ningún plugin de pytest.
"""

import asyncio

import pytest

from app.agentes.cliente_llm import RespuestaLLM
from app.agentes.comun import AgenteError, cargar_prompt, extraer_json, pedir_json


class ClienteFalso:
    """Devuelve respuestas guionadas y guarda los mensajes que recibió en cada llamada."""

    def __init__(self, respuestas):
        # Cada elemento: texto (str) o (texto, finish_reason).
        self.respuestas = list(respuestas)
        self.vistos: list[list[dict]] = []

    async def completar(self, rol, mensajes, **kw):
        self.vistos.append(list(mensajes))  # copia: pedir_json arma una lista nueva por reintento
        item = self.respuestas.pop(0)
        texto, motivo = item if isinstance(item, tuple) else (item, "stop")
        return RespuestaLLM(texto, "modelo-x", "modelo-x", False, motivo, None, 0.0)


def _ok(d):
    """Validador de prueba: exige la clave 'a'."""
    return [] if isinstance(d, dict) and "a" in d else ["falta 'a'"]


def _correr(cliente, **kw):
    """Atajo: ejecuta pedir_json con el validador de prueba."""
    return asyncio.run(pedir_json(cliente, "estratega", [{"role": "user", "content": "x"}], _ok, max_tokens=100, **kw))


# ---------------------------- cargar_prompt ----------------------------

def test_prompt_quita_comentarios_html(tmp_path):
    (tmp_path / "p.md").write_text("<!-- nota\nmultilínea -->\nHola\n\n\n\n<!-- otra -->\nMundo\n", encoding="utf-8")
    assert cargar_prompt("p", tmp_path) == "Hola\n\nMundo"


def test_prompt_inexistente_da_error_claro(tmp_path):
    with pytest.raises(AgenteError) as e:
        cargar_prompt("no_existe", tmp_path)
    assert e.value.codigo == "prompt_no_encontrado"


def test_prompt_solo_comentarios_es_vacio(tmp_path):
    (tmp_path / "v.md").write_text("<!-- nada -->", encoding="utf-8")
    with pytest.raises(AgenteError) as e:
        cargar_prompt("v", tmp_path)
    assert e.value.codigo == "prompt_vacio"


def test_prompt_real_del_estratega_carga_y_es_estable():
    # Dos lecturas devuelven el mismo texto (prefijo idéntico para el caché de Groq) y sin comentarios.
    a, b = cargar_prompt("estratega"), cargar_prompt("estratega")
    assert a == b and "<!--" not in a and "angulo" in a


# ---------------------------- extraer_json ----------------------------

def test_extraer_json_plano_y_con_valla():
    assert extraer_json('{"a": 1}') == {"a": 1}
    assert extraer_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extraer_json_invalido_lanza_valueerror():
    with pytest.raises(ValueError):
        extraer_json("no es json")


# ---------------------------- pedir_json ----------------------------

def test_valida_a_la_primera():
    c = ClienteFalso(['{"a": 1}'])
    dato, resp = _correr(c)
    assert dato == {"a": 1} and resp.modelo == "modelo-x" and len(c.vistos) == 1


def test_reintenta_con_json_roto_y_corrige():
    c = ClienteFalso(['{"a"', '{"a": 2}'])
    dato, _ = _correr(c)
    assert dato == {"a": 2} and len(c.vistos) == 2
    # El reintento incluye la respuesta mala y los motivos, y no altera el diálogo original.
    segundo = c.vistos[1]
    assert segundo[-2] == {"role": "assistant", "content": '{"a"'}
    assert "no es JSON válido" in segundo[-1]["content"]
    assert len(c.vistos[0]) == 1


def test_reintenta_si_el_validador_rechaza():
    c = ClienteFalso(['{"b": 1}', '{"a": 1}'])
    dato, _ = _correr(c)
    assert dato == {"a": 1}
    assert "falta 'a'" in c.vistos[1][-1]["content"]


def test_agota_reintentos_con_salida_invalida():
    c = ClienteFalso(['{"b": 1}', '{"b": 2}'])
    with pytest.raises(AgenteError) as e:
        _correr(c, reintentos=1)
    assert e.value.codigo == "salida_invalida" and "falta 'a'" in e.value.mensaje
    assert len(c.vistos) == 2  # un intento inicial y un solo reintento


def test_truncada_no_se_reintenta():
    c = ClienteFalso([('{"a": 1', "length")])
    with pytest.raises(AgenteError) as e:
        _correr(c)
    assert e.value.codigo == "salida_truncada" and len(c.vistos) == 1


def test_respuesta_vacia_cuenta_como_truncada():
    c = ClienteFalso(["   "])
    with pytest.raises(AgenteError) as e:
        _correr(c)
    assert e.value.codigo == "salida_truncada"