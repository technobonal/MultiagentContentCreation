"""Pruebas de app.agentes.comun: cargador de prompts, extracción de JSON y pedir_json.

Sin red: se usa un cliente falso con la misma interfaz `completar`. Los casos async corren con
asyncio.run para no depender de ningún plugin de pytest.

`validar_ultimo` (validador tolerante del último intento) tiene su propio bloque de pruebas al final.
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
    assert "respuesta válida" in e.value.mensaje  # el JSON sí era válido: lo que falló fue el contenido
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


# ---------------------------- pedir_json: validar_ultimo (validador tolerante) ----------------------------

def _cualquier_objeto(d):
    """Validador tolerante de prueba: acepta cualquier objeto JSON (perdona lo que `_ok` exige)."""
    return [] if isinstance(d, dict) else ["debe ser un objeto"]


def test_tolerante_acepta_en_el_ultimo_intento_lo_que_el_estricto_rechazo():
    c = ClienteFalso(['{"b": 1}', '{"b": 2}'])
    dato, _ = _correr(c, validar_ultimo=_cualquier_objeto)
    assert dato == {"b": 2} and len(c.vistos) == 2  # el primero lo rechazó el estricto; el segundo, el tolerante
    # El reintento sí recibió el motivo del validador estricto.
    assert "falta 'a'" in c.vistos[1][-1]["content"]


def test_cada_validador_se_usa_en_su_intento():
    estrictos: list = []
    tolerantes: list = []

    def estricto(d):
        """Anota lo que recibe y rechaza siempre, para forzar el reintento."""
        estrictos.append(d)
        return ["rechazo estricto"]

    def tolerante(d):
        """Anota lo que recibe y acepta."""
        tolerantes.append(d)
        return []

    c = ClienteFalso(['{"n": 1}', '{"n": 2}'])
    asyncio.run(pedir_json(c, "r", [{"role": "user", "content": "x"}], estricto, max_tokens=10, validar_ultimo=tolerante))
    # El estricto solo vio el intento inicial; el tolerante, solo el último.
    assert estrictos == [{"n": 1}] and tolerantes == [{"n": 2}]


def test_sin_validador_tolerante_todos_los_intentos_usan_el_estricto():
    c = ClienteFalso(['{"b": 1}', '{"b": 2}'])
    with pytest.raises(AgenteError) as e:
        _correr(c, validar_ultimo=None)
    assert e.value.codigo == "salida_invalida" and len(c.vistos) == 2


def test_con_cero_reintentos_el_unico_intento_es_el_ultimo():
    c = ClienteFalso(['{"b": 1}'])
    dato, _ = _correr(c, reintentos=0, validar_ultimo=_cualquier_objeto)
    assert dato == {"b": 1} and len(c.vistos) == 1  # el tolerante se aplica de inmediato


def test_si_el_tolerante_tambien_rechaza_falla_con_sus_motivos():
    c = ClienteFalso(['{"b": 1}', '{"b": 2}'])
    with pytest.raises(AgenteError) as e:
        _correr(c, validar_ultimo=lambda d: ["sigue mal"])
    # El mensaje final lleva los motivos del último intento, que son los del validador tolerante.
    assert e.value.codigo == "salida_invalida" and "sigue mal" in e.value.mensaje
    assert "falta 'a'" not in e.value.mensaje and len(c.vistos) == 2


def test_json_roto_en_el_ultimo_intento_falla_aunque_haya_tolerante():
    c = ClienteFalso(['{"a"', '{"a"'])
    with pytest.raises(AgenteError) as e:
        _correr(c, validar_ultimo=_cualquier_objeto)
    # El validador tolerante no llega a ejecutarse: el JSON ni siquiera se pudo leer.
    assert e.value.codigo == "salida_invalida" and "no es JSON válido" in e.value.mensaje


def test_la_salida_truncada_sigue_sin_reintentarse_con_tolerante():
    c = ClienteFalso([('{"a": 1', "length")])
    with pytest.raises(AgenteError) as e:
        _correr(c, validar_ultimo=_cualquier_objeto)
    assert e.value.codigo == "salida_truncada" and len(c.vistos) == 1