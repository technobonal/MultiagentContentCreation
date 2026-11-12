"""Validador de los contratos de la Fase 0.

Comprueba, en este orden:
  1. Que todos los esquemas sean JSON Schema 2020-12 bien formados y que sus $ref resuelvan.
  2. Que cada bloque de cada esquema tenga su `$comment` (explica qué hace).
  3. Que el catálogo de eventos sea coherente (envelope, despachador y un esquema por evento).
  4. Los ejemplos de entrada: los `valido_*` pasan y los `invalido_*` son rechazados.
  5. La ficha de plantilla y el kit de marca (con los contrastes recalculados).
  6. La secuencia grabada: orden por seq, causas, citas literales, sello y estado final.
  7. Pruebas negativas: eventos mutados a propósito que DEBEN ser rechazados.

Uso:  python contracts/validate.py        (sale con código 1 si hay alguna falla)
"""

import copy
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

# Carpeta contracts/ (donde vive este archivo) y raíz del proyecto.
CONTRATOS = Path(__file__).resolve().parent
PROYECTO = CONTRATOS.parent

# Claves que, solas, describen un bloque "hoja" (una restricción simple): no necesita $comment.
CLAVES_HOJA = {
    "type", "const", "enum", "$ref", "description", "$comment", "minimum", "maximum",
    "minLength", "maxLength", "pattern", "format", "minItems", "maxItems", "uniqueItems", "default",
}

# Resultados acumulados: lista de (estado, título, detalles). Estado: OK, FALLA o aviso.
RESULTADOS = []


def registrar(estado, titulo, detalles=()):
    """Guarda el resultado de una comprobación para imprimirlo al final."""
    RESULTADOS.append((estado, titulo, list(detalles)))


def cargar(ruta):
    """Lee un archivo JSON y devuelve su contenido ya convertido a Python."""
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def sin_comentario_raiz(instancia):
    """Devuelve una copia de la instancia sin su `$comment` raíz.

    Los archivos de ejemplo llevan un `$comment` de documentación en la raíz; los
    esquemas (additionalProperties: false) no lo declaran, así que se quita antes de validar.
    """
    copia = copy.deepcopy(instancia)
    if isinstance(copia, dict):  # solo los objetos pueden tener la clave
        copia.pop("$comment", None)
    return copia


def resumir_errores(validador, instancia, limite=6):
    """Devuelve hasta `limite` mensajes de error legibles de validar `instancia`."""
    mensajes = []
    # Se ordenan por ruta para que la salida sea estable entre ejecuciones.
    for error in sorted(validador.iter_errors(instancia), key=lambda e: list(map(str, e.absolute_path))):
        ruta = "/".join(map(str, error.absolute_path)) or "(raíz)"
        mensajes.append(f"{ruta}: {error.message[:150]}")
        if len(mensajes) >= limite:  # evita inundar la consola con un esquema muy roto
            break
    return mensajes


# --------------------------------------------------------------------------------------
# 1. Esquemas
# --------------------------------------------------------------------------------------

def cargar_esquemas():
    """Carga todos los *.schema.json y construye el registro de $id para resolver $ref.

    Devuelve (esquemas_por_ruta, registro). Registra una falla por cada esquema mal formado.
    """
    esquemas = {}
    recursos = []
    problemas = []
    # Recorre todos los archivos de esquema bajo contracts/.
    for ruta in sorted(CONTRATOS.rglob("*.schema.json")):
        esquema = cargar(ruta)
        esquemas[ruta] = esquema
        try:
            Draft202012Validator.check_schema(esquema)  # comprueba que el esquema sea válido
        except Exception as exc:  # cualquier error de metaesquema es una falla
            problemas.append(f"{ruta.relative_to(PROYECTO)}: {str(exc)[:150]}")
        # Un esquema sin $id no se puede referenciar desde otros archivos.
        if "$id" not in esquema:
            problemas.append(f"{ruta.relative_to(PROYECTO)}: falta $id")
            continue
        recursos.append((esquema["$id"], Resource.from_contents(esquema)))
    registro = Registry().with_resources(recursos)
    if problemas:  # hubo al menos un esquema roto
        registrar("FALLA", f"Esquemas bien formados ({len(problemas)} problemas)", problemas)
    else:
        registrar("OK", f"Esquemas bien formados ({len(esquemas)} archivos)")
    return esquemas, registro


