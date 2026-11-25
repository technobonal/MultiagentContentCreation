"""Pruebas del cargador de fuente: sin red, solo archivos temporales."""

import hashlib
import os

import pytest

from app.fuentes.cargador_fuente import FuenteError, cargar_fuente, fragmentar

TEXTO_BASE = "Scrum es un marco de trabajo.\n\nEl Sprint dura de 1 a 4 semanas.\n"


def _escribir(carpeta, nombre, contenido, binario=False):
    """Crea un archivo en la carpeta temporal (texto UTF-8 o bytes) y devuelve su ruta."""
    ruta = carpeta / nombre
    if binario:
        ruta.write_bytes(contenido)
    else:
        ruta.write_text(contenido, encoding="utf-8", newline="")  # newline="" no toca los saltos
    return ruta


def _codigo(exc_info):
    """Devuelve el código estable del FuenteError capturado."""
    return exc_info.value.codigo


# ---------------------------------------------------------------- carga feliz

def test_carga_basica_calcula_sha_y_caracteres(tmp_path):
    """Un .txt simple se carga con su texto, su sha256 y su tamaño en caracteres."""
    _escribir(tmp_path, "guia.txt", TEXTO_BASE)
    f = cargar_fuente("guia.txt", carpeta=tmp_path)
    assert f.texto == TEXTO_BASE
    assert f.caracteres == len(TEXTO_BASE)
    assert f.sha256 == hashlib.sha256(TEXTO_BASE.encode("utf-8")).hexdigest()
    assert f.referencia == "guia.txt"


def test_extension_en_mayusculas_se_acepta(tmp_path):
    """La extensión se compara sin distinguir mayúsculas."""
    _escribir(tmp_path, "GUIA.MD", TEXTO_BASE)
    assert cargar_fuente("GUIA.MD", carpeta=tmp_path).texto == TEXTO_BASE


def test_acentos_y_enie_se_conservan(tmp_path):
    """No se altera ningún carácter fuera de los saltos de línea."""
    texto = "Año nuevo: ¿qué más? Compromiso, Coraje, Enfoque."
    _escribir(tmp_path, "a.txt", texto)
    assert cargar_fuente("a.txt", carpeta=tmp_path).texto == texto


def test_referencia_con_espacios_en_los_bordes_se_limpia(tmp_path):
    """Los espacios alrededor del nombre no cuentan."""
    _escribir(tmp_path, "guia.txt", TEXTO_BASE)
    assert cargar_fuente("  guia.txt ", carpeta=tmp_path).referencia == "guia.txt"


# ---------------------------------------------------------------- normalización

def test_crlf_se_normaliza_y_da_el_mismo_sha(tmp_path):
    """El mismo texto con \\r\\n o \\n produce la misma huella (clave en Windows)."""
    _escribir(tmp_path, "lf.txt", "uno\n\ndos\n")
    _escribir(tmp_path, "crlf.txt", "uno\r\n\r\ndos\r\n")
    a = cargar_fuente("lf.txt", carpeta=tmp_path)
    b = cargar_fuente("crlf.txt", carpeta=tmp_path)
    assert "\r" not in b.texto
    assert a.sha256 == b.sha256


def test_cr_suelto_tambien_se_normaliza(tmp_path):
    """Un \\r aislado (Mac clásico) pasa a \\n."""
    _escribir(tmp_path, "cr.txt", "uno\rdos")
    assert cargar_fuente("cr.txt", carpeta=tmp_path).texto == "uno\ndos"


def test_posiciones_son_sobre_el_texto_normalizado(tmp_path):
    """Con CRLF en el archivo, cada fragmento sigue siendo una porción exacta del texto cargado."""
    _escribir(tmp_path, "crlf.txt", "Párrafo uno.\r\n\r\nPárrafo dos.\r\n\r\nPárrafo tres.\r\n")
    f = cargar_fuente("crlf.txt", carpeta=tmp_path, max_chars=20)
    assert len(f.fragmentos) > 1
    for fr in f.fragmentos:
        assert f.texto[fr.inicio:fr.fin] == fr.texto


