"""Pruebas de app/runs/contexto_real.py y de MODO_RUN / MAX_RUNS_ACTIVOS en app/config.py.

Cómo están hechas:
  - Todo usa carpetas temporales (tmp_path) y claves falsas: no se toca el kit real ni hay red.
  - Las de config recargan el módulo con importlib.reload (los valores se leen al importar) y,
    al terminar, lo recargan con el entorno original para no contaminar otras pruebas.
  - Las de cerrar() son síncronas y envuelven la corutina en asyncio.run.
"""

import asyncio
import dataclasses
import importlib
import json

import pytest

from app import config
from app.agentes.cliente_llm import ClienteGroq, LLMError
from app.runs import contexto_real
from app.runs.contexto_real import (
    ORIGEN_REAL,
    ContextoReal,
    ContextoRealError,
    cargar_kit,
    construir_contexto,
)

KIT = {"paleta": {"fondo": "#112233", "texto": "#ffffff"}, "tipografia": {"titulo": "Inter"}}
CLAVE = "clave-secreta-xyz"  # texto que jamás debe aparecer en un repr ni en un mensaje de error


# --------------------------------------------------------------------------------------
# Ayudas y fixtures
# --------------------------------------------------------------------------------------

class ClienteFalso:
    """Cliente mínimo (sin red): solo guarda un `sdk` opcional para probar el cierre."""

    def __init__(self, sdk=None):
        self.sdk = sdk


@pytest.fixture
def carpeta_kits(tmp_path, monkeypatch):
    """Apunta la configuración a una carpeta temporal con el kit 'kit_prueba' ya escrito."""
    (tmp_path / "kit_prueba.json").write_text(json.dumps(KIT), encoding="utf-8")
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)
    monkeypatch.setattr(config, "KIT_MARCA", "kit_prueba")
    return tmp_path


@pytest.fixture
def recargar_config(monkeypatch):
    """Devuelve una función que fija variables de entorno (None = borrar) y recarga config.py."""
    # Sin esto, un .env de la raíz podría volver a definir las variables que la prueba borra.
    try:
        import dotenv

        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    except ImportError:
        pass  # sin python-dotenv, config.py ya ignora el .env

    def recargar(**entorno):
        """Aplica el entorno y recarga config; si MODO_RUN es inválido, la recarga lanza ValueError."""
        for nombre, valor in entorno.items():
            # None significa "que la variable no exista".
            if valor is None:
                monkeypatch.delenv(nombre, raising=False)
            else:
                monkeypatch.setenv(nombre, valor)
        return importlib.reload(config)

    yield recargar
    monkeypatch.undo()  # devuelve el entorno y los atributos originales...
    importlib.reload(config)  # ...y deja config.py como estaba antes de la prueba


# --------------------------------------------------------------------------------------
# ORIGEN_REAL
# --------------------------------------------------------------------------------------

def test_el_origen_de_una_ejecucion_real_es_real():
    """El origen que llevan los eventos reales es 'real' (el relleno usa 'grabado')."""
    assert ORIGEN_REAL == "real"


# --------------------------------------------------------------------------------------
# cargar_kit
# --------------------------------------------------------------------------------------

def test_cargar_kit_lee_el_kit_configurado(carpeta_kits):
    """Sin parámetros lee KITS_DIR/KIT_MARCA.json de la configuración."""
    assert cargar_kit() == KIT