def es_hoja(nodo):
    """Un bloque es 'hoja' si solo usa claves de restricción simple (no necesita $comment)."""
    return set(nodo.keys()) <= CLAVES_HOJA


def recorrer_comentarios(nodo, ruta, archivo, problemas, es_raiz=False):
    """Recorre un esquema y anota los bloques que deberían tener `$comment` y no lo tienen.

    Reglas: la raíz siempre lo lleva; cualquier otro bloque lo lleva salvo que sea hoja.
    """
    if not isinstance(nodo, dict):  # los esquemas booleanos (true/false) no llevan comentario
        return
    # La raíz o un bloque compuesto sin $comment es un problema.
    if (es_raiz or not es_hoja(nodo)) and not isinstance(nodo.get("$comment"), str):
        problemas.append(f"{archivo}: bloque sin $comment en {ruta or '#'}")
    # Subesquemas directos.
    for clave in ("if", "then", "else", "items", "not", "additionalProperties", "unevaluatedProperties"):
        if clave in nodo:
            recorrer_comentarios(nodo[clave], f"{ruta}/{clave}", archivo, problemas)
    # Listas de subesquemas.
    for clave in ("allOf", "anyOf", "oneOf", "prefixItems"):
        for i, sub in enumerate(nodo.get(clave, [])):
            recorrer_comentarios(sub, f"{ruta}/{clave}/{i}", archivo, problemas)
    # Mapas de subesquemas (propiedades y definiciones).
    for clave in ("properties", "$defs"):
        for nombre, sub in nodo.get(clave, {}).items():
            recorrer_comentarios(sub, f"{ruta}/{clave}/{nombre}", archivo, problemas)


def comprobar_comentarios(esquemas):
    """Falla si algún bloque de algún esquema no tiene `$comment` (convención del proyecto)."""
    problemas = []
    for ruta, esquema in esquemas.items():
        recorrer_comentarios(esquema, "", str(ruta.relative_to(PROYECTO)), problemas, es_raiz=True)
    if problemas:
        registrar("FALLA", f"Comentarios ($comment en cada archivo y bloque) ({len(problemas)})", problemas)
    else:
        registrar("OK", "Comentarios ($comment en cada archivo y bloque)")


def comprobar_catalogo_eventos(esquemas):
    """Comprueba que envelope, despachador y archivos por evento listen los mismos tipos."""
    carpeta = CONTRATOS / "events"
    envelope = esquemas[carpeta / "envelope.schema.json"]
    evento = esquemas[carpeta / "event.schema.json"]
    # Tipos declarados en el sobre.
    tipos_envelope = set(envelope["properties"]["tipo"]["enum"])
    # Tipos con un archivo propio (todo menos envelope y event).
    tipos_archivos = {
        r.name.replace(".schema.json", "") for r in esquemas
        if r.parent == carpeta and r.name not in ("envelope.schema.json", "event.schema.json")
    }
    # Tipos que el despachador enruta (cada rama if/then con const).
    tipos_despachador = set()
    for rama in evento["allOf"][1:]:  # la primera rama es el $ref al sobre
        tipos_despachador.add(rama["if"]["properties"]["tipo"]["const"])
    problemas = []
    # Cada conjunto debe ser idéntico al del sobre.
    for nombre, conjunto in (("archivos por evento", tipos_archivos), ("despachador event.schema", tipos_despachador)):
        if conjunto != tipos_envelope:
            problemas.append(
                f"{nombre} difiere del sobre: faltan {sorted(tipos_envelope - conjunto)}, sobran {sorted(conjunto - tipos_envelope)}"
            )
    if len(tipos_envelope) != 15:  # el catálogo 0.1 está congelado en 15 eventos
        problemas.append(f"el catálogo 0.1 debe tener 15 eventos y tiene {len(tipos_envelope)}")
    if problemas:
        registrar("FALLA", "Catálogo de eventos coherente", problemas)
    else:
        registrar("OK", "Catálogo de eventos coherente (15 eventos)")


