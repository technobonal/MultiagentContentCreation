/**
 * Ajuste de texto de un campo del lienzo. Función pura, sin DOM: recibe el texto,
 * los tamaños de la plantilla y un medidor inyectado, y devuelve el tamaño elegido.
 */

// Estado final del ajuste: cabe tal cual, cabe tras encoger, o no cabe ni en el mínimo.
export type EstadoAjuste = "ok" | "encogido" | "desborda";

// Medidor inyectado: devuelve cuántas líneas ocupa el texto con ese tamaño y line-height.
// En producción mide el div real; en pruebas es falso.
export type Medidor = (
  texto: string,
  fuentePx: number,
  lineHeightPx: number,
) => number;

// Datos del campo que salen del SVG de la plantilla (tamaño base, data-fuente-min y data-lineas-max).
export interface EntradaAjuste {
  texto: string;
  fuenteBase: number;
  lineHeightBase: number;
  fuenteMin: number;
  lineasMax: number;
  paso?: number;
}

// Resultado: tamaño y line-height elegidos, líneas medidas y estado.
export interface ResultadoAjuste {
  fuentePx: number;
  lineHeightPx: number;
  lineas: number;
  estado: EstadoAjuste;
}

// Paso de reducción por defecto, en px.
export const PASO_PX_POR_DEFECTO = 2;

/**
 * Escala el line-height en la misma proporción que la fuente.
 * Sin esto, bajar solo la fuente no cambiaría el conteo de líneas.
 */
export function escalarLineHeight(
  lineHeightBase: number,
  fuenteBase: number,
  fuentePx: number,
): number {
  return Math.round((lineHeightBase * fuentePx) / fuenteBase);
}

/**
 * Baja la fuente de a `paso` px desde el tamaño base hasta `fuenteMin` y se detiene
 * en cuanto el texto cabe en `lineasMax`. Si en el mínimo no cabe, devuelve "desborda":
 * nunca recorta ni corrige el texto en silencio.
 */
export function ajustarTexto(
  entrada: EntradaAjuste,
  medir: Medidor,
): ResultadoAjuste {
  const { texto, fuenteBase, lineHeightBase, fuenteMin, lineasMax } = entrada;

  // Una fuente base no positiva rompería la escala del line-height.
  if (fuenteBase <= 0) {
    throw new Error("fuenteBase debe ser mayor que 0");
  }

  // Un paso inválido se reemplaza por el valor por defecto para evitar un ciclo infinito.
  const paso =
    entrada.paso !== undefined && entrada.paso > 0
      ? entrada.paso
      : PASO_PX_POR_DEFECTO;

  let fuente = fuenteBase;

  // Cada vuelta mide un tamaño; termina porque la fuente baja hasta fuenteMin.
  while (true) {
    const lineHeight = escalarLineHeight(lineHeightBase, fuenteBase, fuente);
    const lineas = medir(texto, fuente, lineHeight);

    // Cabe: "ok" si no hizo falta encoger, "encogido" si se redujo.
    if (lineas <= lineasMax) {
      return {
        fuentePx: fuente,
        lineHeightPx: lineHeight,
        lineas,
        estado: fuente === fuenteBase ? "ok" : "encogido",
      };
    }

    // Ya estamos en el mínimo (o por debajo desde el inicio) y no cabe: desborde visible.
    if (fuente <= fuenteMin) {
      return {
        fuentePx: fuente,
        lineHeightPx: lineHeight,
        lineas,
        estado: "desborda",
      };
    }

    // Se baja un paso, sin pasar del mínimo (el último paso puede ser menor).
    fuente = Math.max(fuente - paso, fuenteMin);
  }
}