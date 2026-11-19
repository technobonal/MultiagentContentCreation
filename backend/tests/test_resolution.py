"""Pruebas de app/resolution.py: carga del catálogo, reglas contra una plantilla y elección Auto/Fijo.

Dos bloques:
  1. Unitarias con fichas sintéticas en memoria (no dependen del catálogo real).
  2. Contra el catálogo y los ejemplos reales de contracts/ (los tests con "real" en el nombre),
     incluida la paridad con contracts/validate.py para que las dos implementaciones no se separen.
"""

import dataclasses
import importlib.util
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app import config
from app.resolution import Resolucion, cargar_fichas, errores_de_plantilla, resolver

# Plantilla del MVP que debe existir en el catálogo real.
PLANTILLA_MVP = "ig_carrusel_pasos_oscuro_6slides"


# --------------------------------------------------------------------------------------
# Ayudas para armar datos de prueba
# --------------------------------------------------------------------------------------

def hacer_ficha(
    pid: str,
    num_slides: int = 6,
    idiomas: tuple = ("es", "pt-BR"),
    plataforma: str = "instagram",
    formato: str = "carrusel_1080x1350",
    campos_imagen: tuple = (),
) -> dict:
    """Arma una ficha mínima con las claves que lee resolution.py (no es una ficha completa del contrato)."""
    slides = []
    for numero in range(1, num_slides + 1):  # un slide por número, desde 1
        campos = [{"nombre": "{{titulo}}", "tipo": "texto"}]
        if numero == 1:  # los campos de imagen se declaran en el primer slide
            for nombre in campos_imagen:
                campos.append({"nombre": "{{" + nombre + "}}", "tipo": "imagen"})
        slides.append({"numero": numero, "campos": campos})
    return {"id": pid, "plataforma": plataforma, "formato": formato, "idiomas": list(idiomas), "slides": slides}


def hacer_entrada(
    idioma: str = "es",
    num_slides: dict | None = None,
    plantilla: dict | None = None,
    imagenes: list | None = None,
    red: str = "instagram",
    formato: str = "carrusel_1080x1350",
) -> dict:
    """Arma una entrada con la forma que lee resolution.py (los opcionales solo si se pasan)."""
    destino = {"red": red, "formato": formato}
    if num_slides is not None:  # num_slides es opcional en el contrato
        destino["num_slides"] = num_slides
    entrada = {"fuente": {"idioma_salida": idioma}, "destino": destino}
    if plantilla is not None:  # sin "diseno" la plantilla es auto
        entrada["diseno"] = {"plantilla": plantilla}
    if imagenes is not None:  # sin "recursos" no hay imágenes del usuario
        entrada["recursos"] = {"imagenes": imagenes}
    return entrada


def escribir_ficha(carpeta, nombre_carpeta: str, ficha: dict) -> None:
    """Escribe <carpeta>/<nombre_carpeta>/card.json con la ficha dada."""
    destino = carpeta / nombre_carpeta
    destino.mkdir(parents=True)
    (destino / "card.json").write_text(json.dumps(ficha), encoding="utf-8")


# --------------------------------------------------------------------------------------
# cargar_fichas
# --------------------------------------------------------------------------------------

def test_cargar_fichas_indexa_por_id_y_quita_el_comment_raiz(tmp_path):
    """Cada ficha queda indexada por su id y sin el $comment de la raíz."""
    ficha = hacer_ficha("plantilla_a_6slides")
    ficha["$comment"] = "documentación, no parte de la ficha"
    escribir_ficha(tmp_path, "carpeta_cualquiera", ficha)
    fichas = cargar_fichas(tmp_path)
    assert list(fichas) == ["plantilla_a_6slides"]  # la clave es el id, no la carpeta
    assert "$comment" not in fichas["plantilla_a_6slides"]


def test_cargar_fichas_usa_el_nombre_de_carpeta_si_falta_el_id(tmp_path):
    """Una ficha sin id se indexa por el nombre de su carpeta."""
    ficha = hacer_ficha("x")
    ficha.pop("id")
    escribir_ficha(tmp_path, "carpeta_sin_id", ficha)
    assert list(cargar_fichas(tmp_path)) == ["carpeta_sin_id"]


def test_cargar_fichas_en_carpeta_vacia_devuelve_un_diccionario_vacio(tmp_path):
    """Sin ningún card.json no hay fichas (y no es un error de carga)."""
    assert cargar_fichas(tmp_path) == {}


