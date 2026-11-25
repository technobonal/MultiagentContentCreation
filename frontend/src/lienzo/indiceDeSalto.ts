// ---------------------------------------------------------------------------
// indiceDeSalto.ts — Lógica pura de las miniaturas: a qué punto de la secuencia
// saltar para ver un slide y si un slide ya tiene algo que mostrar.
// No depende de React ni del DOM, así que se prueba sin navegador.
// ---------------------------------------------------------------------------
import type { Estado, Evento } from "../timeline/types.ts";

// Tipos de evento que dejan contenido visible en un slide (fondo, texto o borrador).
const TIPOS_CON_CONTENIDO: ReadonlySet<string> = new Set([
  "colocar_fondo",
  "colocar_imagen",
  "escribir_texto",
  "texto_propuesto",
  "corregir",
  "editada",
]);

/**
 * Devuelve cuántos eventos hay que aplicar (el índice que espera `irA`) para que el
 * slide ya tenga contenido, o null si ninguna parte de la secuencia le da contenido.
 */
export function indiceDeSalto(eventos: readonly Evento[], slide: number): number | null {
  // Se ordena una copia por seq: el reproductor aplica los eventos en ese orden.
  const ordenados = [...eventos].sort((a, b) => a.seq - b.seq);

  // Ciclo: busca el primer evento que da contenido a este slide.
  for (let i = 0; i < ordenados.length; i++) {
    const evento = ordenados[i];
    // Defensa por el acceso indexado: un hueco no debería ocurrir.
    if (evento === undefined) continue;
    // Es del slide pedido y de un tipo que se dibuja: el salto lo incluye (i + 1 eventos).
    if (evento.slide === slide && TIPOS_CON_CONTENIDO.has(evento.tipo)) return i + 1;
  }

  // Ningún evento da contenido a este slide.
  return null;
}

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