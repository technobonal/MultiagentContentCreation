/**
 * cargarPlantilla.ts — Carga el template.svg, corrige las rutas de sus tipografías y
 * lo convierte en un elemento SVG. Las rutas del SVG son relativas al archivo
 * ("../../typography/...") y dejan de servir al incrustarlo en la página.
 */

// Plantilla del MVP.
export const ID_PLANTILLA_POR_DEFECTO = "ig_carrusel_pasos_oscuro_6slides";

// Prefijo relativo que usan los @font-face del SVG.
const PREFIJO_FUENTES_SVG = "../../typography/";

// Clase que llevan los SVG de plantilla incrustados en la página.
export const CLASE_PLANTILLA = "plantilla-svg";

/**
 * El SVG se incrusta en la página, así que su <style> es CSS global: un `:root` con las variables de la plantilla
 * (--fondo, --texto, --acento) pisaba las de la aplicación y dejaba la pantalla ilegible. Se acota al propio SVG.
 */
export function aislarEstilos(texto: string): string {
  return texto.replace(/:root(?=\s*\{)/g, `.${CLASE_PLANTILLA}`);
}

// Asegura que la base termine en "/".
function conBarraFinal(base: string): string {
  return base.endsWith("/") ? base : `${base}/`;
}

/**
 * Reemplaza las rutas relativas de las tipografías por rutas absolutas desde la base
 * del sitio, donde scripts/copiar-plantillas.mjs deja los archivos (public/plantillas).
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

  const texto = await respuesta.text();

  // Vite responde con index.html (estado 200) cuando no encuentra el archivo:
  // se detecta aquí para dar un error claro en vez de un fallo de parseo.
  if (!texto.includes("<svg")) {
    throw new Error(
      `La ruta ${url} no devolvió un SVG (¿el servidor respondió con index.html?). Empieza con: ${texto.slice(0, 40)}`,
    );
  }
  return aislarEstilos(reescribirRutasDeFuentes(texto, base));
}

/**
 * Cargador con memoria por id: cada plantilla se descarga una sola vez, aunque la pidan varias pantallas.
 * Una carga que falla no se recuerda, así que se puede reintentar. `cargar` se inyecta para probarlo sin red.
 */
export function crearCargadorDePlantillas(
  cargar: (id: string) => Promise<string> = (id) => cargarPlantillaSvg(id),
): (id: string) => Promise<string> {
  const pedidas = new Map<string, Promise<string>>();
  return (id) => {
    let pedida = pedidas.get(id);
    if (pedida === undefined) {
      pedida = cargar(id);
      pedidas.set(id, pedida);
      pedida.catch(() => pedidas.delete(id));
    }
    return pedida;
  };
}

/** Convierte el texto del SVG en un elemento; lanza un error claro si no es XML válido. */
export function parsearPlantilla(texto: string): SVGSVGElement {
  const doc = new DOMParser().parseFromString(texto, "image/svg+xml");
  const error = doc.querySelector("parsererror");

  // El navegador no lanza al fallar el parseo: deja un <parsererror> en el documento.
  if (error) {
    throw new Error(`template.svg no es un SVG válido: ${error.textContent ?? ""}`);
  }
  const raiz = doc.documentElement as unknown as SVGSVGElement;
  raiz.classList.add(CLASE_PLANTILLA);
  return raiz;
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