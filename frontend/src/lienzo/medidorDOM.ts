import type { Medidor } from "./ajusteTexto.ts";

/**
 * Medidor de producción: mide en el div real del campo (alto del contenido entre
 * line-height), igual que el spike, para que lienzo y spike midan lo mismo.
 * Usa offsetHeight porque no se escala con el viewBox del SVG (getBoundingClientRect sí).
 */
export function crearMedidorDOM(div: HTMLElement): Medidor {
  return (texto, fuentePx, lineHeightPx) => {
    // El alto fijo del div haría que se mida la caja y no el contenido:
    // se libera mientras se mide y se restaura después.
    const altoOriginal = div.style.height;
    div.style.height = "auto";

    // textContent evita inyectar HTML.
    div.textContent = texto;
    div.style.fontSize = `${fuentePx}px`;
    div.style.lineHeight = `${lineHeightPx}px`;

    // Líneas = alto real del contenido entre el line-height.
    const lineas = Math.round(div.offsetHeight / lineHeightPx);

    // Se devuelve la caja a su alto original.
    div.style.height = altoOriginal;
    return lineas;
  };
}