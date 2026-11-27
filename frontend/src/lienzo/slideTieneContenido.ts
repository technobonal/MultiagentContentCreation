import type { Estado } from "../timeline/types.ts";

/**
 * true si el estado ya tiene algo para mostrar en el slide (texto, fondo o borrador).
 * Sirve para deshabilitar las miniaturas que todavía están vacías.
 */
export function slideTieneContenido(estado: Estado, slide: number): boolean {
  return (
    estado.lienzo.textos[slide] !== undefined ||
    estado.lienzo.fondos[slide] !== undefined ||
    estado.propuestas[slide] !== undefined
  );
}
