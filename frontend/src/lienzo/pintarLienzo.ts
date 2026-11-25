/**
 * pintarLienzo.ts — Pinta el estado del reductor sobre el SVG de la plantilla.
 * Lee `estado.lienzo.textos`, `estado.lienzo.fondos`, `estado.lienzo.imagenes`, `estado.slideActivo` y los campos
 * calculados (sello, atribución y licencia de la fuente). Opcionalmente muestra los
 * borradores del redactor (`estado.propuestas`) en los campos que aún no tienen texto
 * dibujado, marcados con data-borrador="true". Es idempotente: se puede llamar
 * en cada cambio de estado. No recorta ni corrige texto: si no cabe en el tamaño mínimo,
 * lo marca como desborde visible.
 */
import { ajustarTexto } from "./ajusteTexto.ts";
import type { Medidor, ResultadoAjuste } from "./ajusteTexto.ts";
import { textoCampoCalculado } from "./camposCalculados.ts";
import { crearMedidorDOM } from "./medidorDOM.ts";
import type { Estado, ImagenColocada } from "../timeline/types.ts";

// Crea el medidor de un campo; en pruebas se inyecta uno falso.
export type FabricaMedidor = (div: HTMLElement) => Medidor;

// Opciones de pintado.
export interface OpcionesPintado {
  // Si es true, los campos sin texto dibujado muestran el borrador del redactor.
  readonly borradores?: boolean;
}

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

// Marca o desmarca un div como borrador (el estilo atenuado vive en style.css).
function marcarBorrador(div: HTMLElement, esBorrador: boolean): void {
  if (esBorrador) {
    div.dataset.borrador = "true";
  } else {
    delete div.dataset.borrador;
  }
}

/**
 * Pinta el fondo: el SVG tiene un solo <rect id="fondo">, así que se usa el fondo del
 * slide activo. Un fondo de tipo imagen se ignora en el MVP (queda el color de la plantilla).
 */
function pintarFondo(raiz: ParentNode, estado: Estado): void {
  const rect = raiz.querySelector("#fondo");
  // Plantilla sin <rect id="fondo">: nada que pintar.
  if (!rect) return;

  // Se guarda el color original la primera vez, para poder restaurarlo.
  if (rect.getAttribute("data-fondo-base") === null) {
    rect.setAttribute("data-fondo-base", rect.getAttribute("fill") ?? "");
  }
  const base = rect.getAttribute("data-fondo-base") ?? "";

  const fondo = estado.lienzo.fondos[estado.slideActivo];
  const color = fondo !== undefined && fondo.tipo === "color" ? fondo.valor : base;

  // Sin color que aplicar (ni propio ni de la plantilla), no se toca el atributo.
  if (color === "") return;
  rect.setAttribute("fill", color);
}

/**
 * Pinta (o limpia) la imagen de un campo de imagen de la plantilla. La URL la sirve el backend por run y referencia.
 * Es idempotente: solo toca el <image> cuando cambia la referencia. Mientras carga queda transparente y, al cargar,
 * entra con un fundido (CSS) y oculta el borde punteado del hueco; si falla, el hueco punteado queda a la vista.
 */
function pintarImagen(campoEl: SVGElement, imagen: ImagenColocada | undefined, runId: string | null, opcional: boolean): void {
  const img = campoEl.querySelector("image");
  const hueco = campoEl.querySelector<SVGElement>("rect");
  if (!img) {
    // Sin <image> no hay dónde dibujar: se oculta si es opcional (como antes de que hubiera imágenes).
    if (opcional) campoEl.style.display = "none";
    return;
  }
  // Sin imagen dibujada (o sin run al que pedírsela): el campo opcional se oculta y se olvida lo anterior.
  if (imagen === undefined || runId === null) {
    img.removeAttribute("data-ref");
    img.removeAttribute("data-cargada");
    img.removeAttribute("data-error");
    img.removeAttribute("href");
    if (hueco) hueco.style.display = "";
    campoEl.style.display = opcional ? "none" : "";
    return;
  }
  const url = `/api/runs/${encodeURIComponent(runId)}/imagenes/${encodeURIComponent(imagen.referencia)}`;
  campoEl.style.display = "";
  campoEl.setAttribute("data-licencia", imagen.licencia);
  const titulo = campoEl.querySelector("title");
  if (titulo) titulo.textContent = imagen.texto_alternativo;
  img.setAttribute("aria-label", imagen.texto_alternativo);
  // La misma imagen ya está pedida: no se vuelve a asignar (reiniciaría la carga y el fundido).
  if (img.getAttribute("data-ref") === url) return;
  img.setAttribute("data-ref", url);
  img.removeAttribute("data-cargada");
  img.removeAttribute("data-error");
  if (hueco) hueco.style.display = "";
  img.addEventListener("load", () => {
    if (img.getAttribute("data-ref") !== url) return; // llegó tarde: ya hay otra imagen
    img.setAttribute("data-cargada", "true");
    if (hueco) hueco.style.display = "none";
  }, { once: true });
  img.addEventListener("error", () => {
    if (img.getAttribute("data-ref") === url) img.setAttribute("data-error", "true");
  }, { once: true });
  img.setAttribute("href", url);
}

/**
 * Pinta todos los slides: marca el activo, escribe los textos y ajusta el tamaño
 * de los campos del slide activo. Devuelve el resultado por campo.
 */
export function pintarLienzo(
  raiz: ParentNode,
  estado: Estado,
  fabrica: FabricaMedidor = crearMedidorDOM,
  opciones: OpcionesPintado = {},
): CampoPintado[] {
  const resultados: CampoPintado[] = [];

  pintarFondo(raiz, estado);

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

      // Sin div no es un campo de texto sino un campo de imagen: se dibuja la imagen del evento colocar_imagen.
      if (!div) {
        pintarImagen(campoEl, estado.lienzo.imagenes[numero]?.[nombre], estado.runId, opcional);
        continue;
      }

      // Se guarda el tamaño base la primera vez, para reajustar siempre desde él.
      if (div.dataset.baseFuente === undefined) {
        div.dataset.baseFuente = String(parseFloat(div.style.fontSize));
        div.dataset.baseLh = String(parseFloat(div.style.lineHeight));
      }
      const fuenteBase = Number(div.dataset.baseFuente);
      const lineHeightBase = Number(div.dataset.baseLh);

      // Un evento de texto tiene prioridad; si no hay, se usa el campo calculado por código.
      const dibujado = estado.lienzo.textos[numero]?.[nombre] ?? textoCampoCalculado(estado, nombre);
      // Sin texto dibujado, y si se pidió, se muestra el borrador del redactor.
      const borrador =
        opciones.borradores === true && dibujado === undefined
          ? estado.propuestas[numero]?.[nombre]
          : undefined;
      const texto = dibujado ?? borrador;
      marcarBorrador(div, dibujado === undefined && borrador !== undefined);

      // Campo sin texto: se limpia; si es opcional se oculta del todo.
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