# --------------------------------------------------------------------------------------
# 2. Plantillas y entrada
# --------------------------------------------------------------------------------------

def cargar_fichas():
    """Carga todas las fichas card.json del catálogo, indexadas por su id."""
    fichas = {}
    # Una carpeta por plantilla en templates/catalog.
    for ruta in sorted((PROYECTO / "templates" / "catalog").glob("*/card.json")):
        ficha = sin_comentario_raiz(cargar(ruta))
        fichas[ficha.get("id", ruta.parent.name)] = (ruta, ficha)
    return fichas


def reglas_cruzadas(entrada, fichas):
    """Reglas de resolución que cruzan archivos (regla 3 del SPEC). Devuelve los errores."""
    errores = []
    plantilla = entrada.get("diseno", {}).get("plantilla", {})
    if plantilla.get("modo") != "fijo":  # con plantilla en auto no hay nada que cruzar
        return errores
    pid = plantilla.get("valor")
    if pid not in fichas:  # la plantilla fija debe existir en el catálogo
        errores.append(f"plantilla fija inexistente en templates/catalog: {pid}")
        return errores
    ficha = fichas[pid][1]
    n = entrada.get("destino", {}).get("num_slides", {})
    # Plantilla fija y número de slides fijo deben coincidir.
    if n.get("modo") == "fijo" and n.get("valor") != len(ficha["slides"]):
        errores.append(
            f"plantilla fija de {len(ficha['slides'])} slides contra num_slides fijo en {n.get('valor')}"
        )
    # El idioma de salida debe estar entre los idiomas probados de la plantilla.
    idioma = entrada.get("fuente", {}).get("idioma_salida")
    if idioma not in ficha["idiomas"]:
        errores.append(f"la plantilla {pid} no fue probada en el idioma {idioma}")
    # Cada imagen del usuario debe apuntar a un campo de imagen declarado en la ficha.
    campos_imagen = {
        c["nombre"].strip("{}") for s in ficha["slides"] for c in s["campos"] if c["tipo"] == "imagen"
    }
    for imagen in entrada.get("recursos", {}).get("imagenes", []):
        if imagen["rol"] not in campos_imagen:  # regla 7: la foto entra solo por un campo declarado
            errores.append(f"la imagen {imagen['archivo']} apunta al rol '{imagen['rol']}', que la plantilla no declara")
    return errores


def comprobar_ejemplos_entrada(registro, fichas):
    """Valida los ejemplos de entrada: los valido_* deben pasar y los invalido_* ser rechazados."""
    esquema = cargar(CONTRATOS / "input" / "input.schema.json")
    validador = Draft202012Validator(esquema, registry=registro, format_checker=FormatChecker())
    problemas = []
    contadores = {"valido": 0, "invalido": 0}
    for ruta in sorted((CONTRATOS / "input" / "examples").glob("*.json")):
        instancia = sin_comentario_raiz(cargar(ruta))
        errores = list(resumir_errores(validador, instancia))
        # Las reglas cruzadas solo tienen sentido si la forma ya es correcta.
        if not errores:
            errores = reglas_cruzadas(instancia, fichas)
        if ruta.name.startswith("valido_"):
            contadores["valido"] += 1
            if errores:  # un ejemplo válido fue rechazado
                problemas.append(f"{ruta.name} debía ser válido y falló: {errores[0]}")
        elif ruta.name.startswith("invalido_"):
            contadores["invalido"] += 1
            if not errores:  # un ejemplo inválido fue aceptado
                problemas.append(f"{ruta.name} debía ser rechazado y pasó la validación")
        else:  # cualquier otro nombre rompe la convención
            problemas.append(f"{ruta.name}: el nombre debe empezar con valido_ o invalido_")
    titulo = f"Ejemplos de entrada ({contadores['valido']} válidos, {contadores['invalido']} inválidos)"
    registrar("FALLA" if problemas else "OK", titulo, problemas)