# ---------------------------------------------------------------- codificación

def test_bom_utf8_se_quita(tmp_path):
    """Un archivo UTF-8 con BOM no arrastra el carácter invisible."""
    _escribir(tmp_path, "bom.txt", b"\xef\xbb\xbfHola", binario=True)
    assert cargar_fuente("bom.txt", carpeta=tmp_path).texto == "Hola"


def test_utf16_con_bom_se_lee(tmp_path):
    """PowerShell guarda en UTF-16 con BOM: se decodifica bien."""
    _escribir(tmp_path, "ps.txt", "Hola ñandú".encode("utf-16"), binario=True)
    assert cargar_fuente("ps.txt", carpeta=tmp_path).texto == "Hola ñandú"


def test_cp1252_se_rechaza_con_mensaje_claro(tmp_path):
    """Un archivo en cp1252 (no UTF-8) da codificacion_invalida en vez de texto con signos raros."""
    _escribir(tmp_path, "viejo.txt", "Año".encode("cp1252"), binario=True)
    with pytest.raises(FuenteError) as e:
        cargar_fuente("viejo.txt", carpeta=tmp_path)
    assert _codigo(e) == "codificacion_invalida"


def test_binario_con_nul_se_rechaza(tmp_path):
    """Un archivo con bytes NUL no es texto."""
    _escribir(tmp_path, "bin.txt", b"abc\x00def", binario=True)
    with pytest.raises(FuenteError) as e:
        cargar_fuente("bin.txt", carpeta=tmp_path)
    assert _codigo(e) == "codificacion_invalida"


# ---------------------------------------------------------------- errores de archivo

def test_no_encontrada(tmp_path):
    """Un nombre que no existe da no_encontrada."""
    with pytest.raises(FuenteError) as e:
        cargar_fuente("nada.txt", carpeta=tmp_path)
    assert _codigo(e) == "no_encontrada"


def test_directorio_con_nombre_valido_no_es_fuente(tmp_path):
    """Una carpeta llamada x.txt no es un archivo de fuente."""
    (tmp_path / "x.txt").mkdir()
    with pytest.raises(FuenteError) as e:
        cargar_fuente("x.txt", carpeta=tmp_path)
    assert _codigo(e) == "no_encontrada"


@pytest.mark.parametrize("contenido", ["", "   \n\n \t\r\n"])
def test_fuente_vacia(tmp_path, contenido):
    """Archivo vacío o solo con blancos: vacia."""
    _escribir(tmp_path, "v.txt", contenido)
    with pytest.raises(FuenteError) as e:
        cargar_fuente("v.txt", carpeta=tmp_path)
    assert _codigo(e) == "vacia"


def test_demasiado_grande(tmp_path):
    """Pasar el límite de bytes se rechaza antes de leer."""
    _escribir(tmp_path, "g.txt", "x" * 100)
    with pytest.raises(FuenteError) as e:
        cargar_fuente("g.txt", carpeta=tmp_path, max_bytes=50)
    assert _codigo(e) == "demasiado_grande"


def test_exactamente_en_el_limite_pasa(tmp_path):
    """El límite es inclusivo."""
    _escribir(tmp_path, "g.txt", "x" * 50)
    assert cargar_fuente("g.txt", carpeta=tmp_path, max_bytes=50).caracteres == 50


# ---------------------------------------------------------------- extensión y referencia

@pytest.mark.parametrize("nombre", ["x.docx", "x", "x.md.exe"])
def test_otras_extensiones_se_rechazan(tmp_path, nombre):
    """Cualquier extensión que no sea .md, .txt o .pdf da extension_no_soportada."""
    with pytest.raises(FuenteError) as e:
        cargar_fuente(nombre, carpeta=tmp_path)
    assert _codigo(e) == "extension_no_soportada"


