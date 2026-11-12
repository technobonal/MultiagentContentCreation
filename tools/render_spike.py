#!/usr/bin/env python3
"""Spike de render (Fase 0): verifica que template.svg sea renderizable.

Abre template.svg en Chromium (Playwright), rellena los {{campos}} de cada slide con datos de
ejemplo, mide el desborde de cada campo y exporta un PNG de 1080x1350 por slide.
Corre dos casos: "ok" (textos dentro de longitud_max) y "desborde" (textos exagerados, para
comprobar que el detector de desborde funciona).

No es el renderer del backend (eso es Fase 1). Sirve para calibrar plantilla, zona segura y
tamaños, y para comprobar que el SVG y card.json no se desincronizaron.

Uso (desde la raíz del proyecto, con el venv activo):
    python tools/render_spike.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Raíz del proyecto: este archivo vive en <raíz>/tools/, así que se sube un nivel.
PROYECTO = Path(__file__).resolve().parents[1]
# Plantilla que se verifica y carpeta donde están su card.json y su template.svg.
PLANTILLA_ID = "ig_carrusel_pasos_oscuro_6slides"
CARPETA = PROYECTO / "templates" / "catalog" / PLANTILLA_ID
# Tamaño del carrusel de Instagram (card.json: formato carrusel_1080x1350).
ANCHO, ALTO = 1080, 1350

# Textos de ejemplo dentro de longitud_max de card.json (español neutro, tono del kit de marca).
CASO_OK: dict[int, dict[str, str]] = {
    1: {
        "{{titulo}}": "Cómo validar contratos antes de escribir código",
        "{{subtitulo}}": "Cuatro pasos para que los agentes no inventen datos.",
    },
    2: {
        "{{titulo}}": "El problema: los agentes inventan cifras",
        "{{cuerpo}}": "Si nadie comprueba la fuente, un modelo puede afirmar un dato falso con total "
                      "seguridad. Un revisor por código lo detecta a tiempo.",
    },
    3: {
        "{{titulo}}": "Paso 1: define los contratos",
        "{{cuerpo}}": "Cada evento y cada ficha se describe con un esquema JSON. Así el backend y el "
                      "frontend hablan el mismo idioma y los errores aparecen al validar, no en producción.",
    },
    4: {
        "{{titulo}}": "Paso 2: renderiza sin LLM",
        "{{cuerpo}}": "Un renderizador determinista coloca el texto en la plantilla. Si no entra en las "
                      "líneas permitidas, se mide el desborde y se corrige antes de revisar.",
    },
    5: {
        "{{titulo}}": "Pruébalo con tu propia fuente",
        "{{cta}}": "Sube un PDF o una URL y recibe un carrusel listo para revisar.",
    },
    6: {
        "{{fuente_atribucion}}": "Fuente: documentación técnica del proyecto MultiagentContentCreation, versión 7.",
        "{{fuente_licencia}}": "Licencia: CC BY 4.0",
        "{{sello_revision}}": "Revisado por código · 2026-11-11",
    },
}
# Mismos textos repetidos 30 veces: tienen que desbordar sí o sí. Sirve para comprobar que el
# detector funciona (si algo no desborda con esto, el detector está roto, no la plantilla).
CASO_DESBORDE: dict[int, dict[str, str]] = {
    n: {campo: " ".join([texto] * 30) for campo, texto in campos.items()} for n, campos in CASO_OK.items()
}

# Texto de relleno con largo de palabras parecido al español real, para el caso "limite".
TEXTO_BASE = ("Los agentes validan cada contrato con esquemas JSON antes de generar el contenido "
              "del carrusel final para su revisión humana y su publicación posterior. ")


def caso_limite(ficha: dict) -> dict[int, dict[str, str]]:
    """Un texto de exactamente longitud_max por cada campo de texto de card.json (el peor caso permitido)."""
    return {
        s["numero"]: {
            c["nombre"]: (TEXTO_BASE * 5)[: c["longitud_max"]].rstrip()
            for c in s["campos"] if c["tipo"] == "texto"
        }
        for s in ficha["slides"]
    }


# Se ejecuta dentro de la página: activa un slide, rellena los campos y mide cada uno.
JS_RELLENAR_Y_MEDIR = """
async ({n, datos}) => {
  await document.fonts.ready;   // espera a que carguen las tipografías antes de medir
  // Muestra solo el slide n (los demás tienen display:none) y toma su grupo.
  document.querySelectorAll('.slide').forEach(g => g.classList.toggle('activo', g.id === 'slide-' + n));
  const g = document.getElementById('slide-' + n);
  const filas = [];
  // Cada campo del SVG declara su nombre en data-campo ({{titulo}}, {{cuerpo}}, ...).
  g.querySelectorAll('[data-campo]').forEach(el => {
    const campo = el.getAttribute('data-campo');
    const fila = {campo};
    // Campo sin dato: si es opcional se oculta; si no, queda marcado para avisar del problema.
    if (!(campo in datos)) {
      if (el.getAttribute('data-opcional') === 'true') { el.style.display = 'none'; fila.estado = 'oculto'; }
      else { fila.estado = 'sin_dato'; }
      filas.push(fila);
      return;
    }
    // Rellena el texto del div que está dentro del foreignObject (textContent evita inyectar HTML).
    const div = el.firstElementChild;
    div.textContent = datos[campo];
    const estilo = getComputedStyle(div);
    fila.estado = 'ok';
    // scrollHeight nunca baja de la altura de la caja: para contar líneas reales se mide con height:auto.
    const alturaCaja = div.clientHeight;
    const alturaInline = div.style.height;
    div.style.height = 'auto';
    const alturaContenido = div.scrollHeight;
    div.style.height = alturaInline;
    // Líneas reales = altura del contenido / interlineado. Los límites vienen de los data-* del SVG.
    fila.alto_contenido = alturaContenido;   // px que necesita el texto
    fila.alto_caja = alturaCaja;             // px que tiene la caja
    fila.fuente_usada = estilo.fontFamily;   // lista de fuentes pedidas (la primera instalada es la que se usa)
    fila.lineas = Math.round(alturaContenido / parseFloat(estilo.lineHeight));
    fila.lineas_max = Number(el.getAttribute('data-lineas-max'));
    fila.fuente_px = parseFloat(estilo.fontSize);
    fila.fuente_min = Number(el.getAttribute('data-fuente-min'));
    // Desborda si el texto necesita más líneas que las permitidas. No se compara en píxeles: la fuente
    // puede sumar 1-3 px por métricas propias y eso no es un desborde (uno real agrega una línea entera).
    fila.desborda = fila.lineas > fila.lineas_max;
    filas.push(fila);
  });
  return filas;
}
"""


def desfases_con_ficha(ficha: dict, n: int, filas: list[dict]) -> list[str]:
    """Compara lo que declara el SVG (data-*) con card.json."""
    # Campos que card.json declara para este slide, indexados por nombre.
    esperado = {c["nombre"]: c for s in ficha["slides"] if s["numero"] == n for c in s["campos"]}
    problemas: list[str] = []
    vistos = set()
    for f in filas:
        campo = f["campo"]
        vistos.add(campo)
        c = esperado.get(campo)
        # Campo en el SVG que la ficha no conoce.
        if c is None:
            problemas.append(f"slide {n} {campo}: está en el SVG pero no en card.json")
            continue
        # Imágenes u ocultos no tienen límites de texto que comparar.
        if f["estado"] != "ok" or "lineas_max" not in c:
            continue
        # Límites del SVG distintos a los de la ficha (se desincronizaron).
        if f["lineas_max"] != c["lineas_max"]:
            problemas.append(f"slide {n} {campo}: lineas_max SVG={f['lineas_max']} ficha={c['lineas_max']}")
        if f["fuente_min"] != c["tamano_fuente_min"]:
            problemas.append(f"slide {n} {campo}: fuente_min SVG={f['fuente_min']} ficha={c['tamano_fuente_min']}")
        # El texto se dibuja más chico que el mínimo que exige la ficha.
        if f["fuente_px"] < c["tamano_fuente_min"]:
            problemas.append(f"slide {n} {campo}: fuente {f['fuente_px']}px < mínimo {c['tamano_fuente_min']}px")
    # Campos que la ficha pide y el SVG no tiene.
    for campo in sorted(set(esperado) - vistos):
        problemas.append(f"slide {n} {campo}: está en card.json pero falta en el SVG")
    return problemas


def main() -> int:
    """Corre los dos casos sobre los 6 slides, guarda PNG + reporte y devuelve 0 (ok) o 1 (hay problemas)."""
    # Evita errores de acentos al imprimir en la consola de Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # Rutas por defecto; se pueden cambiar con --svg, --ficha y --salida.
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--svg", type=Path, default=CARPETA / "template.svg")
    ap.add_argument("--ficha", type=Path, default=CARPETA / "card.json")
    ap.add_argument("--salida", type=Path, default=PROYECTO / "eval" / "results" / "render_spike")
    args = ap.parse_args()

    # Ficha de la plantilla (la fuente de verdad de límites) y carpeta de salida.
    ficha = json.loads(args.ficha.read_text(encoding="utf-8"))
    args.salida.mkdir(parents=True, exist_ok=True)

    problemas: list[str] = []   # todo lo que haga fallar el script
    avisos: list[str] = []      # hallazgos de calibración que no hacen fallar el script
    reporte: list[dict] = []    # una fila por campo medido, para reporte.json

    with sync_playwright() as p:
        # Navegador con la ventana del tamaño exacto del carrusel.
        navegador = p.chromium.launch()
        pagina = navegador.new_page(viewport={"width": ANCHO, "height": ALTO})
        # ok: texto normal | limite: texto de longitud_max exacta | desborde: texto exagerado.
        for caso, datos_caso in (("ok", CASO_OK), ("limite", caso_limite(ficha)), ("desborde", CASO_DESBORDE)):
            print(f"\n== Caso: {caso} ==")
            for n in range(1, 7):
                # Se recarga el SVG en cada slide para partir siempre de un estado limpio.
                pagina.goto(args.svg.resolve().as_uri())
                # Rellena y mide el slide n dentro de la página (ver JS_RELLENAR_Y_MEDIR).
                filas = pagina.evaluate(JS_RELLENAR_Y_MEDIR, {"n": n, "datos": datos_caso[n]})
                png = args.salida / f"slide-{n}_{caso}.png"
                pagina.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": ANCHO, "height": ALTO})

                # El cruce SVG vs card.json se hace una sola vez (en el caso ok).
                if caso == "ok":
                    problemas += desfases_con_ficha(ficha, n, filas)
                for f in filas:
                    f.update(caso=caso, slide=n)
                    reporte.append(f)
                    # Imprime cada campo y registra los problemas según el caso.
                    if f["estado"] == "sin_dato":
                        problemas.append(f"[{caso}] slide {n} {f['campo']}: quedó sin dato (placeholder visible)")
                        print(f"  slide {n} {f['campo']:<24} SIN DATO")
                    elif f["estado"] == "oculto":
                        print(f"  slide {n} {f['campo']:<24} oculto (opcional)")
                    else:
                        marca = "DESBORDA" if f["desborda"] else "ok"
                        print(f"  slide {n} {f['campo']:<24} {f['lineas']}/{f['lineas_max']} líneas  "
                              f"{f['fuente_px']:.0f}px (min {f['fuente_min']:.0f})  {marca}")
                        # ok: con texto válido no debe desbordar. desborde: tiene que desbordar.
                        if caso == "ok" and f["desborda"]:
                            problemas.append(f"[ok] slide {n} {f['campo']}: desborda con texto dentro de longitud_max")
                        # limite: si desborda, longitud_max y tamaño de fuente no cuadran (aviso, no falla).
                        if caso == "limite" and f["desborda"]:
                            avisos.append(f"slide {n} {f['campo']}: con longitud_max exacta necesita "
                                          f"{f['lineas']} líneas ({f['alto_contenido']}px) y la caja tiene "
                                          f"{f['lineas_max']} ({f['alto_caja']}px)")
                        if caso == "desborde" and not f["desborda"]:
                            problemas.append(f"[desborde] slide {n} {f['campo']}: el detector no vio desborde")
        navegador.close()

    # Guarda las mediciones y muestra el resumen; el código de salida refleja si hubo problemas.
    (args.salida / "reporte.json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPNG y reporte.json en: {args.salida}")
    if avisos:
        print("\nAvisos (calibración):")
        for a in avisos:
            print(f"  - {a}")
    if problemas:
        print("\nProblemas:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("\nTodo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())