def comprobar_fichas(registro, fichas):
    """Valida cada ficha de plantilla contra su esquema y sus reglas estructurales."""
    esquema = cargar(CONTRATOS / "template-card" / "card.schema.json")
    validador = Draft202012Validator(esquema, registry=registro, format_checker=FormatChecker())
    problemas = []
    avisos = []
    if not fichas:  # sin fichas no hay plantilla que validar
        registrar("FALLA", "Fichas de plantilla", ["no hay ninguna card.json en templates/catalog"])
        return
    for pid, (ruta, ficha) in fichas.items():
        # Forma de la ficha.
        for error in resumir_errores(validador, ficha):
            problemas.append(f"{pid}: {error}")
        slides = ficha.get("slides", [])
        roles = [s.get("rol") for s in slides]
        # El id debe coincidir con la carpeta y con el número de slides del nombre.
        if ficha.get("id") != ruta.parent.name:
            problemas.append(f"{pid}: el id no coincide con la carpeta {ruta.parent.name}")
        if f"{len(slides)}slides" not in pid:
            problemas.append(f"{pid}: el id declara otro número de slides que los {len(slides)} de la ficha")
        # Numeración consecutiva desde 1.
        if [s.get("numero") for s in slides] != list(range(1, len(slides) + 1)):
            problemas.append(f"{pid}: los slides no están numerados de forma consecutiva desde 1")
        # Estructura de roles: gancho, segundo gancho y fuentes al final.
        if roles[:2] != ["gancho", "segundo_gancho"]:
            problemas.append(f"{pid}: los dos primeros slides deben ser gancho y segundo_gancho")
        if roles[-1:] != ["fuentes"] or roles.count("fuentes") != 1:
            problemas.append(f"{pid}: el último (y único) slide con rol fuentes debe cerrar el carrusel")
        # Nombres de campo únicos dentro de cada slide.
        for slide in slides:
            nombres = [c["nombre"] for c in slide.get("campos", [])]
            if len(nombres) != len(set(nombres)):
                problemas.append(f"{pid}: slide {slide.get('numero')} repite nombres de campo")
        # El slide de fuentes necesita el sello calculado por código, nunca por el LLM.
        if slides and roles[-1:] == ["fuentes"]:
            sello = [c for c in slides[-1]["campos"] if c["nombre"] == "{{sello_revision}}"]
            if not sello or sello[0]["origen_valor"] != "calculado":
                problemas.append(f"{pid}: el slide de fuentes necesita {{{{sello_revision}}}} con origen_valor 'calculado'")
        # Un archivo template.svg pendiente es un aviso, no una falla (Fase 0 en curso).
        if not (ruta.parent / "template.svg").exists():
            avisos.append(f"{ruta.parent.relative_to(PROYECTO)}: falta template.svg (pendiente de la Fase 0)")
    registrar("FALLA" if problemas else "OK", f"Fichas de plantilla ({len(fichas)})", problemas)
    for aviso in avisos:  # los avisos no hacen fallar el validador
        registrar("aviso", aviso)


# --------------------------------------------------------------------------------------
# 3. Kit de marca
# --------------------------------------------------------------------------------------

def luminancia(color):
    """Luminancia relativa WCAG de un color '#RRGGBB'."""
    color = color.lstrip("#")
    canales = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lineales = []
    for c in canales:  # conversión de sRGB a lineal
        lineales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lineales[0] + 0.7152 * lineales[1] + 0.0722 * lineales[2]


def contraste(a, b):
    """Relación de contraste WCAG entre dos colores (de 1 a 21)."""
    mayor, menor = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (mayor + 0.05) / (menor + 0.05)


