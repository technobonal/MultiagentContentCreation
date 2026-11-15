/**
 * pintarLienzo.ts — Pinta el estado del reductor sobre el SVG de la plantilla.
 * Solo lee `estado.lienzo.textos` y `estado.slideActivo`. Es idempotente: se puede
 * llamar en cada cambio de estado. No recorta ni corrige texto: si no cabe en el
 * tamaño mínimo, lo marca como desborde visible.
 */
import { ajustarTexto } from "./ajusteTexto.ts";
import type { Medidor, ResultadoAjuste } from "./ajusteTexto.ts";
import { crearMedidorDOM } from "./medidorDOM.ts";
import type { Estado } from "../timeline/types.ts";

// Crea el medidor de un campo; en pruebas se inyecta uno falso.
export type FabricaMedidor = (div: HTMLElement) => Medidor;

// Resultado por campo; `resultado` es null si no se ajustó (sin texto o slide inactivo).
export interface CampoPintado {
  readonly slide: number;
  readonly campo: string;
  readonly resultado: ResultadoAjuste | null;
}

// Color del marcador de desborde.
export const COLOR_DESBORDE = "#EF4444";

// Quita las llaves dobles: "{{titulo}}" -> "titulo".
export function nombreDeCampo(atributo: string): string {
  return atributo.replace(/^\{\{/, "").replace(/\}\}$/, "");
}

// Lee un atributo numérico; NaN si falta (Number(null) daría 0 y se confundiría con un valor real).
function numeroDeAtributo(el: Element, nombre: string): number {
  const valor = el.getAttribute(nombre);
  // Atributo ausente: NaN para que el llamador lo detecte.
  if (valor === null) return Number.NaN;
  return Number(valor);
}

// Quita el marcador de desborde y el estado de un div.
function limpiarMarcador(div: HTMLElement): void {
  div.style.outline = "";
  div.style.outlineOffset = "";
  delete div.dataset.estado;
}

/**
 * Pinta todos los slides: marca el activo, escribe los textos y ajusta el tamaño
 * de los campos del slide activo. Devuelve el resultado por campo.
 */
export function pintarLienzo(
  raiz: ParentNode,
  estado: Estado,
  fabrica: FabricaMedidor = crearMedidorDOM,
): CampoPintado[] {
  const resultados: CampoPintado[] = [];

  // Un ciclo por slide del SVG.
  for (const slide of Array.from(raiz.querySelectorAll<SVGElement>("g.slide"))) {
    const numero = Number(slide.id.replace("slide-", ""));
    // Un id que no sea "slide-N" no es un slide de la plantilla.
    if (!Number.isFinite(numero)) continue;

    // Solo el slide activo lleva la clase "activo".
    const activo = numero === estado.slideActivo;
    slide.classList.toggle("activo", activo);

    // Un ciclo por campo del slide (textos con div e imagen opcional sin div).
    for (const campoEl of Array.from(slide.querySelectorAll<SVGElement>("[data-campo]"))) {
      const nombre = nombreDeCampo(campoEl.getAttribute("data-campo") ?? "");
      const opcional = campoEl.getAttribute("data-opcional") === "true";
      const div = campoEl.querySelector<HTMLElement>("div");

      // Sin div no es un campo de texto (por ejemplo la imagen): el MVP la oculta siempre.
      if (!div) {
        // Las imágenes quedan para una fase posterior.
        if (opcional) campoEl.style.display = "none";
        continue;
      }

      // Se guarda el tamaño base la primera vez, para reajustar siempre desde él.
      if (div.dataset.baseFuente === undefined) {
        div.dataset.baseFuente = String(parseFloat(div.style.fontSize));
        div.dataset.baseLh = String(parseFloat(div.style.lineHeight));
      }
      const fuenteBase = Number(div.dataset.baseFuente);
      const lineHeightBase = Number(div.dataset.baseLh);

      const texto = estado.lienzo.textos[numero]?.[nombre];

      // Campo sin texto dibujado: se limpia; si es opcional se oculta del todo.
      if (texto === undefined) {
        div.textContent = "";
        div.style.fontSize = `${fuenteBase}px`;
        div.style.lineHeight = `${lineHeightBase}px`;
        limpiarMarcador(div);
        campoEl.style.display = opcional ? "none" : "";
        resultados.push({ slide: numero, campo: nombre, resultado: null });
        continue;
      }

      // Hay texto: el campo se muestra.
      campoEl.style.display = "";

      // Slide inactivo: se escribe el texto sin ajustar (puede estar en display:none y no medir).
      if (!activo) {
        div.textContent = texto;
        limpiarMarcador(div);
        resultados.push({ slide: numero, campo: nombre, resultado: null });
        continue;
      }

      const fuenteMin = numeroDeAtributo(campoEl, "data-fuente-min");
      const lineasMax = numeroDeAtributo(campoEl, "data-lineas-max");

      // Datos incompletos en el SVG: se escribe el texto con el tamaño base y no se ajusta.
      if (![fuenteBase, lineHeightBase, fuenteMin, lineasMax].every(Number.isFinite)) {
        div.textContent = texto;
        limpiarMarcador(div);
        resultados.push({ slide: numero, campo: nombre, resultado: null });
        continue;
      }

      // Ajuste puro con el medidor del campo.
      const resultado = ajustarTexto(
        { texto, fuenteBase, lineHeightBase, fuenteMin, lineasMax },
        fabrica(div),
      );

      // Se aplica el resultado de forma explícita (no se depende del último estado del medidor).
      div.textContent = texto;
      div.style.fontSize = `${resultado.fuentePx}px`;
      div.style.lineHeight = `${resultado.lineHeightPx}px`;
      div.dataset.estado = resultado.estado;

      // Desborde: marcador visible; nunca se recorta ni se corrige el texto.
      if (resultado.estado === "desborda") {
        div.style.outline = `4px dashed ${COLOR_DESBORDE}`;
        div.style.outlineOffset = "4px";
      } else {
        div.style.outline = "";
        div.style.outlineOffset = "";
      }

      resultados.push({ slide: numero, campo: nombre, resultado });
    }
  }

  return resultados;
}