def test_cargar_kit_acepta_nombre_y_carpeta_explicitos(tmp_path):
    """Con nombre y carpeta explícitos no depende de la configuración."""
    (tmp_path / "otro.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert cargar_kit("otro", tmp_path) == {"a": 1}


def test_cargar_kit_tolera_el_bom_que_deja_powershell(tmp_path):
    """Un kit guardado con BOM UTF-8 se lee igual."""
    (tmp_path / "bom.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(KIT).encode("utf-8"))
    assert cargar_kit("bom", tmp_path) == KIT


def test_cargar_kit_inexistente_da_error_sin_mostrar_rutas(tmp_path):
    """Un kit que no existe da kit_no_encontrado y el mensaje no filtra la ruta del servidor."""
    with pytest.raises(ContextoRealError) as exc:
        cargar_kit("no_existe", tmp_path)
    assert exc.value.codigo == "kit_no_encontrado"
    assert "no_existe" in exc.value.mensaje
    assert str(tmp_path) not in exc.value.mensaje


@pytest.mark.parametrize("nombre", ["../mvp", "a/b", "a\\b", "c:mvp", "..", ".", "", "   "])
def test_cargar_kit_rechaza_nombres_que_no_son_un_nombre_simple(tmp_path, nombre):
    """Rutas, unidades de disco, '..' y nombres vacíos se rechazan antes de tocar el disco."""
    with pytest.raises(ContextoRealError) as exc:
        cargar_kit(nombre, tmp_path)
    assert exc.value.codigo == "kit_invalido"


def test_cargar_kit_con_json_mal_formado_indica_donde(tmp_path):
    """Un JSON roto da kit_json_invalido con la posición del error."""
    (tmp_path / "roto.json").write_text('{"paleta": ', encoding="utf-8")
    with pytest.raises(ContextoRealError) as exc:
        cargar_kit("roto", tmp_path)
    assert exc.value.codigo == "kit_json_invalido"
    assert "línea" in exc.value.mensaje and "columna" in exc.value.mensaje


def test_cargar_kit_con_bytes_que_no_son_utf8_da_kit_no_legible(tmp_path):
    """Un archivo que no se puede decodificar como UTF-8 da kit_no_legible."""
    (tmp_path / "binario.json").write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(ContextoRealError) as exc:
        cargar_kit("binario", tmp_path)
    assert exc.value.codigo == "kit_no_legible"


@pytest.mark.parametrize("contenido", ["[]", '"texto"', "123", "null", "{}"], ids=["lista", "texto", "numero", "nulo", "vacio"])
def test_cargar_kit_exige_un_objeto_con_contenido(tmp_path, contenido):
    """Un JSON válido que no es un objeto, o es un objeto vacío, no sirve como kit."""
    (tmp_path / "malo.json").write_text(contenido, encoding="utf-8")
    with pytest.raises(ContextoRealError) as exc:
        cargar_kit("malo", tmp_path)
    assert exc.value.codigo == "kit_invalido"


def test_cargar_kit_lee_la_configuracion_en_cada_llamada(tmp_path, monkeypatch):
    """KITS_DIR y KIT_MARCA se leen al llamar (no al importar), así que monkeypatch funciona."""
    (tmp_path / "uno.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
    (tmp_path / "dos.json").write_text(json.dumps({"n": 2}), encoding="utf-8")
    monkeypatch.setattr(config, "KITS_DIR", tmp_path)
    resultados = []
    # Cada vuelta cambia el kit configurado y comprueba que se lee el nuevo.
    for nombre in ("uno", "dos"):
        monkeypatch.setattr(config, "KIT_MARCA", nombre)
        resultados.append(cargar_kit())
    assert resultados == [{"n": 1}, {"n": 2}]


# --------------------------------------------------------------------------------------
# construir_contexto
# --------------------------------------------------------------------------------------

def test_construir_contexto_arma_el_cliente_groq_y_el_kit(carpeta_kits, monkeypatch):
    """Con clave y kit válidos devuelve un ContextoReal con un ClienteGroq y el kit cargado."""
    monkeypatch.setattr(config, "GROQ_API_KEY", CLAVE)
    contexto = construir_contexto()
    assert isinstance(contexto, ContextoReal)
    assert isinstance(contexto.cliente, ClienteGroq)
    assert contexto.kit == KIT


def test_construir_contexto_sin_clave_falla_al_construirse(carpeta_kits, monkeypatch):
    """Sin GROQ_API_KEY el contexto no se arma: LLMError 'sin_clave' (el servidor no arranca)."""
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    with pytest.raises(LLMError) as exc:
        construir_contexto()
    assert exc.value.codigo == "sin_clave"


def test_construir_contexto_con_kit_inexistente_falla_al_construirse(carpeta_kits, monkeypatch):
    """Con clave pero sin kit tampoco se arma: ContextoRealError 'kit_no_encontrado'."""
    monkeypatch.setattr(config, "GROQ_API_KEY", CLAVE)
    monkeypatch.setattr(config, "KIT_MARCA", "no_existe")
    with pytest.raises(ContextoRealError) as exc:
        construir_contexto()
    assert exc.value.codigo == "kit_no_encontrado"


def test_construir_contexto_usa_el_cliente_y_el_kit_inyectados(monkeypatch):
    """Con cliente y kit inyectados no toca ni la clave ni el disco (así lo usan las pruebas de la ruta)."""
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "KITS_DIR", config.RAIZ_PROYECTO / "no_existe")
    cliente = ClienteFalso()
    contexto = construir_contexto(cliente=cliente, kit={"paleta": {}})
    assert contexto.cliente is cliente
    assert contexto.kit == {"paleta": {}}


# --------------------------------------------------------------------------------------
# ContextoReal
# --------------------------------------------------------------------------------------

def test_kit_para_run_entrega_una_copia_independiente():
    """Cada run recibe su copia: modificarla (incluso en profundidad) no cambia el kit compartido ni otras copias."""
    contexto = ContextoReal(cliente=ClienteFalso(), kit=json.loads(json.dumps(KIT)))
    copia = contexto.kit_para_run()
    otra = contexto.kit_para_run()
    copia["paleta"]["fondo"] = "#000000"  # cambio anidado
    copia["nuevo"] = True
    assert contexto.kit == KIT
    assert otra == KIT
    assert copia is not otra and copia["paleta"] is not otra["paleta"]


def test_el_contexto_es_inmutable():
    """El contexto es un dataclass congelado: no se pueden reasignar sus campos."""
    contexto = ContextoReal(cliente=ClienteFalso(), kit=dict(KIT))
    with pytest.raises(dataclasses.FrozenInstanceError):
        contexto.kit = {}


def test_el_repr_no_filtra_la_clave_ni_el_kit(carpeta_kits, monkeypatch):
    """Ni el repr del contexto ni los mensajes de error contienen la clave de Groq ni el contenido del kit."""
    monkeypatch.setattr(config, "GROQ_API_KEY", CLAVE)
    contexto = construir_contexto()
    assert CLAVE not in repr(contexto)
    assert "#112233" not in repr(contexto)
    monkeypatch.setattr(config, "KIT_MARCA", "no_existe")
    with pytest.raises(ContextoRealError) as exc:
        construir_contexto()
    assert CLAVE not in exc.value.mensaje


def test_cerrar_espera_el_close_asincrono_del_sdk():
    """cerrar() llama a sdk.close() y espera la corutina."""
    cerrado = []

    class SdkAsync:
        """SDK falso con un close asíncrono."""

        async def close(self):
            """Anota que se cerró."""
            cerrado.append("async")

    asyncio.run(ContextoReal(cliente=ClienteFalso(SdkAsync()), kit={"a": 1}).cerrar())
    assert cerrado == ["async"]


def test_cerrar_acepta_un_close_sincrono():
    """Si el close del SDK no es una corutina, igual se llama."""
    cerrado = []

    class SdkSincrono:
        """SDK falso con un close síncrono."""

        def close(self):
            """Anota que se cerró."""
            cerrado.append("sync")

    asyncio.run(ContextoReal(cliente=ClienteFalso(SdkSincrono()), kit={"a": 1}).cerrar())
    assert cerrado == ["sync"]


@pytest.mark.parametrize("cliente", [ClienteFalso(), ClienteFalso(sdk=object()), object()], ids=["sin_sdk", "sdk_sin_close", "sin_atributo"])
def test_cerrar_sin_nada_que_cerrar_no_falla(cliente):
    """Un cliente sin SDK, o con un SDK sin close, se ignora sin error."""
    asyncio.run(ContextoReal(cliente=cliente, kit={"a": 1}).cerrar())


def test_cerrar_cierra_de_verdad_el_cliente_groq(monkeypatch):
    """Con un ClienteGroq real (clave falsa, sin red) cerrar() cierra su cliente HTTP sin errores."""
    monkeypatch.setattr(config, "GROQ_API_KEY", CLAVE)
    asyncio.run(ContextoReal(cliente=ClienteGroq(), kit={"a": 1}).cerrar())


def test_el_modulo_no_guarda_estado_global():
    """No hay caché ni contexto a nivel de módulo (vive en app.state): lo prueba la ausencia de lru_cache."""
    assert not hasattr(contexto_real.construir_contexto, "cache_clear")
    assert not hasattr(contexto_real.cargar_kit, "cache_clear")


# --------------------------------------------------------------------------------------
# config.py: MODO_RUN y MAX_RUNS_ACTIVOS
# --------------------------------------------------------------------------------------

def test_modo_run_por_defecto_es_relleno_y_permite_3_runs(recargar_config):
    """Sin variables de entorno: modo relleno y 3 ejecuciones simultáneas (el comportamiento de siempre)."""
    cfg = recargar_config(MODO_RUN=None, MAX_RUNS_ACTIVOS=None)
    assert cfg.MODO_RUN == "relleno"
    assert cfg.MAX_RUNS_ACTIVOS == 3


def test_modo_run_vacio_cuenta_como_relleno(recargar_config):
    """Una variable definida pero vacía (típico de un .env a medio llenar) vale 'relleno'."""
    assert recargar_config(MODO_RUN="", MAX_RUNS_ACTIVOS=None).MODO_RUN == "relleno"


@pytest.mark.parametrize("valor", ["real", "REAL", "  Real  "])
def test_modo_run_se_normaliza(recargar_config, valor):
    """Mayúsculas y espacios no importan: 'REAL' y '  Real  ' son 'real'."""
    assert recargar_config(MODO_RUN=valor, MAX_RUNS_ACTIVOS=None).MODO_RUN == "real"


def test_en_modo_real_el_limite_por_defecto_baja_a_2(recargar_config):
    """Los runs reales comparten el cupo de tokens de Groq: por defecto solo 2 a la vez."""
    assert recargar_config(MODO_RUN="real", MAX_RUNS_ACTIVOS=None).MAX_RUNS_ACTIVOS == 2


def test_max_runs_activos_explicito_manda_sobre_el_default(recargar_config):
    """Si el entorno define MAX_RUNS_ACTIVOS, se respeta en cualquier modo."""
    assert recargar_config(MODO_RUN="real", MAX_RUNS_ACTIVOS="5").MAX_RUNS_ACTIVOS == 5
    assert recargar_config(MODO_RUN="relleno", MAX_RUNS_ACTIVOS="1").MAX_RUNS_ACTIVOS == 1


@pytest.mark.parametrize("valor", ["turbo", "grabado", "1", "real,relleno"])
def test_modo_run_invalido_falla_al_importar(recargar_config, valor):
    """Un MODO_RUN fuera de la lista falla al arrancar, con el nombre de la variable en el mensaje."""
    with pytest.raises(ValueError, match="MODO_RUN"):
        recargar_config(MODO_RUN=valor, MAX_RUNS_ACTIVOS=None)