def comprobar_kits(registro):
    """Valida los kits de marca y recalcula sus contrastes declarados."""
    esquema = cargar(CONTRATOS / "brand-kit" / "kit.schema.json")
    validador = Draft202012Validator(esquema, registry=registro, format_checker=FormatChecker())
    problemas = []
    kits = sorted((PROYECTO / "templates" / "brand-kits").glob("*.json"))
    if not kits:  # el MVP necesita su kit
        registrar("FALLA", "Kit de marca", ["no hay ningún kit en templates/brand-kits"])
        return
    for ruta in kits:
        kit = sin_comentario_raiz(cargar(ruta))
        errores = resumir_errores(validador, kit)
        problemas.extend(f"{ruta.name}: {e}" for e in errores)
        if errores:  # sin forma correcta no se pueden recalcular los contrastes
            continue
        # Cada contraste declarado debe coincidir con el recalculado (tolerancia de 0,01).
        for par in kit["contraste_precalculado"]:
            real = contraste(kit["paleta"][par["primero"]], kit["paleta"][par["segundo"]])
            if abs(real - par["ratio"]) > 0.01:
                problemas.append(
                    f"{ruta.name}: contraste {par['primero']}/{par['segundo']} declarado {par['ratio']} y real {real:.2f}"
                )
        # Los pares de texto sobre fondo deben cumplir WCAG AA (4,5:1).
        for primero, segundo in (("texto", "fondo"), ("texto_sobre_acento", "acento")):
            real = contraste(kit["paleta"][primero], kit["paleta"][segundo])
            if real < 4.5:
                problemas.append(f"{ruta.name}: {primero} sobre {segundo} tiene contraste {real:.2f}, menor que 4,5")
    registrar("FALLA" if problemas else "OK", f"Kit de marca ({len(kits)}) con contrastes recalculados", problemas)


# --------------------------------------------------------------------------------------
# 4. Secuencia grabada
# --------------------------------------------------------------------------------------

def sello_calculado(eventos):
    """Calcula el sello (respaldadas, totales) con el último veredicto de cada afirmación factual."""
    ultimo = {}
    # Los eventos van en orden por seq, así que el último valor de cada id es el vigente.
    for e in eventos:
        if e["tipo"] == "verificacion_fidelidad" and e["payload"]["clasificacion"] == "factual":
            ultimo[e["payload"]["afirmacion_id"]] = e["payload"]["veredicto"]
    respaldadas = sum(1 for v in ultimo.values() if v == "respaldada")
    return {"afirmaciones_respaldadas": respaldadas, "afirmaciones_totales": len(ultimo)}


def hallazgos_abiertos(eventos, hasta_seq):
    """Devuelve los hallazgos (id -> gravedad) que siguen abiertos hasta el evento `hasta_seq`."""
    abiertos = {}
    for e in eventos:
        if e["seq"] > hasta_seq:  # solo se consideran los eventos ya ocurridos
            break
        if e["tipo"] == "hallazgo_abierto":
            abiertos[e["payload"]["hallazgo_id"]] = e["payload"]["gravedad"]
        elif e["tipo"] == "hallazgo_corregido" and e["payload"]["resultado"] == "corregido":
            abiertos.pop(e["payload"]["hallazgo_id"], None)
    return abiertos


