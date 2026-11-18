/**
 * slideManual.ts — Reglas puras para ver a mano un slide que ningún evento activa
 * (por ejemplo el de fuentes y sello, cuyo texto lo calcula código, no un agente).
 * El "slide activo" del reductor lo marcan los eventos (dato del dominio); el slide
 * que el usuario mira es estado de interfaz. Aquí vive la regla que los separa,
 * sin tocar el reductor ni el reproductor.
 */
import { textoCampoCalculado } from "./camposCalculados.ts";
import { nombreDeCampo } from "./pintarLienzo.ts";
import type { Estado } from "../timeline/types.ts";

// Calcula el texto de un campo (inyectable en pruebas); undefined si no es un campo calculado.
export type Calculador = (estado: Estado, campo: string) => unknown;

// Nombres de campo (sin llaves) de cada slide, indexados por número de slide.
export type CamposPorSlide = Readonly<Record<number, readonly string[]>>;

// Slide elegido a mano y el último seq del reductor en el momento de elegirlo.
export interface SeleccionManual {
  readonly slide: number;
  readonly seq: number;
}

/**
 * Recorre los <g class="slide"> de la plantilla y devuelve los nombres de campo de cada uno.
 * Ejemplo: { 6: ["fuente_atribucion", "fuente_licencia", "sello_revision"] }.
 */
export function camposPorSlide(raiz: ParentNode): CamposPorSlide {
  const mapa: Record<number, string[]> = {};

  // Un ciclo por slide del SVG.
  for (const slide of Array.from(raiz.querySelectorAll<SVGElement>("g.slide"))) {
    const numero = Number(slide.id.replace("slide-", ""));
    // Un id que no sea "slide-N" no es un slide de la plantilla.
    if (!Number.isFinite(numero)) continue;

    // Un campo por cada elemento con data-campo (se quitan las llaves dobles).
    mapa[numero] = Array.from(slide.querySelectorAll("[data-campo]")).map((el) =>
      nombreDeCampo(el.getAttribute("data-campo") ?? ""),
    );
  }
  return mapa;
}

/**
 * true si algún campo calculado del slide ya tiene texto con el estado actual
 * (por ejemplo, la atribución de la fuente o el sello de revisión).
 */
export function slideTieneCalculado(
  estado: Estado,
  campos: readonly string[],
  calcular: Calculador = textoCampoCalculado,
): boolean {
  return campos.some((campo) => {
    const texto = calcular(estado, campo);
    // Solo cuenta un texto real; undefined o vacío significa que aún no hay nada que ver.
    return typeof texto === "string" && texto.trim() !== "";
  });
}

/**
 * Devuelve el slide elegido a mano mientras siga vigente, o null.
 * Es vigente solo si no ha llegado ningún evento nuevo desde que se eligió
 * (el seq del reductor sigue siendo el mismo).
 */
export function slideManualVigente(
  manual: SeleccionManual | null,
  ultimoSeq: number,
): number | null {
  // Sin elección, o con un evento nuevo de por medio, manda el slide activo del reductor.
  if (manual === null || manual.seq !== ultimoSeq) return null;
  return manual.slide;
}

/**
 * Devuelve el estado con el slide activo forzado al elegido a mano.
 * Sin elección vigente devuelve el MISMO objeto, para no provocar repintados de más.
 */
export function aplicarSlideManual(estado: Estado, slide: number | null): Estado {
  // Sin slide manual no se toca nada (misma referencia).
  if (slide === null) return estado;
  return { ...estado, slideActivo: slide };
}