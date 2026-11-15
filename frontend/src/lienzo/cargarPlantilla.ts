/**
 * cargarPlantilla.ts — Carga el template.svg, corrige las rutas de sus tipografías y
 * lo convierte en un elemento SVG. Las rutas del SVG son relativas al archivo
 * ("../../typography/...") y dejan de servir al incrustarlo en la página.
 */

// Plantilla del MVP.
export const ID_PLANTILLA_POR_DEFECTO = "ig_carrusel_pasos_oscuro_6slides";

// Prefijo relativo que usan los @font-face del SVG.
const PREFIJO_FUENTES_SVG = "../../typography/";

// Asegura que la base termine en "/".
function conBarraFinal(base: string): string {
  return base.endsWith("/") ? base : `${base}/`;
}

/**
 * Reemplaza las rutas relativas de las tipografías por rutas absolutas desde la base
 * del sitio, donde vite-plugin-static-copy deja los archivos.
 */
export function reescribirRutasDeFuentes(texto: string, base: string): string {
  return texto
    .split(PREFIJO_FUENTES_SVG)
    .join(`${conBarraFinal(base)}plantillas/typography/`);
}

/** Descarga el template.svg y devuelve su texto con las rutas de fuentes ya corregidas. */
export async function cargarPlantillaSvg(
  id: string = ID_PLANTILLA_POR_DEFECTO,
  base: string = import.meta.env.BASE_URL,
): Promise<string> {
  const url = `${conBarraFinal(base)}plantillas/${id}/template.svg`;
  const respuesta = await fetch(url);

  // Una respuesta fallida no debe terminar pintando una página en blanco sin explicación.
  if (!respuesta.ok) {
    throw new Error(`No se pudo cargar la plantilla ${id} (${url}): HTTP ${respuesta.status}`);
  }
  return reescribirRutasDeFuentes(await respuesta.text(), base);
}

/** Convierte el texto del SVG en un elemento; lanza un error claro si no es XML válido. */
export function parsearPlantilla(texto: string): SVGSVGElement {
  const doc = new DOMParser().parseFromString(texto, "image/svg+xml");
  const error = doc.querySelector("parsererror");

  // El navegador no lanza al fallar el parseo: deja un <parsererror> en el documento.
  if (error) {
    throw new Error(`template.svg no es un SVG válido: ${error.textContent ?? ""}`);
  }
  return doc.documentElement as unknown as SVGSVGElement;
}

/**
 * Espera a que las tipografías de la plantilla estén cargadas antes de medir.
 * `document.fonts.ready` no basta: puede resolverse antes de que empiece la descarga,
 * porque las fuentes solo se piden cuando algo las usa. Por eso se cargan de forma explícita.
 */
export async function esperarFuentes(): Promise<void> {
  // Entornos sin API de fuentes (por ejemplo pruebas): nada que esperar.
  if (!("fonts" in document)) return;

  // Una fuente que falla no debe bloquear el lienzo: se usa la de respaldo.
  await Promise.allSettled([
    document.fonts.load('700 64px "Inter"'),
    document.fonts.load('600 40px "Inter"'),
    document.fonts.load('400 36px "Inter"'),
    document.fonts.load('400 24px "JetBrains Mono"'),
  ]);
}