def reglas_grabacion(doc, ruta, fichas):
    """Reglas de la secuencia grabada que el esquema no puede expresar. Devuelve los problemas."""
    problemas = []
    eventos = doc["eventos"]
    por_seq = {e["seq"]: e for e in eventos}
    # Secuencia consecutiva desde 1 y sin huecos.
    if [e["seq"] for e in eventos] != list(range(1, len(eventos) + 1)):
        problemas.append("los seq no son consecutivos desde 1")
        return problemas  # sin orden fiable no tiene sentido seguir
    # Inicio, fin y coherencia de origen y run_id.
    if eventos[0]["tipo"] != "run_iniciada" or eventos[-1]["tipo"] != "run_finalizada":
        problemas.append("la secuencia debe empezar en run_iniciada y terminar en run_finalizada")
    for e in eventos:
        if e["origen"] != "grabado":  # una grabación no puede hacerse pasar por real
            problemas.append(f"seq {e['seq']}: origen '{e['origen']}' en una secuencia grabada")
        if e["run_id"] != doc["run_id"]:
            problemas.append(f"seq {e['seq']}: run_id distinto al del documento")
    # Los timestamps no pueden retroceder.
    instantes = [datetime.fromisoformat(e["timestamp"]) for e in eventos]
    if instantes != sorted(instantes):
        problemas.append("los timestamps retroceden")
    # Referencias de causa.
    for e in eventos:
        causa = e.get("causa")
        if causa is None:  # no todos los eventos llevan causa
            continue
        if causa >= e["seq"] or causa not in por_seq:
            problemas.append(f"seq {e['seq']}: causa {causa} no apunta a un evento anterior")
            continue
        destino = por_seq[causa]
        if e["tipo"] == "corregir":  # corrige un escribir_texto del mismo slide y campo
            op = e["payload"]["operacion_nueva"]
            if destino["tipo"] != "escribir_texto" or destino.get("slide") != e.get("slide") or destino["payload"]["campo"] != op["campo"]:
                problemas.append(f"seq {e['seq']}: 'corregir' debe sustituir un escribir_texto del mismo slide y campo")
        elif e["tipo"] == "hallazgo_corregido":  # cierra el hallazgo con el mismo id
            if destino["tipo"] != "hallazgo_abierto" or destino["payload"]["hallazgo_id"] != e["payload"]["hallazgo_id"]:
                problemas.append(f"seq {e['seq']}: 'hallazgo_corregido' debe referenciar su hallazgo_abierto")
        elif e["tipo"] == "texto_propuesto":  # una reescritura nace de un hallazgo
            if destino["tipo"] != "hallazgo_abierto":
                problemas.append(f"seq {e['seq']}: una reescritura con causa debe apuntar a un hallazgo_abierto")
    # Coherencia con la entrada resuelta (run_iniciada), el brief y la plantilla.
    inicio = eventos[0]["payload"]
    briefs = [e for e in eventos if e["tipo"] == "brief_emitido"]
    for brief in briefs:
        if brief["payload"]["num_slides"] != inicio["num_slides"] or len(brief["payload"]["roles"]) != inicio["num_slides"]:
            problemas.append(f"seq {brief['seq']}: num_slides y roles del brief no coinciden con run_iniciada")
        if brief["payload"]["roles"][-1] != "fuentes":
            problemas.append(f"seq {brief['seq']}: el último rol del brief debe ser 'fuentes'")
    for e in eventos:
        if e["tipo"] == "plantilla_elegida":  # la plantilla elegida existe y encaja con el número de slides
            ficha = fichas.get(e["payload"]["plantilla_id"])
            if ficha is None:
                problemas.append(f"seq {e['seq']}: la plantilla {e['payload']['plantilla_id']} no existe en el catálogo")
            elif len(ficha[1]["slides"]) != inicio["num_slides"]:
                problemas.append(f"seq {e['seq']}: la plantilla tiene {len(ficha[1]['slides'])} slides y la ejecución {inicio['num_slides']}")
        if "slide" in e and e["slide"] > inicio["num_slides"]:  # ningún evento apunta a un slide inexistente
            problemas.append(f"seq {e['seq']}: slide {e['slide']} fuera del carrusel de {inicio['num_slides']} slides")
        if e["tipo"] == "editada" and e["payload"]["texto_antes"] == e["payload"]["texto_despues"]:
            problemas.append(f"seq {e['seq']}: 'editada' sin cambio de texto")
    # Fuente: se lee el archivo y se comprueban huella, tamaño y todas las citas.
    fuente_path = ruta.parent / doc["fuente_ref"]
    if not fuente_path.exists():
        problemas.append(f"no existe la fuente {doc['fuente_ref']}")
        return problemas
    fuente = fuente_path.read_text(encoding="utf-8")
    for e in eventos:
        if e["tipo"] == "fuente_indexada":  # huella y tamaño deben ser los reales
            if e["payload"]["sha256"] != hashlib.sha256(fuente.encode("utf-8")).hexdigest():
                problemas.append(f"seq {e['seq']}: el sha256 no corresponde a la fuente")
            if e["payload"]["num_caracteres"] != len(fuente):
                problemas.append(f"seq {e['seq']}: num_caracteres no corresponde a la fuente")
        if e["tipo"] == "verificacion_fidelidad" and e["payload"]["cita"] is not None:
            cita = e["payload"]["cita"]  # la cita debe ser literal y estar en la posición declarada
            if fuente[cita["inicio"]:cita["fin"]] != cita["fragmento"]:
                problemas.append(f"seq {e['seq']}: la cita no es literal en la posición {cita['inicio']}:{cita['fin']}")
    # Sello de revisión: lo calcula código y debe coincidir en los dos eventos que lo llevan.
    for e in eventos:
        if e["tipo"] in ("aprobacion_solicitada", "run_finalizada"):
            esperado = sello_calculado([x for x in eventos if x["seq"] < e["seq"]])
            if e["payload"]["sello"] != esperado:
                problemas.append(f"seq {e['seq']}: sello {e['payload']['sello']} distinto del calculado {esperado}")
    # Estado de la revisión: nada se aprueba con bloqueantes abiertos y los contadores deben ser reales.
    for e in eventos:
        if e["tipo"] == "aprobacion_solicitada":
            abiertos = hallazgos_abiertos(eventos, e["seq"])
            if e["payload"]["hallazgos_abiertos"] != len(abiertos):
                problemas.append(f"seq {e['seq']}: hallazgos_abiertos declara {e['payload']['hallazgos_abiertos']} y hay {len(abiertos)}")
            if e["payload"]["estado_revision"] == "aprobada" and "bloqueante" in abiertos.values():
                problemas.append(f"seq {e['seq']}: estado 'aprobada' con un hallazgo bloqueante abierto")
    return problemas