def test_cargar_fichas_con_json_roto_sube_el_error(tmp_path):
    """Un JSON roto no se ignora: sube como error visible."""
    destino = tmp_path / "rota"
    destino.mkdir()
    (destino / "card.json").write_text("{esto no es json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        cargar_fichas(tmp_path)


def test_cargar_fichas_ignora_carpetas_sin_card_json(tmp_path):
    """Una carpeta del catálogo sin card.json (por ejemplo, en construcción) no rompe la carga."""
    (tmp_path / "vacia").mkdir()
    escribir_ficha(tmp_path, "ok", hacer_ficha("plantilla_ok_6slides"))
    assert list(cargar_fichas(tmp_path)) == ["plantilla_ok_6slides"]


# --------------------------------------------------------------------------------------
# errores_de_plantilla
# --------------------------------------------------------------------------------------

def test_entrada_compatible_no_produce_errores():
    """Idioma probado, sin num_slides fijo y sin imágenes: nada que reportar."""
    assert errores_de_plantilla(hacer_entrada(), hacer_ficha("p_6slides")) == []


def test_num_slides_fijo_distinto_al_de_la_plantilla_es_un_error():
    """Un num_slides fijo en 5 contra una plantilla de 6 slides se rechaza con el mensaje del contrato."""
    entrada = hacer_entrada(num_slides={"modo": "fijo", "valor": 5})
    errores = errores_de_plantilla(entrada, hacer_ficha("p_6slides", num_slides=6))
    assert errores == ["plantilla fija de 6 slides contra num_slides fijo en 5"]


def test_num_slides_fijo_igual_al_de_la_plantilla_pasa():
    """Un num_slides fijo que coincide con la plantilla no es un error."""
    entrada = hacer_entrada(num_slides={"modo": "fijo", "valor": 6})
    assert errores_de_plantilla(entrada, hacer_ficha("p_6slides", num_slides=6)) == []


def test_num_slides_en_auto_no_se_compara_con_la_plantilla():
    """Con num_slides en auto manda la plantilla: el número no genera error."""
    entrada = hacer_entrada(num_slides={"modo": "auto"})
    assert errores_de_plantilla(entrada, hacer_ficha("p_7slides", num_slides=7)) == []


def test_idioma_no_probado_en_la_plantilla_es_un_error():
    """Una plantilla probada solo en español no sirve para pt-BR."""
    ficha = hacer_ficha("p_6slides", idiomas=("es",))
    errores = errores_de_plantilla(hacer_entrada(idioma="pt-BR"), ficha)
    assert errores == ["la plantilla p_6slides no fue probada en el idioma pt-BR"]


def test_imagen_con_rol_no_declarado_es_un_error():
    """Una foto cuyo rol no es un campo de imagen de la plantilla se rechaza (regla 7)."""
    entrada = hacer_entrada(imagenes=[{"archivo": "foto.png", "rol": "imagen_producto"}])
    errores = errores_de_plantilla(entrada, hacer_ficha("p_6slides"))
    assert errores == ["la imagen foto.png apunta al rol 'imagen_producto', que la plantilla no declara"]


def test_imagen_con_rol_declarado_pasa_aunque_la_ficha_lo_escriba_con_llaves():
    """La ficha declara '{{imagen_producto}}' y la entrada 'imagen_producto': deben encajar."""
    entrada = hacer_entrada(imagenes=[{"archivo": "foto.png", "rol": "imagen_producto"}])
    ficha = hacer_ficha("p_6slides", campos_imagen=("imagen_producto",))
    assert errores_de_plantilla(entrada, ficha) == []


def test_los_errores_se_acumulan():
    """Con varias reglas rotas a la vez se reportan todas, no solo la primera."""
    entrada = hacer_entrada(
        idioma="pt-BR",
        num_slides={"modo": "fijo", "valor": 7},
        imagenes=[{"archivo": "a.png", "rol": "uno"}, {"archivo": "b.png", "rol": "dos"}],
    )
    ficha = hacer_ficha("p_6slides", idiomas=("es",))
    assert len(errores_de_plantilla(entrada, ficha)) == 4  # slides + idioma + 2 imágenes


# --------------------------------------------------------------------------------------
# resolver: modo fijo
# --------------------------------------------------------------------------------------

def test_plantilla_fija_existente_se_resuelve_en_modo_fijo():
    """El usuario fija una plantilla del catálogo: se respeta y el número de slides sale de la ficha."""
    fichas = {"p_6slides": hacer_ficha("p_6slides", num_slides=6)}
    entrada = hacer_entrada(plantilla={"modo": "fijo", "valor": "p_6slides"})
    resolucion, errores = resolver(entrada, fichas)
    assert errores == []
    assert (resolucion.plantilla_id, resolucion.modo_plantilla, resolucion.num_slides) == ("p_6slides", "fijo", 6)
    assert resolucion.ficha is fichas["p_6slides"]  # devuelve la ficha del catálogo, sin copiarla


def test_plantilla_fija_inexistente_devuelve_error_y_ninguna_resolucion():
    """Una plantilla fija que no está en el catálogo es un error visible."""
    entrada = hacer_entrada(plantilla={"modo": "fijo", "valor": "no_existe_6slides"})
    resolucion, errores = resolver(entrada, {"otra_6slides": hacer_ficha("otra_6slides")})
    assert resolucion is None
    assert errores == ["plantilla fija inexistente en templates/catalog: no_existe_6slides"]


def test_plantilla_fija_que_contradice_la_entrada_devuelve_los_errores():
    """Plantilla fija de 6 slides con num_slides fijo en 5: se rechaza y no se elige otra por su cuenta."""
    fichas = {"p_6slides": hacer_ficha("p_6slides"), "p_5slides": hacer_ficha("p_5slides", num_slides=5)}
    entrada = hacer_entrada(
        num_slides={"modo": "fijo", "valor": 5},
        plantilla={"modo": "fijo", "valor": "p_6slides"},
    )
    resolucion, errores = resolver(entrada, fichas)
    assert resolucion is None  # aunque p_5slides sí encajaría, el usuario fijó otra
    assert errores == ["plantilla fija de 6 slides contra num_slides fijo en 5"]


# --------------------------------------------------------------------------------------
# resolver: modo auto
# --------------------------------------------------------------------------------------

def test_sin_diseno_la_plantilla_es_auto():
    """Una entrada sin 'diseno' se trata como auto y elige del catálogo."""
    fichas = {"p_6slides": hacer_ficha("p_6slides")}
    resolucion, errores = resolver(hacer_entrada(), fichas)
    assert errores == []
    assert resolucion.modo_plantilla == "auto"


def test_auto_elige_la_primera_compatible_por_orden_de_id():
    """Con varias compatibles gana la de id menor, aunque el diccionario venga en otro orden."""
    fichas = {
        "zeta_6slides": hacer_ficha("zeta_6slides"),
        "alfa_6slides": hacer_ficha("alfa_6slides"),
        "medio_6slides": hacer_ficha("medio_6slides"),
    }
    resolucion, _ = resolver(hacer_entrada(), fichas)
    assert resolucion.plantilla_id == "alfa_6slides"  # repetible: mismo resultado en cada ejecución


def test_auto_salta_las_incompatibles_por_idioma():
    """Una plantilla no probada en el idioma pedido se salta y se elige la siguiente."""
    fichas = {
        "alfa_6slides": hacer_ficha("alfa_6slides", idiomas=("es",)),
        "beta_6slides": hacer_ficha("beta_6slides", idiomas=("es", "pt-BR")),
    }
    resolucion, _ = resolver(hacer_entrada(idioma="pt-BR"), fichas)
    assert resolucion.plantilla_id == "beta_6slides"


def test_auto_con_num_slides_fijo_elige_la_plantilla_con_ese_numero():
    """Con num_slides fijo en 7 y plantilla auto, solo sirve una plantilla de 7 slides."""
    fichas = {
        "alfa_6slides": hacer_ficha("alfa_6slides", num_slides=6),
        "beta_7slides": hacer_ficha("beta_7slides", num_slides=7),
    }
    resolucion, _ = resolver(hacer_entrada(num_slides={"modo": "fijo", "valor": 7}), fichas)
    assert (resolucion.plantilla_id, resolucion.num_slides) == ("beta_7slides", 7)


def test_auto_respeta_la_red_y_el_formato_de_la_ficha():
    """Una plantilla de otra red o de otro formato nunca es candidata."""
    fichas = {
        "alfa_6slides": hacer_ficha("alfa_6slides", plataforma="linkedin"),
        "beta_6slides": hacer_ficha("beta_6slides", formato="otro_formato"),
    }
    resolucion, errores = resolver(hacer_entrada(), fichas)
    assert resolucion is None
    assert len(errores) == 1


def test_auto_sin_candidatas_devuelve_un_unico_error_visible():
    """Si nada encaja no se elige 'la más parecida': error claro y ninguna resolución."""
    fichas = {"alfa_6slides": hacer_ficha("alfa_6slides", idiomas=("es",))}
    resolucion, errores = resolver(hacer_entrada(idioma="pt-BR"), fichas)
    assert resolucion is None
    assert errores == ["ninguna plantilla del catálogo cumple la entrada (red, idioma, número de slides o imágenes)"]


def test_auto_con_catalogo_vacio_devuelve_error():
    """Un catálogo sin fichas tampoco puede resolver nada."""
    resolucion, errores = resolver(hacer_entrada(), {})
    assert resolucion is None
    assert errores


def test_la_resolucion_es_inmutable():
    """Resolucion es un dataclass congelado: nadie cambia la decisión después de tomarla."""
    resolucion, _ = resolver(hacer_entrada(), {"p_6slides": hacer_ficha("p_6slides")})
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolucion.num_slides = 7
    assert isinstance(resolucion, Resolucion)


# --------------------------------------------------------------------------------------
# Contra el catálogo y los ejemplos reales
# --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fichas_reales():
    """Fichas del catálogo real (templates/catalog)."""
    return cargar_fichas()


@pytest.fixture(scope="module")
def validate_py():
    """Importa contracts/validate.py como módulo (no es un paquete) para reutilizar sus funciones."""
    ruta = config.CONTRATOS_DIR / "validate.py"
    spec = importlib.util.spec_from_file_location("contracts_validate", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # el bloque __main__ no corre al importar
    return modulo


def cargar_ejemplo(ruta) -> dict:
    """Lee un ejemplo de entrada sin su $comment raíz (el esquema no lo declara)."""
    with open(ruta, encoding="utf-8") as f:
        ejemplo = json.load(f)
    ejemplo.pop("$comment", None)
    return ejemplo


def test_catalogo_real_contiene_la_plantilla_del_mvp(fichas_reales):
    """El catálogo real carga y trae la plantilla de 6 slides del MVP, con su id y sus slides."""
    assert PLANTILLA_MVP in fichas_reales
    assert fichas_reales[PLANTILLA_MVP]["id"] == PLANTILLA_MVP
    assert len(fichas_reales[PLANTILLA_MVP]["slides"]) == 6


def test_entrada_minima_real_resuelve_en_auto_a_la_plantilla_del_mvp(fichas_reales):
    """valido_minimo_todo_auto: sin fijos, el sistema elige la única plantilla del MVP con 6 slides."""
    entrada = cargar_ejemplo(config.CONTRATOS_DIR / "input" / "examples" / "valido_minimo_todo_auto.json")
    resolucion, errores = resolver(entrada, fichas_reales)
    assert errores == []
    assert (resolucion.plantilla_id, resolucion.modo_plantilla, resolucion.num_slides) == (PLANTILLA_MVP, "auto", 6)


def test_entrada_con_fijos_real_resuelve_en_fijo(fichas_reales):
    """valido_url_con_fijos: plantilla fija de 6 slides, num_slides fijo en 6 e idioma pt-BR."""
    entrada = cargar_ejemplo(config.CONTRATOS_DIR / "input" / "examples" / "valido_url_con_fijos.json")
    resolucion, errores = resolver(entrada, fichas_reales)
    assert errores == []
    assert (resolucion.plantilla_id, resolucion.modo_plantilla, resolucion.num_slides) == (PLANTILLA_MVP, "fijo", 6)


def ejemplos_reales():
    """Lista las rutas de todos los ejemplos de entrada (para parametrizar la prueba de paridad)."""
    return sorted((config.CONTRATOS_DIR / "input" / "examples").glob("*.json"))


@pytest.mark.parametrize("ruta", ejemplos_reales(), ids=lambda r: r.name)
def test_paridad_real_con_validate_py(ruta, fichas_reales, validate_py):
    """Los ejemplos reales: el veredicto (forma + resolución) coincide con su nombre valido_/invalido_,
    y con plantilla fija los mensajes de resolution.py son los mismos que los de validate.py."""
    # Mismo validador de forma que usa validate.py (registro de $id y comprobación de formatos).
    _, registro = validate_py.cargar_esquemas()
    esquema = validate_py.cargar(config.CONTRATOS_DIR / "input" / "input.schema.json")
    validador = Draft202012Validator(esquema, registry=registro, format_checker=FormatChecker())

    entrada = cargar_ejemplo(ruta)
    errores_forma = list(validador.iter_errors(entrada))
    errores_resolucion = []
    # La resolución solo se aplica a entradas que ya pasaron el esquema (así lo documenta resolution.py).
    if not errores_forma:
        _, errores_resolucion = resolver(entrada, fichas_reales)
        # Con plantilla fija, validate.py y resolution.py deben decir exactamente lo mismo.
        if entrada.get("diseno", {}).get("plantilla", {}).get("modo") == "fijo":
            fichas_validate = validate_py.cargar_fichas()
            assert errores_resolucion == validate_py.reglas_cruzadas(entrada, fichas_validate)

    es_valida = not errores_forma and not errores_resolucion
    # El prefijo del nombre es la convención del proyecto: valido_* pasan, invalido_* se rechazan.
    assert es_valida == ruta.name.startswith("valido_"), f"{ruta.name}: veredicto inesperado"