@pytest.mark.parametrize(
    "ref",
    ["", "   ", ".", "..", "../x.txt", "sub/x.txt", "sub\\x.txt", "C:\\x.txt", "x.txt:flujo", "/etc/passwd", "a\x00.txt"],
)
def test_referencias_que_no_son_un_nombre_simple(tmp_path, ref):
    """Rutas, unidades, flujos y NUL no se aceptan como referencia."""
    with pytest.raises(FuenteError) as e:
        cargar_fuente(ref, carpeta=tmp_path)
    assert _codigo(e) == "referencia_invalida"


def test_enlace_simbolico_que_sale_de_la_carpeta(tmp_path):
    """Un enlace dentro de la carpeta que apunta afuera se rechaza."""
    carpeta = tmp_path / "fuentes"
    carpeta.mkdir()
    fuera = tmp_path / "secreto.txt"
    fuera.write_text("no debe leerse", encoding="utf-8")
    try:
        os.symlink(fuera, carpeta / "enlace.txt")
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear enlaces simbólicos")
    with pytest.raises(FuenteError) as e:
        cargar_fuente("enlace.txt", carpeta=carpeta)
    assert _codigo(e) == "referencia_invalida"


# ---------------------------------------------------------------- fragmentación

def _parrafos(n, largo):
    """n párrafos de `largo` caracteres, cada uno con su número al inicio."""
    return [(f"P{i} " + "x" * largo)[:largo] for i in range(n)]


def _sin_blancos(s):
    """Quita todos los blancos, para comparar contenido sin importar el espaciado."""
    return "".join(s.split())


def test_texto_corto_es_un_solo_fragmento():
    """Un texto que cabe entero produce un fragmento con sus posiciones exactas."""
    texto = "Hola mundo.\n\nSegundo párrafo."
    frs = fragmentar(texto, max_chars=1000)
    assert len(frs) == 1
    assert (frs[0].inicio, frs[0].fin, frs[0].texto) == (0, len(texto), texto)


def test_texto_vacio_no_da_fragmentos():
    """Sin contenido no hay fragmentos."""
    assert fragmentar("  \n\n ", max_chars=100) == ()


def test_max_chars_invalido():
    """Un máximo menor que 1 es un error de programación."""
    with pytest.raises(ValueError):
        fragmentar("hola", max_chars=0)


def test_invariantes_de_los_fragmentos():
    """Posiciones exactas, orden, sin solape, índices correlativos, tamaño máximo y sin perder contenido."""
    parrafos = _parrafos(12, 300)
    texto = "\n\n".join(parrafos)
    frs = fragmentar(texto, max_chars=1000)
    assert len(frs) > 1
    previo_fin = 0
    for i, fr in enumerate(frs):
        assert fr.indice == i
        assert texto[fr.inicio:fr.fin] == fr.texto  # porción exacta
        assert len(fr.texto) <= 1000
        assert fr.inicio >= previo_fin  # sin solape y en orden
        assert fr.texto == fr.texto.strip()  # sin blancos en los bordes
        previo_fin = fr.fin
    # Nada se pierde: todo el contenido (sin blancos) está en algún fragmento.
    assert _sin_blancos("".join(fr.texto for fr in frs)) == _sin_blancos(texto)


def test_corta_en_limites_de_parrafo_cuando_caben():
    """Si todos los párrafos son menores al máximo, ningún fragmento corta un párrafo por la mitad."""
    parrafos = _parrafos(10, 300)
    texto = "\n\n".join(parrafos)
    for fr in fragmentar(texto, max_chars=1000):
        # Cada trozo entre líneas en blanco debe ser un párrafo completo.
        assert all(parte in parrafos for parte in fr.texto.split("\n\n"))


def test_titulo_y_parrafo_pegados_forman_un_bloque():
    """Un título seguido de su párrafo sin línea en blanco no se separa."""
    texto = "1. QUÉ ES SCRUM\nScrum es un marco ligero.\n\n2. VALORES\nSeis valores."
    frs = fragmentar(texto, max_chars=30)
    assert frs[0].texto.startswith("1. QUÉ ES SCRUM\nScrum")