def comprobar_grabaciones(registro, fichas):
    """Valida cada secuencia grabada contra el esquema y sus reglas cruzadas."""
    esquema = cargar(CONTRATOS / "recordings" / "recording.schema.json")
    validador = Draft202012Validator(esquema, registry=registro, format_checker=FormatChecker())
    archivos = sorted(p for p in (CONTRATOS / "recordings").glob("*.json") if not p.name.endswith(".schema.json"))
    if not archivos:  # la Fase 0 exige al menos la secuencia B.5
        registrar("FALLA", "Secuencia grabada", ["no hay ninguna grabación en contracts/recordings"])
        return
    for ruta in archivos:
        doc = sin_comentario_raiz(cargar(ruta))
        # Los eventos de la grabación llevan su propio sobre, sin $comment, así que se valida tal cual.
        errores = resumir_errores(validador, doc)
        if errores:  # sin forma correcta no se aplican las reglas cruzadas
            registrar("FALLA", f"Secuencia grabada {ruta.name}", errores)
            continue
        problemas = reglas_grabacion(doc, ruta, fichas)
        registrar("FALLA" if problemas else "OK", f"Secuencia grabada {ruta.name} ({len(doc['eventos'])} eventos)", problemas)


# --------------------------------------------------------------------------------------
# 5. Pruebas negativas
# --------------------------------------------------------------------------------------