def test_bloque_largo_se_parte_por_frases():
    """Un párrafo único más largo que el máximo se corta al final de una frase."""
    frase = "Esta es una frase de prueba con varias palabras. "
    texto = (frase * 40).strip()
    frs = fragmentar(texto, max_chars=200)
    assert len(frs) > 1
    for fr in frs:
        assert len(fr.texto) <= 200
        assert texto[fr.inicio:fr.fin] == fr.texto
        assert fr.texto.endswith(".")  # todos terminan en una frase completa
    assert _sin_blancos("".join(fr.texto for fr in frs)) == _sin_blancos(texto)


def test_bloque_sin_puntuacion_se_parte_en_espacios():
    """Sin finales de frase, se corta en un espacio y no a mitad de palabra."""
    texto = " ".join(f"palabra{i}" for i in range(80))
    frs = fragmentar(texto, max_chars=100)
    palabras = set(texto.split())
    for fr in frs:
        assert len(fr.texto) <= 100
        assert all(p in palabras for p in fr.texto.split())  # ninguna palabra cortada


def test_sin_espacios_corta_en_seco_pero_conserva_todo():
    """Un bloque sin ningún espacio se corta en el límite y no pierde caracteres."""
    texto = "a" * 250
    frs = fragmentar(texto, max_chars=100)
    assert [len(fr.texto) for fr in frs] == [100, 100, 50]
    assert "".join(fr.texto for fr in frs) == texto


def test_cargar_usa_el_maximo_por_defecto_de_config(tmp_path):
    """Sin max_chars explícito, se usa FRAGMENTO_MAX_CHARS de la configuración."""
    from app import config

    texto = "\n\n".join(_parrafos(30, 300))
    _escribir(tmp_path, "larga.txt", texto)
    f = cargar_fuente("larga.txt", carpeta=tmp_path)
    assert all(len(fr.texto) <= config.FRAGMENTO_MAX_CHARS for fr in f.fragmentos)
    assert len(f.fragmentos) > 1

# ---------------------------------------------------------------- PDF con texto

PARRAFO_1 = "El Sprint es un evento de duracion fija de un mes o menos para crear consistencia."
PARRAFO_2 = "El Scrum Team es lo bastante pequeno para seguir siendo agil y lo bastante grande para completar trabajo."


def _pdf(carpeta, nombre, paginas):
    """Crea un PDF real con PyMuPDF: `paginas` es una lista de listas de párrafos (un cuadro de texto por párrafo)."""
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    for parrafos in paginas:
        pagina = doc.new_page()
        y = 60
        for parrafo in parrafos:
            pagina.insert_textbox(fitz.Rect(50, y, 550, y + 80), parrafo, fontsize=11)
            y += 100
    ruta = carpeta / nombre
    doc.save(ruta)
    doc.close()
    return ruta


def test_pdf_con_texto_se_carga_con_un_parrafo_por_bloque(tmp_path):
    """Cada bloque del PDF es un párrafo separado por línea en blanco, y las citas caen en el texto extraído."""
    _pdf(tmp_path, "guia.pdf", [[PARRAFO_1, PARRAFO_2]])
    f = cargar_fuente("guia.pdf", carpeta=tmp_path)
    assert f.referencia == "guia.pdf"
    partes = f.texto.split("\n\n")
    assert len(partes) == 2
    # El ajuste de línea del PDF no deja saltos dentro del párrafo.
    assert all("\n" not in p for p in partes)
    assert partes[0].startswith("El Sprint es un evento") and partes[1].startswith("El Scrum Team")
    # Se cumple la regla de siempre: cada fragmento es una porción exacta del texto y el sha256 es el del texto.
    assert all(f.texto[fr.inicio:fr.fin] == fr.texto for fr in f.fragmentos)
    assert f.sha256 == hashlib.sha256(f.texto.encode("utf-8")).hexdigest()