def comprobar_pruebas_negativas(registro):
    """Muta eventos válidos a propósito: cada mutación DEBE ser rechazada por el esquema."""
    ruta = CONTRATOS / "recordings" / "b5_cifra_inventada.json"
    if not ruta.exists():  # sin grabación no hay eventos base
        registrar("FALLA", "Pruebas negativas de eventos", ["falta b5_cifra_inventada.json"])
        return
    eventos = cargar(ruta)["eventos"]
    validador = Draft202012Validator(cargar(CONTRATOS / "events" / "event.schema.json"), registry=registro, format_checker=FormatChecker())

    def base(tipo):
        """Devuelve una copia del primer evento de ese tipo de la grabación."""
        return copy.deepcopy(next(e for e in eventos if e["tipo"] == tipo))

    casos = []  # lista de (descripción, evento mutado)
    # Regla 1: respaldada sin cita.
    e = base("verificacion_fidelidad"); e["payload"]["veredicto"] = "respaldada"; e["payload"]["cita"] = None
    casos.append(("veredicto respaldada con cita null", e))
    # Regla 2: una opinión o CTA no puede tener un veredicto factual.
    e = base("verificacion_fidelidad"); e["payload"]["clasificacion"] = "opinion_cta"
    casos.append(("opinion_cta con veredicto distinto de no_aplica", e))
    # Regla 3: no_aplica en una afirmación factual es una salida de escape.
    e = base("verificacion_fidelidad"); e["payload"]["veredicto"] = "no_aplica"; e["payload"]["cita"] = None
    casos.append(("no_aplica con clasificación factual", e))
    # Regla 4: contradice siempre es factual.
    e = base("verificacion_fidelidad"); e["payload"]["clasificacion"] = "opinion_cta"; e["payload"]["veredicto"] = "contradice"
    casos.append(("contradice con clasificación opinion_cta", e))
    # Una corrección sin causa rompe la inmutabilidad (no sabría qué sustituye).
    e = base("corregir"); e.pop("causa")
    casos.append(("corregir sin causa", e))
    # El emisor equivocado.
    e = base("colocar_fondo"); e["agente"] = "revisor"
    casos.append(("colocar_fondo emitido por el revisor", e))
    # Un tipo fuera del catálogo.
    e = base("run_iniciada"); e["tipo"] = "evento_inventado"
    casos.append(("tipo fuera del catálogo", e))
    # Un hallazgo sin acción propuesta no es explicable.
    e = base("hallazgo_abierto"); e["payload"].pop("accion")
    casos.append(("hallazgo_abierto sin accion", e))
    # El sello con campos de más (el LLM no debe inventar nada).
    e = base("run_finalizada"); e["payload"]["sello"]["garantia"] = "100% verdadero"
    casos.append(("sello con un campo no declarado", e))
    # Un seq cero.
    e = base("fuente_indexada"); e["seq"] = 0
    casos.append(("seq igual a 0", e))
    # Un evento de slide sin slide (el texto no sabría dónde dibujarse).
    e = base("escribir_texto"); e.pop("slide")
    casos.append(("escribir_texto sin slide", e))

    problemas = []
    for descripcion, evento in casos:
        if not list(validador.iter_errors(evento)):  # si pasa la validación, el esquema es demasiado permisivo
            problemas.append(f"debía ser rechazado y pasó: {descripcion}")
    # Y los eventos originales sin mutar sí deben pasar (control positivo).
    for e in eventos:
        if list(validador.iter_errors(e)):
            problemas.append(f"el evento original seq {e['seq']} ({e['tipo']}) debería ser válido")
    registrar("FALLA" if problemas else "OK", f"Pruebas negativas de eventos ({len(casos)} mutaciones rechazadas)", problemas)


# --------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------

def main():
    """Ejecuta todas las comprobaciones, imprime el resultado y devuelve el código de salida."""
    esquemas, registro = cargar_esquemas()
    comprobar_comentarios(esquemas)
    comprobar_catalogo_eventos(esquemas)
    fichas = cargar_fichas()
    comprobar_ejemplos_entrada(registro, fichas)
    comprobar_fichas(registro, fichas)
    comprobar_kits(registro)
    comprobar_grabaciones(registro, fichas)
    comprobar_pruebas_negativas(registro)

    fallas = 0
    # Imprime cada resultado con su estado y, si hay detalles, los lista debajo.
    for estado, titulo, detalles in RESULTADOS:
        etiqueta = {"OK": "[OK]    ", "FALLA": "[FALLA] ", "aviso": "[aviso] "}[estado]
        print(f"{etiqueta}{titulo}")
        for detalle in detalles:
            print(f"        - {detalle}")
        if estado == "FALLA":
            fallas += 1
    print()
    print("Todo en orden." if fallas == 0 else f"{fallas} comprobación(es) con fallas.")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