def test_pdf_con_varias_paginas_junta_los_parrafos_en_orden(tmp_path):
    _pdf(tmp_path, "g.pdf", [[PARRAFO_1], [PARRAFO_2]])
    texto = cargar_fuente("g.pdf", carpeta=tmp_path).texto
    assert texto.index("El Sprint") < texto.index("El Scrum Team")


def test_pdf_une_las_palabras_cortadas_por_el_ajuste_de_linea(tmp_path):
    """«autoorga-» al final de una línea y «nizado» al inicio de la siguiente se leen como una palabra."""
    from app.fuentes import cargador_fuente as cf
    assert cf._GUION_DE_CORTE.sub(r"\1", "equipo autoorga-\nnizado y agil") == "equipo autoorganizado y agil"
    # Un guion real (la palabra siguiente empieza con mayúscula o número) se conserva.
    assert cf._GUION_DE_CORTE.sub(r"\1", "Scrum-\nMaster") == "Scrum-\nMaster"


def test_pdf_escaneado_sin_texto_se_rechaza_con_mensaje_claro(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    doc.new_page()  # una página en blanco se comporta como un escaneo sin capa de texto
    doc.save(tmp_path / "escaneo.pdf")
    doc.close()
    with pytest.raises(FuenteError) as e:
        cargar_fuente("escaneo.pdf", carpeta=tmp_path)
    assert _codigo(e) == "pdf_sin_texto" and "OCR" in e.value.mensaje


def test_pdf_dañado_da_pdf_invalido(tmp_path):
    _escribir(tmp_path, "roto.pdf", b"esto no es un pdf", binario=True)
    with pytest.raises(FuenteError) as e:
        cargar_fuente("roto.pdf", carpeta=tmp_path)
    assert _codigo(e) == "pdf_invalido"


def test_pdf_protegido_con_contrasena_se_rechaza(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    doc.new_page().insert_text((50, 60), PARRAFO_1)
    doc.save(tmp_path / "secreto.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="clave", owner_pw="clave")
    doc.close()
    with pytest.raises(FuenteError) as e:
        cargar_fuente("secreto.pdf", carpeta=tmp_path)
    assert _codigo(e) == "pdf_protegido"


def test_pdf_con_demasiadas_paginas_se_rechaza(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PDF_MAX_PAGINAS", 1)
    _pdf(tmp_path, "largo.pdf", [[PARRAFO_1], [PARRAFO_2]])
    with pytest.raises(FuenteError) as e:
        cargar_fuente("largo.pdf", carpeta=tmp_path)
    assert _codigo(e) == "pdf_demasiadas_paginas"


def test_pdf_mas_grande_que_el_tope_se_rechaza(tmp_path):
    _pdf(tmp_path, "g.pdf", [[PARRAFO_1, PARRAFO_2]])
    with pytest.raises(FuenteError) as e:
        cargar_fuente("g.pdf", carpeta=tmp_path, max_bytes=150)  # el PDF pesa más que 150 bytes: salta por el tamaño del archivo
    assert _codigo(e) == "demasiado_grande"


def test_pdf_escaneado_pesado_falla_por_falta_de_texto_y_no_por_tamano(tmp_path):
    """Un escaneo pesa mucho más que 200 KB: no debe rechazarse por el tope de texto de .md y .txt."""
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    pagina = doc.new_page()
    # Una imagen casi incompresible (ruido) hace que el archivo pese más que el tope de texto.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 600), False)
    pix.set_rect(pix.irect, (200, 30, 90))
    pagina.insert_image(pagina.rect, pixmap=pix)
    doc.save(tmp_path / "escaneo.pdf")
    doc.close()
    ruta = tmp_path / "escaneo.pdf"
    ruta.write_bytes(ruta.read_bytes() + os.urandom(300_000))  # relleno al final: el PDF sigue siendo válido
    assert ruta.stat().st_size > 204_800
    with pytest.raises(FuenteError) as e:
        cargar_fuente("escaneo.pdf", carpeta=tmp_path)
    assert _codigo(e) == "pdf_sin_texto"
